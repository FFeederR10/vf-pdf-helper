from __future__ import annotations

import math
import os
import tempfile
import threading
import winreg
from dataclasses import dataclass
from pathlib import Path

import nanoprc_py
import numpy as np
from PySide6.QtCore import QObject, QPointF, QProcess, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QMatrix4x4,
    QMouseEvent,
    QSurfaceFormat,
    QWheelEvent,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFunctions_2_1,
    QOpenGLShader,
    QOpenGLShaderProgram,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .u3d import U3DDecodeCancelled, U3DScene, decode_u3d_scene


class ThreeDViewError(RuntimeError):
    """Raised when an embedded model cannot be prepared for interactive viewing."""


def find_adobe_executable() -> Path | None:
    """Locate an installed Adobe Acrobat or Reader executable on Windows."""
    registry_names = ("Acrobat.exe", "AcroRd32.exe")
    registry_roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    registry_flags = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for root in registry_roots:
        for name in registry_names:
            for flag in registry_flags:
                try:
                    with winreg.OpenKey(
                        root,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}",
                        0,
                        winreg.KEY_READ | flag,
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                except OSError:
                    continue
                candidate = Path(os.path.expandvars(str(value))).resolve()
                if candidate.is_file():
                    return candidate

    program_files = [
        Path(value)
        for value in {
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
        }
        if value
    ]
    relative_paths = (
        Path("Adobe/Acrobat DC/Acrobat/Acrobat.exe"),
        Path("Adobe/Acrobat Reader DC/Reader/AcroRd32.exe"),
        Path("Adobe/Acrobat Reader/Reader/AcroRd32.exe"),
    )
    for root in program_files:
        for relative in relative_paths:
            candidate = (root / relative).resolve()
            if candidate.is_file():
                return candidate
    return None


def launch_adobe(executable: Path, pdf_path: Path) -> bool:
    result = QProcess.startDetached(str(executable), [str(pdf_path)])
    return bool(result[0] if isinstance(result, tuple) else result)


# OpenGL 2.1 constants used by QOpenGLFunctions_2_1.
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_MULTISAMPLE = 0x809D
GL_LIGHTING = 0x0B50
GL_LIGHT0 = 0x4000
GL_COLOR_MATERIAL = 0x0B57
GL_FRONT_AND_BACK = 0x0408
GL_AMBIENT_AND_DIFFUSE = 0x1602
GL_SMOOTH = 0x1D01
GL_NORMALIZE = 0x0BA1
GL_PROJECTION = 0x1701
GL_MODELVIEW = 0x1700
GL_VERTEX_ARRAY = 0x8074
GL_NORMAL_ARRAY = 0x8075
GL_FLOAT = 0x1406
GL_UNSIGNED_INT = 0x1405
GL_FILL = 0x1B02
GL_LINE = 0x1B01
GL_TRIANGLES = 0x0004
GL_TRIANGLE_STRIP = 0x0005
GL_TRIANGLE_FAN = 0x0006
GL_LINES = 0x0001
GL_LINE_STRIP = 0x0003
GL_LINE_LOOP = 0x0002

PRIMITIVE_MODES = {
    0: GL_TRIANGLES,
    1: GL_TRIANGLE_FAN,
    2: GL_TRIANGLE_STRIP,
    3: GL_LINES,
    4: GL_LINE_STRIP,
    5: GL_LINE_LOOP,
}


@dataclass
class CpuMesh:
    positions: np.ndarray
    normals: np.ndarray | None
    indices: np.ndarray
    mode: int
    color: tuple[float, float, float, float]


@dataclass
class GpuMesh:
    vertex_buffer: QOpenGLBuffer
    color_buffer: QOpenGLBuffer
    vertex_count: int
    mode: int
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class ModelStats:
    tessellations: int
    faces: int
    primitives: int
    vertices: int


def _normalise_rows(values: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(values, axis=1)
    valid = lengths > 1e-12
    result = np.zeros_like(values, dtype=np.float32)
    if np.any(valid):
        result[valid] = values[valid] / lengths[valid, np.newaxis]
    result[~valid] = (0.0, 0.0, 1.0)
    return np.ascontiguousarray(result, dtype=np.float32)


def _triangles(indices: np.ndarray, mode: int):
    if mode == GL_TRIANGLES:
        for offset in range(0, len(indices) - 2, 3):
            yield int(indices[offset]), int(indices[offset + 1]), int(indices[offset + 2])
    elif mode == GL_TRIANGLE_STRIP:
        for offset in range(0, len(indices) - 2):
            first, second, third = (
                int(indices[offset]),
                int(indices[offset + 1]),
                int(indices[offset + 2]),
            )
            if offset % 2:
                first, second = second, first
            yield first, second, third
    elif mode == GL_TRIANGLE_FAN and len(indices) >= 3:
        first = int(indices[0])
        for offset in range(1, len(indices) - 1):
            yield first, int(indices[offset]), int(indices[offset + 1])


def _generated_normals(positions: np.ndarray, indices: np.ndarray, mode: int) -> np.ndarray | None:
    if mode not in {GL_TRIANGLES, GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN}:
        return None
    normals = np.zeros_like(positions, dtype=np.float32)
    vertex_count = len(positions)
    for first, second, third in _triangles(indices, mode):
        if first >= vertex_count or second >= vertex_count or third >= vertex_count:
            continue
        normal = np.cross(positions[second] - positions[first], positions[third] - positions[first])
        if float(np.linalg.norm(normal)) <= 1e-12:
            continue
        normals[first] += normal
        normals[second] += normal
        normals[third] += normal
    return _normalise_rows(normals)


def _material_color(material: dict) -> tuple[float, float, float, float]:
    fallback = (0.72, 0.78, 0.88, 1.0)
    if not material or not material.get("is_material"):
        return fallback
    values = material.get("material", {})
    diffuse = values.get("diffuse")
    if diffuse is None or len(diffuse) < 3:
        return fallback
    try:
        alpha = float(values.get("diffuse_alpha", 1.0))
        if alpha <= 0.0:
            alpha = 1.0
        return tuple(float(max(0.0, min(1.0, value))) for value in diffuse[:3]) + (alpha,)
    except (TypeError, ValueError):
        return fallback


class PrcCanvas(QOpenGLWidget):
    """A compact OpenGL canvas for PRC and decoded U3D triangle meshes."""

    render_failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        surface = QSurfaceFormat()
        surface.setVersion(2, 1)
        surface.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        surface.setDepthBufferSize(24)
        surface.setSamples(4)
        self.setFormat(surface)
        self.setMinimumSize(720, 500)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._context: nanoprc_py.Context | None = None
        self._document = None
        self._cpu_meshes: list[CpuMesh] = []
        self._gpu_meshes: list[GpuMesh] = []
        self._gl: QOpenGLFunctions_2_1 | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._render_error = ""
        self._scene_center = np.zeros(3, dtype=np.float32)
        self._scene_radius = 1.0
        self._yaw = 35.0
        self._pitch = -20.0
        self._distance = 3.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_mouse = QPointF()
        self._drag_mode = ""
        self._wireframe = False
        self._lighting = True
        self._show_outlines = True
        self.stats = ModelStats(0, 0, 0, 0)

    def load_prc(self, path: str) -> ModelStats:
        try:
            context = nanoprc_py.Context()
            document = context.open(path)
            document.prepare_model_tree()
            document.create_model_tree()
            tessellation_count = int(document.tessellation_counts()[0])
        except Exception as exc:
            raise ThreeDViewError(f"The embedded PRC model could not be parsed: {exc}") from exc
        if tessellation_count < 1:
            raise ThreeDViewError("The embedded PRC model contains no surface tessellations.")

        meshes: list[CpuMesh] = []
        bounds_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
        bounds_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
        face_total = 0
        vertex_total = 0
        try:
            for tessellation in range(tessellation_count):
                face_count = int(document.number_of_faces(tessellation))
                face_total += face_count
                for face in range(face_count):
                    positions = np.asarray(
                        document.face_vertex_positions(tessellation, face), dtype=np.float32
                    ).reshape((-1, 3))
                    if positions.size == 0:
                        continue
                    positions = np.ascontiguousarray(positions, dtype=np.float32)
                    vertex_total += len(positions)
                    bounds_min = np.minimum(bounds_min, positions.min(axis=0))
                    bounds_max = np.maximum(bounds_max, positions.max(axis=0))

                    raw_normals = np.asarray(
                        document.face_vertex_normals(tessellation, face), dtype=np.float32
                    )
                    normals = None
                    if raw_normals.size == positions.size:
                        normals = _normalise_rows(raw_normals.reshape((-1, 3)))
                    color = _material_color(document.face_material(tessellation, face))
                    primitive_count = int(
                        document.face_graphics_primitive_count(tessellation, face)
                    )
                    for primitive_index in range(primitive_count):
                        primitive = document.get_graphics_primitive(
                            tessellation, face, primitive_index
                        )
                        indices = np.ascontiguousarray(
                            np.asarray(primitive.get("indices", ()), dtype=np.uint32).reshape(-1)
                        )
                        if indices.size == 0:
                            continue
                        if int(indices.max()) >= len(positions):
                            raise ThreeDViewError(
                                "The PRC model contains an out-of-range geometry index."
                            )
                        mode = PRIMITIVE_MODES.get(int(primitive.get("type", 0)), GL_TRIANGLES)
                        mesh_normals = normals
                        if mesh_normals is None:
                            mesh_normals = _generated_normals(positions, indices, mode)
                        meshes.append(
                            CpuMesh(positions, mesh_normals, indices, mode, color)
                        )
        except Exception as exc:
            raise ThreeDViewError(f"The PRC geometry could not be prepared: {exc}") from exc

        if not meshes or not np.all(np.isfinite(bounds_min)) or not np.all(np.isfinite(bounds_max)):
            raise ThreeDViewError("The embedded PRC model has no renderable geometry.")

        self._context = context
        self._document = document
        self._cpu_meshes = meshes
        self._set_bounds(bounds_min, bounds_max)
        self.stats = ModelStats(
            tessellations=tessellation_count,
            faces=face_total,
            primitives=len(meshes),
            vertices=vertex_total,
        )
        self.reset_view()
        return self.stats

    def load_u3d(self, scene: U3DScene) -> ModelStats:
        meshes = [
            CpuMesh(
                mesh.positions,
                mesh.normals,
                mesh.indices,
                GL_LINES if mesh.primitive == "lines" else GL_TRIANGLES,
                mesh.color,
            )
            for mesh in scene.meshes
            if len(mesh.positions) and len(mesh.indices)
        ]
        if not meshes:
            raise ThreeDViewError("The decoded U3D preview contains no renderable geometry.")
        bounds_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
        bounds_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)
        for mesh in meshes:
            bounds_min = np.minimum(bounds_min, mesh.positions.min(axis=0))
            bounds_max = np.maximum(bounds_max, mesh.positions.max(axis=0))
        if not np.all(np.isfinite(bounds_min)) or not np.all(np.isfinite(bounds_max)):
            raise ThreeDViewError("The decoded U3D preview has invalid geometry bounds.")
        self._context = None
        self._document = None
        self._cpu_meshes = meshes
        self._set_bounds(bounds_min, bounds_max)
        self.stats = ModelStats(
            tessellations=scene.resource_count,
            faces=scene.rendered_faces,
            primitives=len(meshes),
            vertices=sum(len(mesh.positions) for mesh in meshes),
        )
        self.reset_view()
        return self.stats

    def _set_bounds(self, minimum: np.ndarray, maximum: np.ndarray) -> None:
        self._scene_center = ((minimum + maximum) * 0.5).astype(np.float32)
        radius = float(np.linalg.norm(maximum - minimum) * 0.5)
        self._scene_radius = max(radius, 0.1)

    def reset_view(self) -> None:
        self._yaw = 35.0
        self._pitch = -20.0
        self._distance = self._scene_radius * 2.8
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def set_wireframe(self, enabled: bool) -> None:
        self._wireframe = enabled
        self.update()

    def set_lighting(self, enabled: bool) -> None:
        self._lighting = enabled
        if self.isValid() and self._gl is not None:
            try:
                self.makeCurrent()
                self._upload_meshes()
            except Exception as exc:
                self._render_error = str(exc)
                self.render_failed.emit(self._render_error)
            finally:
                self.doneCurrent()
        self.update()

    def set_outlines(self, enabled: bool) -> None:
        self._show_outlines = enabled
        self.update()

    def initializeGL(self) -> None:  # type: ignore[override]
        try:
            self._gl = QOpenGLFunctions_2_1()
            if not self._gl.initializeOpenGLFunctions():
                raise ThreeDViewError("OpenGL 2.1 compatibility functions are unavailable.")
            self._program = QOpenGLShaderProgram(self)
            vertex_shader = """
                attribute highp vec3 position;
                attribute lowp vec4 vertexColor;
                uniform highp mat4 mvpMatrix;
                varying lowp vec4 modelColor;
                void main() {
                    modelColor = vertexColor;
                    gl_Position = mvpMatrix * vec4(position, 1.0);
                }
            """
            fragment_shader = """
                varying lowp vec4 modelColor;
                void main() {
                    gl_FragColor = modelColor;
                }
            """
            if not self._program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, vertex_shader
            ):
                raise ThreeDViewError(f"The 3D vertex shader failed: {self._program.log()}")
            if not self._program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, fragment_shader
            ):
                raise ThreeDViewError(f"The 3D fragment shader failed: {self._program.log()}")
            if not self._program.link():
                raise ThreeDViewError(f"The 3D shader could not be linked: {self._program.log()}")
            self._gl.glClearColor(0.965, 0.975, 0.992, 1.0)
            self._gl.glEnable(GL_DEPTH_TEST)
            self._gl.glEnable(GL_BLEND)
            self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self._gl.glEnable(GL_MULTISAMPLE)
            self._upload_meshes()
            context = self.context()
            if context is not None:
                context.aboutToBeDestroyed.connect(self._context_about_to_be_destroyed)
        except Exception as exc:
            self._render_error = str(exc)
            self.render_failed.emit(self._render_error)

    def _context_about_to_be_destroyed(self) -> None:
        self.makeCurrent()
        self._destroy_gpu_meshes()
        self.doneCurrent()

    def _new_buffer(self, buffer_type: QOpenGLBuffer.Type, data: bytes) -> QOpenGLBuffer:
        buffer = QOpenGLBuffer(buffer_type)
        if not buffer.create() or not buffer.bind():
            raise ThreeDViewError("A graphics buffer could not be created.")
        buffer.allocate(data, len(data))
        buffer.release()
        return buffer

    def _upload_meshes(self) -> None:
        self._destroy_gpu_meshes()
        for mesh in self._cpu_meshes:
            positions = np.ascontiguousarray(mesh.positions[mesh.indices], dtype=np.float32)
            if mesh.normals is None:
                normals = np.zeros_like(positions, dtype=np.float32)
                normals[:, 2] = 1.0
            else:
                normals = np.ascontiguousarray(mesh.normals[mesh.indices], dtype=np.float32)
            base_color = np.asarray(mesh.color, dtype=np.float32)
            colors = np.tile(base_color, (len(positions), 1))
            if self._lighting:
                light = np.asarray((0.35, 0.55, 0.75), dtype=np.float32)
                light /= np.linalg.norm(light)
                shades = 0.28 + 0.72 * np.abs(normals @ light)
                colors[:, :3] *= shades[:, np.newaxis]
            colors = np.ascontiguousarray(colors, dtype=np.float32)
            vertex_buffer = self._new_buffer(
                QOpenGLBuffer.Type.VertexBuffer, positions.tobytes()
            )
            color_buffer = self._new_buffer(
                QOpenGLBuffer.Type.VertexBuffer, colors.tobytes()
            )
            self._gpu_meshes.append(
                GpuMesh(
                    vertex_buffer,
                    color_buffer,
                    len(positions),
                    mesh.mode,
                    mesh.color,
                )
            )

    def _destroy_gpu_meshes(self) -> None:
        for mesh in self._gpu_meshes:
            if mesh.vertex_buffer.isCreated():
                mesh.vertex_buffer.destroy()
            if mesh.color_buffer.isCreated():
                mesh.color_buffer.destroy()
        self._gpu_meshes.clear()

    def resizeGL(self, width: int, height: int) -> None:  # type: ignore[override]
        if self._gl is not None:
            self._gl.glViewport(0, 0, width, max(1, height))

    def paintGL(self) -> None:  # type: ignore[override]
        gl = self._gl
        program = self._program
        if gl is None or program is None:
            return
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._render_error:
            return
        width = max(1, self.width())
        height = max(1, self.height())
        padding = max(self._scene_radius * 0.35, 0.1)
        near = max(0.01, self._distance - self._scene_radius - padding)
        far = max(near + 1.0, self._distance + self._scene_radius + padding)
        half_height = near * math.tan(math.radians(45.0) * 0.5)
        half_width = half_height * width / height

        projection = QMatrix4x4()
        projection.frustum(-half_width, half_width, -half_height, half_height, near, far)
        view = QMatrix4x4()
        view.translate(self._pan_x, self._pan_y, -self._distance)
        model = QMatrix4x4()
        model.rotate(self._pitch, 1.0, 0.0, 0.0)
        model.rotate(self._yaw, 0.0, 1.0, 0.0)
        model.translate(
            -float(self._scene_center[0]),
            -float(self._scene_center[1]),
            -float(self._scene_center[2]),
        )
        program.bind()
        program.setUniformValue(program.uniformLocation("mvpMatrix"), projection * view * model)
        position_location = program.attributeLocation("position")
        color_location = program.attributeLocation("vertexColor")
        for mesh in self._gpu_meshes:
            if mesh.mode == GL_LINES and not self._show_outlines:
                continue
            mesh.vertex_buffer.bind()
            program.enableAttributeArray(position_location)
            program.setAttributeBuffer(position_location, GL_FLOAT, 0, 3, 12)
            mesh.color_buffer.bind()
            program.enableAttributeArray(color_location)
            program.setAttributeBuffer(color_location, GL_FLOAT, 0, 4, 16)
            gl.glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self._wireframe else GL_FILL)
            gl.glLineWidth(1.0)
            gl.glDrawArrays(mesh.mode, 0, mesh.vertex_count)
            program.disableAttributeArray(color_location)
            program.disableAttributeArray(position_location)
            mesh.color_buffer.release()
            mesh.vertex_buffer.release()
        gl.glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        program.release()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._last_mouse = event.position()
        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton} or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._drag_mode = "pan"
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag_mode = "rotate"
        self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        delta = event.position() - self._last_mouse
        self._last_mouse = event.position()
        if self._drag_mode == "rotate":
            self._yaw += delta.x() * 0.45
            self._pitch = max(-89.0, min(89.0, self._pitch + delta.y() * 0.45))
        elif self._drag_mode == "pan":
            scale = self._distance / max(250.0, float(min(self.width(), self.height())))
            self._pan_x += delta.x() * scale
            self._pan_y -= delta.y() * scale
        else:
            return
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._drag_mode = ""
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.reset_view()
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        steps = event.angleDelta().y() / 120.0
        self._distance *= math.pow(0.88, steps)
        self._distance = max(
            self._scene_radius * 0.08,
            min(self._scene_radius * 50.0, self._distance),
        )
        self.update()
        event.accept()


class _U3DDecoderWorker(QObject):
    progress = Signal(int, str)
    decoded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, model_data: bytes, stop_event: threading.Event) -> None:
        super().__init__()
        self._model_data = model_data
        self._stop_event = stop_event

    @Slot()
    def run(self) -> None:
        try:
            scene = decode_u3d_scene(
                self._model_data,
                max_triangles=500_000,
                progress=self.progress.emit,
                cancelled=self._stop_event.is_set,
            )
        except U3DDecodeCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.decoded.emit(scene)
        finally:
            self._model_data = b""


class ThreeDViewerDialog(QDialog):
    open_external_requested = Signal()

    def __init__(
        self,
        model_data: bytes,
        page_number: int,
        model_format: str = "PRC",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Interactive 3D View - Page {page_number}")
        self.resize(980, 720)
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._decode_thread: QThread | None = None
        self._decode_worker: _U3DDecoderWorker | None = None
        self._decode_stop = threading.Event()
        self._close_after_decode = False
        self._model_format = model_format.upper()
        self.canvas = PrcCanvas(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        controls = QHBoxLayout()
        self.title = QLabel("Preparing 3D model...")
        self.title.setStyleSheet("font-weight:600;color:#172033;")
        controls.addWidget(self.title)
        controls.addStretch(1)
        outlines = QCheckBox("Outlines")
        outlines.setChecked(True)
        outlines.toggled.connect(self.canvas.set_outlines)
        wireframe = QCheckBox("Wireframe")
        wireframe.toggled.connect(self.canvas.set_wireframe)
        lighting = QCheckBox("Lighting")
        lighting.setChecked(True)
        lighting.toggled.connect(self.canvas.set_lighting)
        reset = QPushButton("Reset View")
        reset.clicked.connect(self.canvas.reset_view)
        external = QPushButton("Open in Acrobat")
        external.clicked.connect(self.open_external_requested)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        controls.addWidget(outlines)
        controls.addWidget(wireframe)
        controls.addWidget(lighting)
        controls.addWidget(reset)
        controls.addWidget(external)
        controls.addWidget(close)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        self.loading_panel = QWidget(self)
        loading_layout = QVBoxLayout(self.loading_panel)
        loading_layout.addStretch(1)
        self.loading_label = QLabel("Inspecting embedded U3D model...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet("font-size:15px;font-weight:600;color:#36445d;")
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 100)
        self.loading_progress.setValue(0)
        self.loading_progress.setMaximumWidth(560)
        loading_layout.addWidget(self.loading_label)
        loading_layout.addWidget(
            self.loading_progress, 0, Qt.AlignmentFlag.AlignHCenter
        )
        loading_layout.addStretch(1)
        layout.addWidget(self.loading_panel, 1)
        self.instructions = QLabel(
            "Left-drag: rotate   |   Shift+left-drag or right-drag: pan   |   "
            "Wheel: zoom   |   Double-click: reset"
        )
        self.instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instructions.setStyleSheet("color:#657084;")
        self.canvas.render_failed.connect(
            lambda message: self.instructions.setText(f"3D rendering failed: {message}")
        )
        layout.addWidget(self.instructions)

        if self._model_format == "PRC":
            outlines.hide()
            self.loading_panel.hide()
            self._temp_dir = tempfile.TemporaryDirectory(prefix="vf-pdf-helper-3d-")
            model_path = Path(self._temp_dir.name) / "embedded-model.prc"
            model_path.write_bytes(model_data)
            stats = self.canvas.load_prc(str(model_path))
            self.title.setText(
                f"PRC model | {stats.tessellations} tessellation(s) | "
                f"{stats.faces:,} faces | {stats.vertices:,} vertices"
            )
        elif self._model_format == "U3D":
            self.canvas.hide()
            self.instructions.setText(
                "Large U3D assemblies are decoded as a bounded interactive preview."
            )
            self._start_u3d_decode(model_data)
        else:
            raise ThreeDViewError(f"The built-in viewer does not support {self._model_format} models.")

    def _start_u3d_decode(self, model_data: bytes) -> None:
        thread = QThread(self)
        worker = _U3DDecoderWorker(model_data, self._decode_stop)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._u3d_progress)
        worker.decoded.connect(self._u3d_decoded)
        worker.failed.connect(self._u3d_failed)
        worker.cancelled.connect(self._u3d_cancelled)
        worker.decoded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._u3d_thread_finished)
        self._decode_thread = thread
        self._decode_worker = worker
        thread.start()

    @Slot(int, str)
    def _u3d_progress(self, percent: int, message: str) -> None:
        self.loading_progress.setValue(max(0, min(100, percent)))
        self.loading_label.setText(message)

    @Slot(object)
    def _u3d_decoded(self, scene: U3DScene) -> None:
        try:
            self.canvas.load_u3d(scene)
        except Exception as exc:
            self._u3d_failed(str(exc))
            return
        self.loading_panel.hide()
        self.canvas.show()
        preview_note = ""
        if scene.omitted_faces:
            preview_note = f" | preview {scene.rendered_faces:,}/{scene.source_faces:,} faces"
        self.title.setText(
            f"U3D model | {scene.resource_count:,} resources | "
            f"{scene.instance_count:,} instances{preview_note}"
            + (
                f" | {scene.proxy_instances:,} outline proxies"
                if scene.proxy_instances
                else ""
            )
        )
        self.instructions.setText(
            "Left-drag: rotate   |   Shift+left-drag or right-drag: pan   |   "
            "Wheel: zoom   |   Double-click: reset"
        )

    @Slot(str)
    def _u3d_failed(self, message: str) -> None:
        self.loading_progress.setValue(0)
        self.loading_label.setText(f"The U3D preview could not be prepared:\n{message}")
        self.title.setText("U3D model could not be decoded")

    @Slot()
    def _u3d_cancelled(self) -> None:
        self.loading_label.setText("U3D decoding cancelled")

    @Slot()
    def _u3d_thread_finished(self) -> None:
        thread = self._decode_thread
        self._decode_thread = None
        self._decode_worker = None
        if thread is not None:
            thread.deleteLater()
        if self._close_after_decode:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._decode_thread is not None and self._decode_thread.isRunning():
            self._decode_stop.set()
            self._close_after_decode = True
            self.loading_label.setText("Cancelling U3D decoding...")
            event.ignore()
            return
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None
        super().closeEvent(event)
