from __future__ import annotations

import os
from pathlib import Path

import nanoprc_py
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pdf_helper.three_d import GL_TRIANGLES, CpuMesh, PrcCanvas


def make_triangle_prc(path: Path) -> None:
    tessellation = {
        "kind": nanoprc_py.PRC_API_WRITE_TESS_KIND_COMPRESSED,
        "positions": np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            dtype=np.float64,
        ),
        "normals": np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float64),
        "tri_indices": np.asarray(((0, 1, 2),), dtype=np.uint32),
        "norm_indices": np.asarray(((0, 1, 2),), dtype=np.uint32),
        "face_tri_counts": np.asarray((1,), dtype=np.uint32),
    }
    root = {
        "name": "Triangle",
        "children": [
            {
                "name": "Part",
                "part_name": "Triangle",
                "rep_items": [
                    {
                        "kind": nanoprc_py.PRC_API_WRITE_RI_SURFACE,
                        "biased_tessellation_index": 1,
                        "is_closed": False,
                    }
                ],
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [1.0, 1.0, 0.0],
            }
        ],
    }
    context = nanoprc_py.Context()
    path.write_bytes(context.write_prc_buffer("VF PDF Helper test", root, [tessellation]))


def test_prc_geometry_is_loaded_for_interactive_viewing(tmp_path: Path) -> None:
    source = tmp_path / "triangle.prc"
    make_triangle_prc(source)
    app = QApplication.instance() or QApplication([])
    canvas = PrcCanvas()

    stats = canvas.load_prc(str(source))

    assert stats.tessellations == 1
    assert stats.faces == 1
    assert stats.primitives == 1
    assert stats.vertices == 3
    assert app is not None


def test_3d_canvas_defaults_to_unified_color_with_edge_outlines() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = PrcCanvas()

    assert canvas._unified_colors is True
    assert canvas._edge_outlines is True
    assert app is not None


def test_3d_canvas_can_switch_between_unified_and_part_colors() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = PrcCanvas()
    canvas._lighting = False
    mesh = CpuMesh(
        positions=np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            dtype=np.float32,
        ),
        normals=np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32),
        indices=np.asarray((0, 1, 2), dtype=np.uint32),
        mode=GL_TRIANGLES,
        color=(0.9, 0.2, 0.1, 0.75),
    )

    unified = canvas._mesh_colors(mesh)
    np.testing.assert_allclose(unified[0], (0.58, 0.69, 0.77, 0.75))

    canvas.set_unified_colors(False)
    part_colors = canvas._mesh_colors(mesh)
    np.testing.assert_allclose(part_colors[0], mesh.color)
    assert app is not None
