from __future__ import annotations

import os
from pathlib import Path

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRect, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from .app_info import APP_NAME, APP_VERSION, ORGANIZATION_NAME, PROJECT_URL
from .model import (
    FontChoice,
    FormField,
    PasswordRequired,
    PdfDocumentModel,
    PdfError,
    TextSpan,
    available_fonts,
)


APP_STYLE = """
QMainWindow, QWidget {
    background: #f5f7fb;
    color: #172033;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #dfe4ec;
    spacing: 4px;
    padding: 7px 10px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 9px;
}
QToolButton:hover { background: #edf3ff; color: #0d5bd7; }
QToolButton:checked { background: #dfeaff; color: #0b57c9; border-color: #b8d0ff; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #e5e9f0; }
QMenuBar::item { padding: 6px 10px; background: transparent; }
QMenuBar::item:selected { background: #edf3ff; border-radius: 5px; }
QMenu { background: white; border: 1px solid #dfe4ec; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 10px; border-radius: 5px; }
QMenu::item:selected { background: #edf3ff; color: #0b57c9; }
QSplitter::handle { background: #dfe4ec; width: 1px; }
#Sidebar, #Inspector { background: #ffffff; }
#PanelTitle { font-size: 15px; font-weight: 700; color: #111a2b; }
#Muted { color: #6d7788; }
#Badge {
    background: #e9f1ff;
    color: #0b57c9;
    border-radius: 9px;
    padding: 3px 7px;
}
QListWidget {
    background: #ffffff;
    border: none;
    outline: none;
    padding: 4px 8px;
}
QListWidget::item {
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px;
    margin: 3px 0;
}
QListWidget::item:hover { background: #f1f5fb; }
QListWidget::item:selected { background: #e5efff; border-color: #a8c8ff; color: #0b57c9; }
QPushButton {
    background: #ffffff;
    border: 1px solid #d6dce6;
    border-radius: 7px;
    padding: 7px 11px;
}
QPushButton:hover { border-color: #8eb7ff; background: #f5f8ff; color: #0b57c9; }
QPushButton:pressed { background: #e6efff; }
QPushButton:disabled { color: #aab1bd; background: #f4f5f7; border-color: #e3e6eb; }
QPushButton#Primary {
    background: #1467d9;
    border-color: #1467d9;
    color: white;
    font-weight: 600;
}
QPushButton#Primary:hover { background: #0f5fcf; border-color: #0f5fcf; color: white; }
QPushButton#Primary:disabled {
    color: #aab1bd;
    background: #f4f5f7;
    border-color: #e3e6eb;
}
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #d6dce6;
    border-radius: 7px;
    padding: 6px 8px;
    selection-background-color: #b9d2ff;
}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #5997f2;
}
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #c5ccd7; border-radius: 5px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: #c5ccd7; border-radius: 5px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar { background: #ffffff; border-top: 1px solid #dfe4ec; color: #657084; }
"""


def qimage_from_render(data: bytes, width: int, height: int, stride: int) -> QImage:
    return QImage(data, width, height, stride, QImage.Format.Format_RGB888).copy()


class PageCanvas(QLabel):
    span_clicked = Signal(object)
    point_clicked = Signal(float, float)
    inline_edit_requested = Signal(object, str)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setMouseTracking(True)
        self.setStyleSheet("background: white;")
        self._scale = 1.0
        self._spans: list[TextSpan] = []
        self._selected: TextSpan | None = None
        self._hovered: TextSpan | None = None
        self._inline_editor: QLineEdit | None = None
        self._inline_span: TextSpan | None = None
        self.mode = "browse"

    def set_page(
        self, image: QImage, scale: float, spans: list[TextSpan], selected: TextSpan | None = None
    ) -> None:
        self._close_inline_editor()
        self._scale = scale
        self._spans = spans
        self._selected = selected
        self._hovered = None
        pixmap = QPixmap.fromImage(image)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.update()

    def clear_page(self) -> None:
        self._close_inline_editor()
        self.clear()
        self.setFixedSize(1, 1)
        self._spans.clear()
        self._selected = None
        self._hovered = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "select":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif mode == "add":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hovered = None
        self.update()

    def set_selected(self, span: TextSpan | None) -> None:
        self._selected = span
        self.update()

    def _point_in_pdf(self, event: QMouseEvent) -> tuple[float, float]:
        pos = event.position()
        return pos.x() / self._scale, pos.y() / self._scale

    def _span_at(self, x: float, y: float) -> TextSpan | None:
        hits: list[tuple[float, TextSpan]] = []
        tolerance = 1.4
        for span in self._spans:
            x0, y0, x1, y1 = span.bbox
            if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
                hits.append(((x1 - x0) * (y1 - y0), span))
        return min(hits, key=lambda pair: pair[0])[1] if hits else None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.mode == "select":
            x, y = self._point_in_pdf(event)
            hovered = self._span_at(x, y)
            if hovered != self._hovered:
                self._hovered = hovered
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if hovered
                    else Qt.CursorShape.CrossCursor
                )
                self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = self._point_in_pdf(event)
            if self.mode == "select":
                span = self._span_at(x, y)
                if span:
                    self._selected = span
                    self.span_clicked.emit(span)
                    self.update()
                    return
            elif self.mode == "add":
                self.point_clicked.emit(x, y)
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.mode == "select":
            x, y = self._point_in_pdf(event)
            span = self._span_at(x, y)
            if span:
                self._selected = span
                self.span_clicked.emit(span)
                self._open_inline_editor(span)
                self.update()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _open_inline_editor(self, span: TextSpan) -> None:
        self._close_inline_editor()
        x0, y0, x1, y1 = span.bbox
        left = max(0, round(x0 * self._scale) - 4)
        top = max(0, round(y0 * self._scale) - 5)
        original_width = max(1, round((x1 - x0) * self._scale))
        height = max(30, round((y1 - y0) * self._scale) + 10)

        editor = QLineEdit(self)
        editor.setText(span.text)
        font = QFont(self.font())
        font.setPixelSize(max(12, round(span.size * self._scale)))
        editor.setFont(font)
        red, green, blue = (round(channel * 255) for channel in span.color)
        editor.setStyleSheet(
            "QLineEdit {"
            "background: rgba(255,255,255,245);"
            "border: 2px solid #1467d9;"
            "border-radius: 4px;"
            f"color: rgb({red},{green},{blue});"
            "padding: 2px 5px;"
            "selection-background-color: #b9d2ff;"
            "}"
        )
        editor.textChanged.connect(
            lambda: self._resize_inline_editor(editor, left, top, original_width, height)
        )
        editor.returnPressed.connect(lambda: self._commit_inline_editor(editor, span))
        editor.editingFinished.connect(lambda: self._commit_inline_editor(editor, span))
        editor.installEventFilter(self)
        self._inline_editor = editor
        self._inline_span = span
        self._resize_inline_editor(editor, left, top, original_width, height)
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        editor.selectAll()

    def _resize_inline_editor(
        self,
        editor: QLineEdit,
        left: int,
        top: int,
        original_width: int,
        height: int,
    ) -> None:
        desired = max(
            original_width + 18,
            editor.fontMetrics().horizontalAdvance(editor.text()) + 24,
            90,
        )
        available = max(40, self.width() - left - 6)
        editor.setGeometry(left, top, min(desired, available), height)

    def _commit_inline_editor(self, editor: QLineEdit, span: TextSpan) -> None:
        if editor is not self._inline_editor or editor.property("inlineFinished"):
            return
        editor.setProperty("inlineFinished", True)
        text = editor.text()
        self._inline_editor = None
        self._inline_span = None
        editor.hide()
        editor.deleteLater()
        self.inline_edit_requested.emit(span, text)

    def _close_inline_editor(self) -> None:
        editor = self._inline_editor
        self._inline_editor = None
        self._inline_span = None
        if editor:
            editor.setProperty("inlineFinished", True)
            editor.hide()
            editor.deleteLater()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self._inline_editor and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._close_inline_editor()
                self.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for span, color, width in (
            (self._hovered, QColor(41, 121, 255, 190), 1.2),
            (self._selected, QColor(8, 92, 220, 240), 2.0),
        ):
            if span is None:
                continue
            x0, y0, x1, y1 = span.bbox
            painter.setPen(QPen(color, width))
            fill = QColor(color)
            fill.setAlpha(28)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                x0 * self._scale,
                y0 * self._scale,
                (x1 - x0) * self._scale,
                (y1 - y0) * self._scale,
                2,
                2,
            )


class PdfViewer(QScrollArea):
    span_clicked = Signal(object)
    point_clicked = Signal(float, float)
    inline_edit_requested = Signal(object, str)
    zoom_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea { background: #dfe3ea; }")
        self.canvas.span_clicked.connect(self.span_clicked)
        self.canvas.point_clicked.connect(self.point_clicked)
        self.canvas.inline_edit_requested.connect(self.inline_edit_requested)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_requested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class FloatingTextToolbar(QFrame):
    style_changed = Signal(object, float, object, bool, bool, bool)
    interaction_started = Signal()
    interaction_finished = Signal()

    def __init__(self, fonts: tuple[FontChoice, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.fonts = fonts
        self._color = (0.0, 0.0, 0.0)
        self._setting = False
        self.setObjectName("FloatingTextToolbar")
        self.setStyleSheet(
            "QFrame#FloatingTextToolbar {"
            "background:#ffffff; border:1px solid #b8c1cf; border-radius:8px;"
            "}"
            "QComboBox {background:#ffffff; border:1px solid #d2d8e2; border-radius:5px;"
            "padding:4px 7px; min-height:22px;}"
            "QPushButton {border:1px solid #c7ced9; border-radius:5px; min-width:30px;"
            "min-height:28px; padding:0;}"
            "QPushButton:checked {background:#dfeaff;color:#0b57c9;border-color:#8eb7ff;}"
        )
        self.setAutoFillBackground(True)
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(5)
        self.font_combo = QComboBox()
        self.font_combo.setFixedWidth(132)
        for font in fonts:
            self.font_combo.addItem(font.label)
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.size_combo.setFixedWidth(67)
        for size in (6, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 64, 72):
            self.size_combo.addItem(str(size))
        self.size_combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.color_button = QPushButton()
        self.color_button.setToolTip("文字颜色")
        self.bold_button = QPushButton("B")
        self.bold_button.setToolTip("加粗")
        self.bold_button.setCheckable(True)
        self.bold_button.setStyleSheet("font-weight:700;")
        self.italic_button = QPushButton("I")
        self.italic_button.setToolTip("斜体")
        self.italic_button.setCheckable(True)
        self.italic_button.setStyleSheet("font-style:italic;")
        self.underline_button = QPushButton("U")
        self.underline_button.setToolTip("下划线")
        self.underline_button.setCheckable(True)
        self.underline_button.setStyleSheet("text-decoration:underline;")
        layout.addWidget(self.font_combo)
        layout.addWidget(self.size_combo)
        layout.addWidget(self.bold_button)
        layout.addWidget(self.italic_button)
        layout.addWidget(self.underline_button)
        layout.addWidget(self.color_button)

        self.font_combo.activated.connect(self._emit_style)
        self.size_combo.activated.connect(self._emit_style)
        self.size_combo.lineEdit().editingFinished.connect(self._emit_style)
        self.color_button.clicked.connect(self._choose_color)
        self.bold_button.toggled.connect(self._emit_style)
        self.italic_button.toggled.connect(self._emit_style)
        self.underline_button.toggled.connect(self._emit_style)
        self.set_style(fonts[0], 11, self._color, False, False, False)
        self.hide()

    def current_style(
        self,
    ) -> tuple[FontChoice, float, tuple[float, float, float], bool, bool, bool]:
        index = max(0, min(self.font_combo.currentIndex(), len(self.fonts) - 1))
        try:
            size = float(self.size_combo.currentText().strip())
        except ValueError:
            size = 11.0
        size = max(4.0, min(200.0, size))
        return (
            self.fonts[index],
            size,
            self._color,
            self.bold_button.isChecked(),
            self.italic_button.isChecked(),
            self.underline_button.isChecked(),
        )

    def set_style(
        self,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        self._setting = True
        try:
            index = next(
                (
                    i
                    for i, choice in enumerate(self.fonts)
                    if choice.label == font.label or choice.pdf_name == font.pdf_name
                ),
                0,
            )
            self.font_combo.setCurrentIndex(index)
            self.size_combo.setEditText(f"{size:.1f}".rstrip("0").rstrip("."))
            self._color = color
            self.bold_button.setChecked(bold)
            self.italic_button.setChecked(italic)
            self.underline_button.setChecked(underline)
            red, green, blue = (round(channel * 255) for channel in color)
            self.color_button.setStyleSheet(
                "QPushButton {"
                f"background:rgb({red},{green},{blue});"
                "border:1px solid #8e97a5;border-radius:5px;min-width:30px;min-height:28px;"
                "}"
            )
        finally:
            self._setting = False

    def _emit_style(self, *_args) -> None:
        if self._setting:
            return
        font, size, color, bold, italic, underline = self.current_style()
        self.size_combo.setEditText(f"{size:.1f}".rstrip("0").rstrip("."))
        self.style_changed.emit(font, size, color, bold, italic, underline)

    def _choose_color(self) -> None:
        self.interaction_started.emit()
        initial = QColor.fromRgbF(*self._color)
        color = QColorDialog.getColor(initial, self, "选择文字颜色")
        if color.isValid():
            self._color = (color.redF(), color.greenF(), color.blueF())
            font, size, _, bold, italic, underline = self.current_style()
            self.set_style(font, size, self._color, bold, italic, underline)
            self.style_changed.emit(font, size, self._color, bold, italic, underline)
        self.interaction_finished.emit()


class FloatingInkToolbar(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._color = (0.03, 0.16, 0.38)
        self.setObjectName("FloatingInkToolbar")
        self.setStyleSheet(
            "QFrame#FloatingInkToolbar {background:#ffffff;border:1px solid #b8c1cf;"
            "border-radius:8px;}"
            "QComboBox {background:#ffffff;border:1px solid #d2d8e2;border-radius:5px;"
            "padding:4px 7px;min-height:22px;}"
            "QPushButton {border:1px solid #c7ced9;border-radius:5px;min-width:34px;"
            "min-height:28px;padding:0 7px;}"
        )
        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(5)
        label = QLabel("画笔")
        label.setStyleSheet("font-weight:700;")
        self.width_combo = QComboBox()
        self.width_combo.setToolTip("画笔粗细")
        self.width_combo.setFixedWidth(72)
        for width in (1, 1.5, 2, 3, 5, 8):
            self.width_combo.addItem(f"{width:g} pt", float(width))
        self.width_combo.setCurrentIndex(2)
        self.color_button = QPushButton("颜色")
        self.color_button.setToolTip("签名颜色")
        self.color_button.clicked.connect(self._choose_color)
        layout.addWidget(label)
        layout.addWidget(self.width_combo)
        layout.addWidget(self.color_button)
        self._update_color_button()
        self.hide()

    def current_style(self) -> tuple[tuple[float, float, float], float]:
        return self._color, float(self.width_combo.currentData() or 2.0)

    def _choose_color(self) -> None:
        initial = QColor.fromRgbF(*self._color)
        color = QColorDialog.getColor(initial, self, "选择签名颜色")
        if color.isValid():
            self._color = (color.redF(), color.greenF(), color.blueF())
            self._update_color_button()

    def _update_color_button(self) -> None:
        red, green, blue = (round(channel * 255) for channel in self._color)
        foreground = "white" if red + green + blue < 420 else "#172033"
        self.color_button.setStyleSheet(
            f"background:rgb({red},{green},{blue});color:{foreground};font-weight:600;"
        )


class FormTextEdit(QPlainTextEdit):
    commit_requested = Signal(str)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        text = self.toPlainText()
        super().focusOutEvent(event)
        QTimer.singleShot(0, lambda value=text: self.commit_requested.emit(value))


class DirectPageCanvas(QLabel):
    span_clicked = Signal(object)
    delete_text_requested = Signal(object)
    style_edit_requested = Signal(object, object, float, object, bool, bool, bool)
    inline_edit_requested = Signal(object, str, object, float, object, bool, bool, bool, bool)
    new_text_requested = Signal(float, float, str, object, float, object, bool, bool, bool)
    move_text_requested = Signal(object, float, float, object, float, object, bool, bool, bool)
    form_field_edited = Signal(object, object)
    ink_stroke_requested = Signal(object, object, float)

    def __init__(self, fonts: tuple[FontChoice, ...]) -> None:
        super().__init__()
        self.fonts = fonts
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background: white;")
        self._scale = 1.0
        self._spans: list[TextSpan] = []
        self._form_fields: list[FormField] = []
        self._form_controls: list[QWidget] = []
        self._selected: TextSpan | None = None
        self._hovered: TextSpan | None = None
        self._inline_editor: QLineEdit | None = None
        self._editor_span: TextSpan | None = None
        self._editor_point: tuple[float, float] | None = None
        self._editor_style_dirty = False
        self._toolbar_interacting = False
        self._drag_span: TextSpan | None = None
        self._drag_press_position: tuple[float, float] | None = None
        self._drag_offset = (0.0, 0.0)
        self._dragging = False
        self._ink_points: list[tuple[float, float]] = []
        self.mode = "browse"

        self.floating_toolbar = FloatingTextToolbar(fonts, self)
        self.floating_toolbar.style_changed.connect(self._toolbar_style_changed)
        self.floating_toolbar.interaction_started.connect(
            lambda: setattr(self, "_toolbar_interacting", True)
        )
        self.floating_toolbar.interaction_finished.connect(self._toolbar_interaction_finished)
        self.ink_toolbar = FloatingInkToolbar(self)

    def set_page(
        self,
        image: QImage,
        scale: float,
        spans: list[TextSpan],
        form_fields: list[FormField],
        selected: TextSpan | None = None,
    ) -> None:
        self._close_inline_editor()
        self._reset_drag()
        self._clear_form_controls()
        self._ink_points.clear()
        self._scale = scale
        self._spans = spans
        self._form_fields = form_fields
        self._selected = selected if selected in spans else None
        self._hovered = None
        pixmap = QPixmap.fromImage(image)
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        if self._selected and self.mode == "select":
            self._show_toolbar_for_span(self._selected)
        else:
            self.floating_toolbar.hide()
        if self.mode == "form":
            self._show_form_controls()
        elif self.mode == "signature":
            self._show_ink_toolbar()
        else:
            self.ink_toolbar.hide()
        self.update()

    def clear_page(self) -> None:
        self._close_inline_editor()
        self._reset_drag()
        self._clear_form_controls()
        self._ink_points.clear()
        self.clear()
        self.setFixedSize(1, 1)
        self._spans.clear()
        self._form_fields.clear()
        self._selected = None
        self._hovered = None
        self.floating_toolbar.hide()
        self.ink_toolbar.hide()

    def set_mode(self, mode: str) -> None:
        if self._inline_editor:
            self._commit_inline_editor()
        self._reset_drag()
        self._clear_form_controls()
        self._ink_points.clear()
        self.mode = mode
        self._hovered = None
        if mode != "select":
            self._selected = None
            self.floating_toolbar.hide()
        if mode == "select":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "add":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif mode == "form":
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._show_form_controls()
        elif mode == "signature":
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._show_ink_toolbar()
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if mode != "signature":
            self.ink_toolbar.hide()
        self.update()

    def select_span(
        self,
        span: TextSpan | None,
        style: tuple[
            FontChoice,
            float,
            tuple[float, float, float],
            bool,
            bool,
            bool,
        ]
        | None = None,
    ) -> None:
        self._selected = span
        if span and self.mode == "select":
            self._show_toolbar_for_span(span, style)
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        else:
            self.floating_toolbar.hide()
        self.update()

    def _style_for_span(
        self, span: TextSpan
    ) -> tuple[FontChoice, float, tuple[float, float, float], bool, bool, bool]:
        is_bold = bool(span.flags & (1 << 4))
        is_italic = bool(span.flags & (1 << 1))
        is_serif = bool(span.flags & (1 << 2))
        is_mono = bool(span.flags & (1 << 3))
        label = (
            "Courier"
            if is_mono
            else "Times Roman"
            if is_serif
            else "Helvetica"
        )
        font = next((choice for choice in self.fonts if choice.label == label), self.fonts[0])
        return font, span.size, span.color, is_bold, is_italic, span.underline

    def _show_toolbar_for_span(
        self,
        span: TextSpan,
        style: tuple[
            FontChoice,
            float,
            tuple[float, float, float],
            bool,
            bool,
            bool,
        ]
        | None = None,
    ) -> None:
        font, size, color, bold, italic, underline = style or self._style_for_span(span)
        self.floating_toolbar.set_style(font, size, color, bold, italic, underline)
        x0, y0, x1, y1 = span.bbox
        target = QRect(
            round(x0 * self._scale),
            round(y0 * self._scale),
            max(1, round((x1 - x0) * self._scale)),
            max(1, round((y1 - y0) * self._scale)),
        )
        self._position_toolbar(target)

    def _position_toolbar(self, target: QRect) -> None:
        toolbar = self.floating_toolbar
        toolbar.adjustSize()
        width = toolbar.sizeHint().width()
        height = toolbar.height()
        max_left = max(5, self.width() - width - 5)
        max_top = max(5, self.height() - height - 5)

        def bounded(left: int, top: int) -> QRect:
            return QRect(
                max(5, min(left, max_left)),
                max(5, min(top, max_top)),
                width,
                height,
            )

        candidates = (
            bounded(target.left(), target.top() - height - 8),
            bounded(target.right() - width, target.top() - height - 8),
            bounded(target.left() - width - 8, target.center().y() - height // 2),
            bounded(target.right() + 8, target.center().y() - height // 2),
            bounded(target.left(), target.bottom() + 8),
            bounded(target.right() - width, target.bottom() + 8),
        )
        avoid = [target]
        for span in self._spans:
            x0, y0, x1, y1 = span.bbox
            avoid.append(
                QRect(
                    round(x0 * self._scale),
                    round(y0 * self._scale),
                    max(1, round((x1 - x0) * self._scale)),
                    max(1, round((y1 - y0) * self._scale)),
                )
            )

        def overlap_score(candidate: QRect) -> int:
            return sum(
                intersection.width() * intersection.height()
                for rect in avoid
                if not (intersection := candidate.intersected(rect)).isEmpty()
            )

        geometry = min(candidates, key=overlap_score)
        toolbar.setGeometry(geometry)
        toolbar.show()
        toolbar.raise_()

    def _clear_form_controls(self) -> None:
        controls = self._form_controls
        self._form_controls = []
        for control in controls:
            control.hide()
            control.deleteLater()

    def _form_geometry(self, field: FormField) -> QRect:
        x0, y0, x1, y1 = field.rect
        return QRect(
            round(x0 * self._scale),
            round(y0 * self._scale),
            max(12, round((x1 - x0) * self._scale)),
            max(12, round((y1 - y0) * self._scale)),
        )

    def _show_form_controls(self) -> None:
        self._clear_form_controls()
        for field in self._form_fields:
            control: QWidget | None = None
            geometry = self._form_geometry(field)
            if field.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT:
                if field.multiline:
                    multiline = FormTextEdit(self)
                    multiline.setPlainText(field.value)
                    multiline.setPlaceholderText(field.label)
                    multiline.setToolTip(field.label + "（多行字段）")
                    multiline.setStyleSheet(
                        "QPlainTextEdit {background:#ffffff;"
                        "border:1px solid #4f91ed;border-radius:2px;padding:2px 4px;}"
                        "QPlainTextEdit:focus {border:2px solid #1467d9;background:white;}"
                    )
                    multiline.commit_requested.connect(
                        lambda value, f=field: self.form_field_edited.emit(f, value)
                    )
                    control = multiline
                else:
                    editor = QLineEdit(self)
                    editor.setText(field.value)
                    editor.setPlaceholderText(field.label)
                    editor_font = QFont(editor.font())
                    editor_font.setPixelSize(
                        max(11, min(36, round(geometry.height() * 0.52)))
                    )
                    editor.setFont(editor_font)
                    if field.password:
                        editor.setEchoMode(QLineEdit.EchoMode.Password)
                    if field.max_length:
                        editor.setMaxLength(field.max_length)
                    editor.setToolTip(field.label)
                    editor.setStyleSheet(
                        "QLineEdit {background:#ffffff;"
                        "border:1px solid #4f91ed;border-radius:2px;padding:1px 4px;}"
                        "QLineEdit:focus {border:2px solid #1467d9;background:white;}"
                    )
                    editor.editingFinished.connect(
                        lambda f=field, widget=editor: self.form_field_edited.emit(
                            f, widget.text()
                        )
                    )
                    control = editor
            elif field.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                checkbox = QCheckBox(self)
                checkbox.setChecked(field.value not in ("", "Off", "False", "0"))
                checkbox.setToolTip(field.label)
                checkbox.setStyleSheet(
                    "QCheckBox {background:#ffffff;padding:1px;}"
                    "QCheckBox::indicator {width:16px;height:16px;}"
                )
                checkbox.clicked.connect(
                    lambda checked, f=field: self.form_field_edited.emit(
                        f, (f.on_value or "Yes") if checked else "Off"
                    )
                )
                control = checkbox
            elif field.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                radio = QRadioButton(self)
                radio.setChecked(field.value == (field.on_value or "Yes"))
                radio.setToolTip(field.label)
                radio.setStyleSheet(
                    "QRadioButton {background:#ffffff;padding:1px;}"
                    "QRadioButton::indicator {width:16px;height:16px;}"
                )
                radio.clicked.connect(
                    lambda checked, f=field: checked
                    and self.form_field_edited.emit(f, f.on_value or "Yes")
                )
                control = radio
            elif field.field_type in (
                pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                pymupdf.PDF_WIDGET_TYPE_LISTBOX,
            ):
                combo = QComboBox(self)
                combo.addItems(field.choices)
                if field.value and combo.findText(field.value) < 0:
                    combo.addItem(field.value)
                combo.setCurrentText(field.value)
                combo.setToolTip(field.label)
                combo_font = QFont(combo.font())
                combo_font.setPixelSize(
                    max(11, min(32, round(geometry.height() * 0.46)))
                )
                combo.setFont(combo_font)
                combo.setStyleSheet(
                    "QComboBox {background:#ffffff;border:1px solid #4f91ed;"
                    "border-radius:2px;padding:1px 4px;}"
                )
                combo.activated.connect(
                    lambda _index, f=field, widget=combo: self.form_field_edited.emit(
                        f, widget.currentText()
                    )
                )
                control = combo
            elif field.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                signature_label = QLabel("数字签名字段", self)
                signature_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                signature_label.setToolTip("可使用工具栏中的“签名画笔”绘制手写签名")
                signature_label.setStyleSheet(
                    "background:rgba(232,240,255,225);border:1px dashed #4f91ed;"
                    "border-radius:2px;color:#0b57c9;font-size:11px;"
                )
                control = signature_label
            if control is None:
                continue
            control.setGeometry(geometry)
            control.setEnabled(not field.read_only)
            control.show()
            control.raise_()
            self._form_controls.append(control)

    def _show_ink_toolbar(self) -> None:
        toolbar = self.ink_toolbar
        toolbar.adjustSize()
        toolbar.move(max(8, self.width() - toolbar.sizeHint().width() - 8), 8)
        toolbar.show()
        toolbar.raise_()

    def _point_in_pdf(self, event: QMouseEvent) -> tuple[float, float]:
        pos = event.position()
        return pos.x() / self._scale, pos.y() / self._scale

    def _span_at(self, x: float, y: float) -> TextSpan | None:
        hits: list[tuple[float, TextSpan]] = []
        tolerance = 1.4
        for span in self._spans:
            x0, y0, x1, y1 = span.bbox
            if x0 - tolerance <= x <= x1 + tolerance and y0 - tolerance <= y <= y1 + tolerance:
                hits.append(((x1 - x0) * (y1 - y0), span))
        return min(hits, key=lambda pair: pair[0])[1] if hits else None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self.mode == "signature"
            and self._ink_points
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            point = self._point_in_pdf(event)
            last = self._ink_points[-1]
            if (point[0] - last[0]) ** 2 + (point[1] - last[1]) ** 2 >= 0.12:
                self._ink_points.append(point)
                self.update()
            event.accept()
            return
        if self.mode == "select" and not self._inline_editor:
            if (
                self._drag_span
                and self._drag_press_position
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                pos = event.position()
                delta_x = pos.x() - self._drag_press_position[0]
                delta_y = pos.y() - self._drag_press_position[1]
                if self._dragging or (
                    delta_x * delta_x + delta_y * delta_y
                    >= QApplication.startDragDistance() ** 2
                ):
                    self._dragging = True
                    self.floating_toolbar.hide()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    span = self._drag_span
                    x0, y0, x1, y1 = span.bbox
                    page_width = self.width() / self._scale
                    page_height = self.height() / self._scale
                    pdf_dx = delta_x / self._scale
                    pdf_dy = delta_y / self._scale
                    pdf_dx = max(-x0, min(pdf_dx, page_width - x1))
                    pdf_dy = max(-y0, min(pdf_dy, page_height - y1))
                    self._drag_offset = (pdf_dx, pdf_dy)
                    self.update()
                    event.accept()
                    return
            x, y = self._point_in_pdf(event)
            hovered = self._span_at(x, y)
            if hovered != self._hovered:
                self._hovered = hovered
                self.setCursor(
                    Qt.CursorShape.OpenHandCursor if hovered else Qt.CursorShape.CrossCursor
                )
                self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hovered = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._inline_editor:
            self._commit_inline_editor()
            event.accept()
            return
        x, y = self._point_in_pdf(event)
        if self.mode == "signature":
            self._ink_points = [(x, y)]
            self.ink_toolbar.raise_()
            self.update()
        elif self.mode == "select":
            span = self._span_at(x, y)
            self.select_span(span)
            if span:
                pos = event.position()
                self._drag_span = span
                self._drag_press_position = (pos.x(), pos.y())
                self._drag_offset = (0.0, 0.0)
                self._dragging = False
                self.span_clicked.emit(span)
            else:
                self._reset_drag()
        elif self.mode == "add":
            self._open_new_editor((x, y))
        else:
            self.select_span(None)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.mode == "signature":
            if self._ink_points:
                points = list(self._ink_points)
                self._ink_points.clear()
                color, width = self.ink_toolbar.current_style()
                self.ink_stroke_requested.emit(points, color, width)
                self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_span:
            span = self._drag_span
            dx, dy = self._drag_offset
            moved = self._dragging
            font, size, color, bold, italic, underline = self.floating_toolbar.current_style()
            self._reset_drag()
            if moved:
                self.move_text_requested.emit(
                    span,
                    span.origin[0] + dx,
                    span.origin[1] + dy,
                    font,
                    size,
                    color,
                    bold,
                    italic,
                    underline,
                )
            elif span == self._selected:
                self._show_toolbar_for_span(
                    span, (font, size, color, bold, italic, underline)
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.mode == "select":
            x, y = self._point_in_pdf(event)
            span = self._span_at(x, y)
            if span:
                self._reset_drag()
                self._selected = span
                self.span_clicked.emit(span)
                self._open_existing_editor(span)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if self._selected and not self._inline_editor and event.key() in (
            Qt.Key.Key_Delete,
            Qt.Key.Key_Backspace,
        ):
            span = self._selected
            self.select_span(None)
            self.delete_text_requested.emit(span)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._inline_editor:
                self._close_inline_editor()
            elif self._ink_points:
                self._ink_points.clear()
                self.update()
            else:
                self.select_span(None)
            event.accept()
            return
        super().keyPressEvent(event)

    def _reset_drag(self) -> None:
        self._drag_span = None
        self._drag_press_position = None
        self._drag_offset = (0.0, 0.0)
        self._dragging = False
        if self.mode == "select":
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if self._hovered else Qt.CursorShape.CrossCursor
            )

    def _open_existing_editor(self, span: TextSpan) -> None:
        self._close_inline_editor()
        self._selected = span
        font, size, color, bold, italic, underline = self._style_for_span(span)
        self.floating_toolbar.set_style(font, size, color, bold, italic, underline)
        x0, y0, x1, y1 = span.bbox
        left = max(0, round(x0 * self._scale) - 4)
        top = max(0, round(y0 * self._scale) - 5)
        width = max(90, round((x1 - x0) * self._scale) + 18)
        height = max(30, round((y1 - y0) * self._scale) + 10)
        self._editor_span = span
        self._editor_point = None
        self._create_editor(span.text, left, top, width, height)

    def _open_new_editor(self, point: tuple[float, float]) -> None:
        self._close_inline_editor()
        self._selected = None
        font, size, color, bold, italic, underline = self.floating_toolbar.current_style()
        self.floating_toolbar.set_style(font, size, color, bold, italic, underline)
        x, y = point
        left = max(0, round(x * self._scale) - 4)
        top = max(0, round((y - size) * self._scale) - 5)
        self._editor_span = None
        self._editor_point = point
        self._create_editor("", left, top, 130, max(31, round(size * self._scale) + 12))
        assert self._inline_editor is not None
        self._inline_editor.setPlaceholderText("输入文字")

    def _create_editor(self, text: str, left: int, top: int, width: int, height: int) -> None:
        editor = QLineEdit(self)
        editor.setText(text)
        editor.setProperty("anchorLeft", left)
        editor.setProperty("anchorTop", top)
        editor.setProperty("baseWidth", width)
        editor.setProperty("baseHeight", height)
        editor.installEventFilter(self)
        editor.textChanged.connect(self._resize_inline_editor)
        editor.returnPressed.connect(self._commit_inline_editor)
        self._inline_editor = editor
        self._editor_style_dirty = False
        self._apply_editor_style()
        self._resize_inline_editor()
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        editor.selectAll()

    def _qt_font_for_choice(
        self, choice: FontChoice, pixel_size: int, bold: bool = False, italic: bool = False
    ) -> QFont:
        family = choice.label
        if family.startswith("Helvetica") or family.startswith("Arial"):
            family = "Arial"
        elif family.startswith("Times"):
            family = "Times New Roman"
        elif family.startswith("Courier"):
            family = "Courier New"
        font = QFont(family)
        font.setPixelSize(max(12, pixel_size))
        font.setBold(bold or "Bold" in choice.label)
        font.setItalic(italic or "Italic" in choice.label or "Oblique" in choice.label)
        return font

    def _apply_editor_style(self) -> None:
        editor = self._inline_editor
        if not editor:
            return
        font_choice, size, color, bold, italic, underline = (
            self.floating_toolbar.current_style()
        )
        editor_font = self._qt_font_for_choice(
            font_choice, round(size * self._scale), bold, italic
        )
        editor_font.setUnderline(underline)
        editor.setFont(editor_font)
        red, green, blue = (round(channel * 255) for channel in color)
        editor.setStyleSheet(
            "QLineEdit {background:rgba(255,255,255,246);border:2px solid #1467d9;"
            "border-radius:4px;padding:2px 5px;"
            f"color:rgb({red},{green},{blue});selection-background-color:#b9d2ff;}}"
        )

    def _resize_inline_editor(self) -> None:
        editor = self._inline_editor
        if not editor:
            return
        left = int(editor.property("anchorLeft"))
        top = int(editor.property("anchorTop"))
        base_width = int(editor.property("baseWidth"))
        height = int(editor.property("baseHeight"))
        desired = max(base_width, editor.fontMetrics().horizontalAdvance(editor.text()) + 28)
        width = min(desired, max(50, self.width() - left - 6))
        editor.setGeometry(left, top, width, height)
        self._position_toolbar(editor.geometry())
        editor.raise_()

    def _toolbar_style_changed(
        self,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool,
        italic: bool,
        underline: bool,
    ) -> None:
        if self._inline_editor:
            self._editor_style_dirty = True
            self._apply_editor_style()
            self._resize_inline_editor()
            QTimer.singleShot(0, lambda: self._inline_editor and self._inline_editor.setFocus())
        elif self._selected:
            self.style_edit_requested.emit(
                self._selected, font, size, color, bold, italic, underline
            )

    def _toolbar_interaction_finished(self) -> None:
        self._toolbar_interacting = False
        if self._inline_editor:
            QTimer.singleShot(0, lambda: self._inline_editor and self._inline_editor.setFocus())

    def _commit_if_focus_left(self) -> None:
        if not self._inline_editor or self._toolbar_interacting:
            return
        focused = QApplication.focusWidget()
        if focused is self.floating_toolbar or (
            focused is not None and self.floating_toolbar.isAncestorOf(focused)
        ):
            return
        self._commit_inline_editor()

    def _commit_inline_editor(self) -> None:
        editor = self._inline_editor
        if not editor:
            return
        text = editor.text()
        span = self._editor_span
        point = self._editor_point
        dirty = self._editor_style_dirty
        font, size, color, bold, italic, underline = self.floating_toolbar.current_style()
        self._close_inline_editor()
        if span is not None:
            self.inline_edit_requested.emit(
                span, text, font, size, color, bold, italic, underline, dirty
            )
        elif point is not None and text:
            self.new_text_requested.emit(
                point[0], point[1], text, font, size, color, bold, italic, underline
            )

    def _close_inline_editor(self) -> None:
        editor = self._inline_editor
        self._inline_editor = None
        self._editor_span = None
        self._editor_point = None
        self._editor_style_dirty = False
        if editor:
            editor.removeEventFilter(self)
            editor.hide()
            editor.deleteLater()
        self.floating_toolbar.hide()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self._inline_editor:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._close_inline_editor()
                self.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self._commit_if_focus_left)
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for span, color, width in (
            (self._hovered, QColor(41, 121, 255, 190), 1.2),
            (self._selected, QColor(8, 92, 220, 240), 2.0),
        ):
            if span is None:
                continue
            x0, y0, x1, y1 = span.bbox
            painter.setPen(QPen(color, width))
            fill = QColor(color)
            fill.setAlpha(28)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                x0 * self._scale,
                y0 * self._scale,
                (x1 - x0) * self._scale,
                (y1 - y0) * self._scale,
                2,
                2,
            )
        if self._dragging and self._drag_span:
            span = self._drag_span
            dx, dy = self._drag_offset
            x0, y0, x1, y1 = span.bbox
            painter.save()
            painter.setPen(QPen(QColor(20, 103, 217, 230), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.drawRoundedRect(
                (x0 + dx) * self._scale,
                (y0 + dy) * self._scale,
                (x1 - x0) * self._scale,
                (y1 - y0) * self._scale,
                2,
                2,
            )
            font, size, color, bold, italic, underline = (
                self.floating_toolbar.current_style()
            )
            preview_font = self._qt_font_for_choice(
                font, round(size * self._scale), bold, italic
            )
            preview_font.setUnderline(underline)
            painter.setFont(preview_font)
            red, green, blue = (round(channel * 255) for channel in color)
            painter.setPen(QColor(red, green, blue, 210))
            painter.drawText(
                QPointF(
                    (span.origin[0] + dx) * self._scale,
                    (span.origin[1] + dy) * self._scale,
                ),
                span.text,
            )
            painter.restore()
        if self._ink_points:
            color, width = self.ink_toolbar.current_style()
            red, green, blue = (round(channel * 255) for channel in color)
            pen = QPen(QColor(red, green, blue), max(1.0, width * self._scale))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            points = QPolygonF(
                [QPointF(x * self._scale, y * self._scale) for x, y in self._ink_points]
            )
            if len(points) == 1:
                painter.drawPoint(points[0])
            else:
                painter.drawPolyline(points)


class DirectPdfViewer(QScrollArea):
    span_clicked = Signal(object)
    delete_text_requested = Signal(object)
    style_edit_requested = Signal(object, object, float, object, bool, bool, bool)
    inline_edit_requested = Signal(object, str, object, float, object, bool, bool, bool, bool)
    new_text_requested = Signal(float, float, str, object, float, object, bool, bool, bool)
    move_text_requested = Signal(object, float, float, object, float, object, bool, bool, bool)
    form_field_edited = Signal(object, object)
    ink_stroke_requested = Signal(object, object, float)
    zoom_requested = Signal(int)

    def __init__(self, fonts: tuple[FontChoice, ...]) -> None:
        super().__init__()
        self.canvas = DirectPageCanvas(fonts)
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea { background: #dfe3ea; }")
        self.canvas.span_clicked.connect(self.span_clicked)
        self.canvas.delete_text_requested.connect(self.delete_text_requested)
        self.canvas.style_edit_requested.connect(self.style_edit_requested)
        self.canvas.inline_edit_requested.connect(self.inline_edit_requested)
        self.canvas.new_text_requested.connect(self.new_text_requested)
        self.canvas.move_text_requested.connect(self.move_text_requested)
        self.canvas.form_field_edited.connect(self.form_field_edited)
        self.canvas.ink_stroke_requested.connect(self.ink_stroke_requested)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_requested.emit(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class ThumbnailList(QListWidget):
    order_changed = Signal(list)

    PAGE_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self) -> None:
        super().__init__()
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setIconSize(QSize(118, 148))
        self.setSpacing(2)
        self.setUniformItemSizes(False)
        self._model: PdfDocumentModel | None = None
        self._generation = 0

    def rebuild(self, model: PdfDocumentModel, current_row: int = 0) -> None:
        self._generation += 1
        generation = self._generation
        self._model = model
        self.clear()
        placeholder = QPixmap(118, 148)
        placeholder.fill(QColor("#edf0f4"))
        for index in range(model.page_count):
            item = QListWidgetItem(QIcon(placeholder), f"  第 {index + 1} 页")
            item.setData(self.PAGE_ROLE, index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setSizeHint(QSize(150, 184))
            self.addItem(item)
        if model.page_count:
            self.setCurrentRow(max(0, min(current_row, model.page_count - 1)))
        self._render_next_thumbnail(0, generation)

    def _render_next_thumbnail(self, index: int, generation: int) -> None:
        if generation != self._generation or not self._model or index >= self.count():
            return
        try:
            data, width, height, stride = self._model.render_thumbnail(index)
            image = qimage_from_render(data, width, height, stride)
            item = self.item(index)
            if item:
                item.setIcon(QIcon(QPixmap.fromImage(image)))
        except Exception:
            pass
        QTimer.singleShot(0, lambda: self._render_next_thumbnail(index + 1, generation))

    def dropEvent(self, event: QDropEvent) -> None:
        super().dropEvent(event)
        order = [int(self.item(row).data(self.PAGE_ROLE)) for row in range(self.count())]
        self.order_changed.emit(order)


class InsertPdfDialog(QDialog):
    def __init__(self, file_name: str, source_pages: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("插入 PDF")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        title = QLabel("选择要插入的页面")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        name = QLabel(Path(file_name).name)
        name.setObjectName("Muted")
        name.setWordWrap(True)
        root.addWidget(name)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.from_page = QSpinBox()
        self.from_page.setRange(1, source_pages)
        self.from_page.setValue(1)
        self.to_page = QSpinBox()
        self.to_page.setRange(1, source_pages)
        self.to_page.setValue(source_pages)
        self.position = QComboBox()
        self.position.addItem("当前页之后", "after")
        self.position.addItem("当前页之前", "before")
        self.position.addItem("文档末尾", "end")
        form.addRow("起始页", self.from_page)
        form.addRow("结束页", self.to_page)
        form.addRow("插入位置", self.position)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("插入")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        if self.from_page.value() > self.to_page.value():
            QMessageBox.warning(self, "页码范围", "起始页不能大于结束页。")
            return
        self.accept()


class TextInspector(QWidget):
    replace_requested = Signal()
    delete_requested = Signal()
    add_requested = Signal()
    choose_color_requested = Signal()

    def __init__(self, fonts: tuple[FontChoice, ...]) -> None:
        super().__init__()
        self.setObjectName("Inspector")
        self.setMinimumWidth(270)
        self.setMaximumWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        heading_row = QHBoxLayout()
        heading = QLabel("文字编辑")
        heading.setObjectName("PanelTitle")
        self.layer_badge = QLabel("未打开")
        self.layer_badge.setObjectName("Badge")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.layer_badge)
        root.addLayout(heading_row)

        self.selection_label = QLabel("切换到“选择文字”后，可拖动文字或双击直接修改。")
        self.selection_label.setObjectName("Muted")
        self.selection_label.setWordWrap(True)
        root.addWidget(self.selection_label)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("可选：在这里输入长文本，或要新增的文字…")
        self.editor.setMinimumHeight(130)
        root.addWidget(self.editor)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.font_combo = QComboBox()
        for font in fonts:
            self.font_combo.addItem(font.label)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(4, 200)
        self.font_size.setDecimals(1)
        self.font_size.setValue(11)
        self.font_size.setSuffix(" pt")
        self.color_button = QPushButton("  ")
        self.color_button.setToolTip("选择文字颜色")
        self.color_button.setFixedHeight(31)
        self.color_button.clicked.connect(self.choose_color_requested)
        form.addRow("字体", self.font_combo)
        form.addRow("字号", self.font_size)
        form.addRow("颜色", self.color_button)
        root.addLayout(form)

        self.replace_button = QPushButton("应用修改")
        self.replace_button.setObjectName("Primary")
        self.replace_button.clicked.connect(self.replace_requested)
        self.delete_button = QPushButton("删除选中文字")
        self.delete_button.clicked.connect(self.delete_requested)
        self.add_button = QPushButton("添加到页面")
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self.add_requested)
        root.addWidget(self.replace_button)
        root.addWidget(self.delete_button)
        root.addWidget(self.add_button)

        tip = QLabel(
            "提示：文字替换会移除选中区域的原文字形，再写入新文字；不会栅格化整页。"
        )
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addStretch(1)
        self.set_state("none")

    def set_state(self, state: str) -> None:
        has_selection = state == "selection"
        has_point = state == "point"
        self.replace_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.add_button.setEnabled(has_point)
        self.editor.setEnabled(state != "none")
        self.font_combo.setEnabled(state != "none")
        self.font_size.setEnabled(state != "none")
        self.color_button.setEnabled(state != "none")


class MainWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.model = PdfDocumentModel()
        self.current_page = 0
        self.zoom = 1.35
        self.fit_width = True
        self.current_span: TextSpan | None = None
        self.fonts = available_fonts()
        self._initial_path = initial_path

        self.setWindowTitle(APP_NAME)
        self.resize(1320, 840)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_actions()
        self._build_menus_and_toolbar()
        self._update_actions()
        self._show_empty_state()

        if initial_path:
            QTimer.singleShot(50, lambda: self.open_path(initial_path))

    def _build_ui(self) -> None:
        self.page_list = ThumbnailList()
        self.page_list.currentRowChanged.connect(self._page_changed)
        self.page_list.itemSelectionChanged.connect(self._update_actions)
        self.page_list.order_changed.connect(self._pages_reordered)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(176)
        sidebar.setMaximumWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 14, 10, 10)
        sidebar_layout.setSpacing(8)
        header = QHBoxLayout()
        label = QLabel("页面")
        label.setObjectName("PanelTitle")
        self.page_badge = QLabel("0")
        self.page_badge.setObjectName("Badge")
        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(self.page_badge)
        sidebar_layout.addLayout(header)
        sidebar_layout.addWidget(self.page_list, 1)
        hint = QLabel("拖拽缩略图可调整顺序\n按住 Ctrl/Shift 可多选")
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(hint)

        self.viewer = DirectPdfViewer(self.fonts)
        self.viewer.span_clicked.connect(self._span_selected)
        self.viewer.delete_text_requested.connect(self._delete_selected_text)
        self.viewer.style_edit_requested.connect(self._style_selected_text)
        self.viewer.inline_edit_requested.connect(self._inline_text_committed)
        self.viewer.new_text_requested.connect(self._new_text_committed)
        self.viewer.move_text_requested.connect(self._move_selected_text)
        self.viewer.form_field_edited.connect(self._form_field_edited)
        self.viewer.ink_stroke_requested.connect(self._ink_stroke_committed)
        self.viewer.zoom_requested.connect(self._zoom_step)

        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel("PDF")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(88, 88)
        icon_label.setStyleSheet(
            "background:#1467d9;color:white;border-radius:18px;"
            "font-size:25px;font-weight:800;"
        )
        empty_title = QLabel("打开 PDF，开始浏览与编辑")
        empty_title.setStyleSheet("font-size:20px;font-weight:700;color:#172033;")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_tip = QLabel("可直接拖入 PDF 文件，或点击下方按钮")
        empty_tip.setObjectName("Muted")
        empty_tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        open_button = QPushButton("打开 PDF")
        open_button.setObjectName("Primary")
        open_button.setFixedWidth(150)
        open_button.clicked.connect(self.open_dialog)
        empty_layout.addStretch(1)
        empty_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addSpacing(14)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_tip)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch(1)

        self.center_stack = QWidget()
        center_layout = QVBoxLayout(self.center_stack)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.empty_state)
        center_layout.addWidget(self.viewer)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.center_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([196, 1100])
        self.setCentralWidget(splitter)

        status = QStatusBar()
        self.setStatusBar(status)
        self.file_status = QLabel("未打开文件")
        self.text_status = QLabel("")
        self.page_status = QLabel("")
        self.zoom_status = QLabel("")
        status.addWidget(self.file_status, 1)
        status.addPermanentWidget(self.text_status)
        status.addPermanentWidget(self.page_status)
        status.addPermanentWidget(self.zoom_status)

    def _make_action(
        self,
        text: str,
        slot,
        shortcut: str | QKeySequence | None = None,
        *,
        checkable: bool = False,
        tooltip: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.setToolTip(tooltip or text)
        return action

    def _build_actions(self) -> None:
        self.open_action = self._make_action("打开", self.open_dialog, QKeySequence.StandardKey.Open)
        self.export_action = self._make_action(
            "导出 PDF", self.export_dialog, QKeySequence.StandardKey.SaveAs
        )
        self.insert_action = self._make_action("插入 PDF", self._insert_pdf, "Ctrl+I")
        self.delete_page_action = self._make_action(
            "删除页面", self._delete_pages, "Ctrl+Delete"
        )
        self.rotate_left_action = self._make_action("左转", lambda: self._rotate_pages(-90))
        self.rotate_right_action = self._make_action("右转", lambda: self._rotate_pages(90))
        self.undo_action = self._make_action("撤销", self._undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._make_action("重做", self._redo, QKeySequence.StandardKey.Redo)
        self.prev_action = self._make_action("上一页", self._previous_page, "PageUp")
        self.next_action = self._make_action("下一页", self._next_page, "PageDown")
        self.zoom_out_action = self._make_action("缩小", lambda: self._zoom_step(-1), "Ctrl+-")
        self.zoom_in_action = self._make_action("放大", lambda: self._zoom_step(1), "Ctrl++")
        self.fit_action = self._make_action("适合宽度", self._fit_to_width, "Ctrl+0")

        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.browse_mode_action = self._make_action(
            "浏览", lambda: self._set_mode("browse"), checkable=True
        )
        self.select_mode_action = self._make_action(
            "选择文字", lambda: self._set_mode("select"), checkable=True
        )
        self.add_mode_action = self._make_action(
            "添加文字", lambda: self._set_mode("add"), checkable=True
        )
        self.form_mode_action = self._make_action(
            "填写表单", lambda: self._set_mode("form"), checkable=True
        )
        self.signature_mode_action = self._make_action(
            "签名画笔", lambda: self._set_mode("signature"), checkable=True
        )
        for action in (
            self.browse_mode_action,
            self.select_mode_action,
            self.add_mode_action,
            self.form_mode_action,
            self.signature_mode_action,
        ):
            self.mode_group.addAction(action)
        self.browse_mode_action.setChecked(True)

    def _build_menus_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.insert_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close, "Alt+F4")

        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.delete_page_action)
        edit_menu.addAction(self.rotate_left_action)
        edit_menu.addAction(self.rotate_right_action)

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction(self.browse_mode_action)
        view_menu.addAction(self.select_mode_action)
        view_menu.addAction(self.add_mode_action)
        view_menu.addAction(self.form_mode_action)
        view_menu.addAction(self.signature_mode_action)
        view_menu.addSeparator()
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.fit_action)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("使用说明", self._show_help)
        help_menu.addAction("开源许可", self._show_licenses)
        help_menu.addAction(f"关于 {APP_NAME}", self._show_about)

        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.setStyleSheet("QToolButton { padding: 6px 5px; }")
        self.addToolBar(toolbar)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.export_action)
        toolbar.addSeparator()
        toolbar.addAction(self.insert_action)
        toolbar.addAction(self.delete_page_action)
        toolbar.addAction(self.rotate_left_action)
        toolbar.addAction(self.rotate_right_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.browse_mode_action)
        toolbar.addAction(self.select_mode_action)
        toolbar.addAction(self.add_mode_action)
        toolbar.addAction(self.form_mode_action)
        toolbar.addAction(self.signature_mode_action)
        toolbar.addSeparator()
        toolbar.addAction(self.prev_action)
        toolbar.addAction(self.next_action)
        toolbar.addAction(self.zoom_out_action)
        toolbar.addAction(self.zoom_in_action)
        toolbar.addAction(self.fit_action)

    def _show_empty_state(self) -> None:
        self.empty_state.show()
        self.viewer.hide()
        self.page_list.clear()
        self.page_badge.setText("0")
        self.file_status.setText("未打开文件")
        self.text_status.setText("")
        self.page_status.setText("")
        self.zoom_status.setText("")

    def _show_document_state(self) -> None:
        self.empty_state.hide()
        self.viewer.show()

    def _title(self) -> str:
        if not self.model.is_open:
            return APP_NAME
        name = Path(self.model.saved_path or self.model.source_path or "未命名.pdf").name
        return f"{'*' if self.model.modified else ''}{name} - {APP_NAME}"

    def _set_mode(self, mode: str) -> None:
        self.viewer.canvas.set_mode(mode)
        if mode == "select":
            self.statusBar().showMessage(
                "单击选择文字；按住拖动可移动；双击编辑；Delete 或 Backspace 删除", 3500
            )
        elif mode == "add":
            self.current_span = None
            self.viewer.canvas.select_span(None)
            self.statusBar().showMessage("点击页面任意位置，直接输入新增文字", 3500)
        elif mode == "form":
            self.current_span = None
            count = len(self.model.form_fields(self.current_page)) if self.model.is_open else 0
            self.statusBar().showMessage(
                f"当前页有 {count} 个表单字段，点击蓝框直接填写"
                if count
                else "当前页没有可填写的表单字段",
                3500,
            )
        elif mode == "signature":
            self.current_span = None
            self.statusBar().showMessage(
                "按住鼠标在页面上绘制签名；右上角可调整颜色和粗细", 3500
            )
        else:
            self.statusBar().showMessage("浏览模式：滚轮翻动，Ctrl + 滚轮缩放", 2500)

    def open_dialog(self) -> None:
        if not self._confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if path:
            self.open_path(path, already_confirmed=True)

    def open_path(self, path: str, already_confirmed: bool = False) -> None:
        if not already_confirmed and not self._confirm_discard_changes():
            return
        password = ""
        while True:
            try:
                self.model.open_file(path, password)
                break
            except PasswordRequired:
                password, ok = QInputDialog.getText(
                    self,
                    "PDF 密码",
                    f"{Path(path).name} 需要密码：",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return
            except PdfError as exc:
                self._error(str(exc))
                return
        self.current_page = 0
        self.current_span = None
        self.fit_width = True
        self._show_document_state()
        self._rebuild_document()
        form_count = self.model.form_field_count
        self.statusBar().showMessage(
            f"PDF 已打开，发现 {form_count} 个可填写表单字段"
            if form_count
            else "PDF 已打开",
            3500 if form_count else 2500,
        )

    def export_dialog(self) -> bool:
        if not self.model.is_open:
            return False
        source = Path(self.model.saved_path or self.model.source_path or "document.pdf")
        suggested = source.with_name(f"{source.stem}-已编辑.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PDF", str(suggested), "PDF 文件 (*.pdf)"
        )
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.model.save_as(path)
        except PdfError as exc:
            self._error(str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.setWindowTitle(self._title())
        self.file_status.setText(str(Path(path)))
        self.statusBar().showMessage("导出完成，文件已重新打开校验", 3500)
        self._update_actions()
        return True

    def _confirm_discard_changes(self) -> bool:
        if not self.model.is_open or not self.model.modified:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("尚未导出")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("当前 PDF 有未导出的修改。")
        box.setInformativeText("是否先导出修改后的 PDF？")
        save = box.addButton("导出", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save:
            return self.export_dialog()
        if clicked == discard:
            return True
        return clicked != cancel and False

    def _probe_pdf(self, path: str) -> tuple[int, str] | None:
        try:
            source = pymupdf.open(path)
        except Exception as exc:
            self._error(f"无法打开要插入的 PDF：{exc}")
            return None
        password = ""
        try:
            if source.needs_pass:
                password, ok = QInputDialog.getText(
                    self,
                    "PDF 密码",
                    f"{Path(path).name} 需要密码：",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return None
                if not source.authenticate(password):
                    self._error("密码不正确。")
                    return None
            return source.page_count, password
        finally:
            source.close()

    def _insert_pdf(self, preset_path: str | None = None) -> None:
        if not self.model.is_open:
            self.open_dialog()
            return
        path = preset_path
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择要插入的 PDF", "", "PDF 文件 (*.pdf)"
            )
        if not path:
            return
        info = self._probe_pdf(path)
        if not info:
            return
        source_pages, password = info
        dialog = InsertPdfDialog(path, source_pages, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        position = dialog.position.currentData()
        if position == "before":
            insert_at = self.current_page
        elif position == "end":
            insert_at = self.model.page_count
        else:
            insert_at = self.current_page + 1
        try:
            count = self.model.insert_pdf(
                path,
                insert_at,
                dialog.from_page.value() - 1,
                dialog.to_page.value() - 1,
                password,
            )
        except PdfError as exc:
            self._error(str(exc))
            return
        self.current_page = insert_at
        self._rebuild_document()
        self.statusBar().showMessage(f"已插入 {count} 页", 2500)

    def _selected_pages(self) -> list[int]:
        rows = sorted({self.page_list.row(item) for item in self.page_list.selectedItems()})
        return rows or ([self.current_page] if self.model.is_open else [])

    def _delete_pages(self) -> None:
        pages = self._selected_pages()
        if not pages:
            return
        label = "、".join(str(index + 1) for index in pages[:6])
        if len(pages) > 6:
            label += "…"
        if (
            QMessageBox.question(
                self,
                "删除页面",
                f"确定删除第 {label} 页吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.model.delete_pages(pages)
        except PdfError as exc:
            self._error(str(exc))
            return
        self.current_page = min(pages[0], self.model.page_count - 1)
        self._rebuild_document()

    def _rotate_pages(self, degrees: int) -> None:
        try:
            self.model.rotate_pages(self._selected_pages(), degrees)
        except PdfError as exc:
            self._error(str(exc))
            return
        self._rebuild_document()

    def _pages_reordered(self, order: list[int]) -> None:
        new_current = max(0, self.page_list.currentRow())
        try:
            self.model.reorder_pages(order)
        except PdfError as exc:
            self._error(str(exc))
            self._rebuild_document()
            return
        self.current_page = new_current
        self._rebuild_document()
        self.statusBar().showMessage("页面顺序已更新", 1800)

    def _undo(self) -> None:
        label = self.model.undo()
        if label:
            self.current_page = min(self.current_page, self.model.page_count - 1)
            self._rebuild_document()
            self.statusBar().showMessage(f"已撤销：{label}", 1800)

    def _redo(self) -> None:
        label = self.model.redo()
        if label:
            self.current_page = min(self.current_page, self.model.page_count - 1)
            self._rebuild_document()
            self.statusBar().showMessage(f"已重做：{label}", 1800)

    def _previous_page(self) -> None:
        if self.current_page > 0:
            self.page_list.setCurrentRow(self.current_page - 1)

    def _next_page(self) -> None:
        if self.current_page + 1 < self.model.page_count:
            self.page_list.setCurrentRow(self.current_page + 1)

    def _page_changed(self, row: int) -> None:
        if row < 0 or not self.model.is_open or row == self.current_page:
            return
        self.current_page = row
        self.current_span = None
        self._render_current_page()

    def _fit_to_width(self) -> None:
        if not self.model.is_open:
            return
        self.fit_width = True
        width, _ = self.model.page_size(self.current_page)
        available = max(self.viewer.viewport().width() - 34, 100)
        self.zoom = max(0.25, min(4.0, available / max(width, 1)))
        self._render_current_page()

    def _zoom_step(self, direction: int) -> None:
        if not self.model.is_open:
            return
        self.fit_width = False
        factor = 1.15 if direction > 0 else 1 / 1.15
        self.zoom = max(0.25, min(4.0, self.zoom * factor))
        self._render_current_page()

    def _rebuild_document(self) -> None:
        self.current_span = None
        self.current_page = max(0, min(self.current_page, self.model.page_count - 1))
        with QSignalBlocker(self.page_list):
            self.page_list.rebuild(self.model, self.current_page)
        if self.fit_width:
            self._fit_to_width()
        else:
            self._render_current_page()
        self.page_badge.setText(str(self.model.page_count))
        self.file_status.setText(str(Path(self.model.saved_path or self.model.source_path or "")))
        self.setWindowTitle(self._title())
        self._update_actions()

    def _render_current_page(self) -> None:
        if not self.model.is_open:
            return
        try:
            data, width, height, stride = self.model.render_page(self.current_page, self.zoom)
            image = qimage_from_render(data, width, height, stride)
            spans = self.model.text_spans(self.current_page)
            form_fields = self.model.form_fields(self.current_page)
        except Exception as exc:
            self._error(f"页面渲染失败：{exc}")
            return
        self.viewer.canvas.set_page(
            image, self.zoom, spans, form_fields, self.current_span
        )
        status_parts = [f"{len(spans)} 个文本块" if spans else "无文本层"]
        if form_fields:
            status_parts.append(f"{len(form_fields)} 个表单项")
        self.text_status.setText(" · ".join(status_parts) + "  ")
        self.page_status.setText(f"第 {self.current_page + 1} / {self.model.page_count} 页  ")
        self.zoom_status.setText(f"{round(self.zoom * 100)}%  ")
        self._update_actions()

    def _span_selected(self, span: TextSpan) -> None:
        self.current_span = span
        preview = span.text.replace("\n", " ")
        if len(preview) > 35:
            preview = preview[:35] + "…"
        self.statusBar().showMessage(
            f"已选：{preview}　拖动移动，双击编辑，Delete / Backspace 删除", 3000
        )

    def _inline_text_committed(
        self,
        span: TextSpan,
        text: str,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool,
        italic: bool,
        underline: bool,
        style_dirty: bool,
    ) -> None:
        if text == span.text and not style_dirty:
            return
        try:
            self.model.replace_text(
                self.current_page,
                span,
                text,
                font,
                size,
                color,
                bold,
                italic,
                underline,
            )
        except Exception as exc:
            self._error(f"文字修改失败：{exc}")
            return
        self.current_span = None
        self._rebuild_document()
        self.select_mode_action.setChecked(True)
        self._set_mode("select")
        self.statusBar().showMessage("文字已保存", 1800)

    def _delete_selected_text(self, span: TextSpan) -> None:
        try:
            self.model.replace_text(
                self.current_page,
                span,
                "",
                self.fonts[0],
                span.size,
                span.color,
            )
        except Exception as exc:
            self._error(f"删除文字失败：{exc}")
            return
        self.current_span = None
        self._rebuild_document()
        self.select_mode_action.setChecked(True)
        self._set_mode("select")
        self.statusBar().showMessage("文字已删除", 1800)

    def _style_selected_text(
        self,
        span: TextSpan,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool,
        italic: bool,
        underline: bool,
    ) -> None:
        try:
            self.model.replace_text(
                self.current_page,
                span,
                span.text,
                font,
                size,
                color,
                bold,
                italic,
                underline,
            )
        except Exception as exc:
            self._error(f"文字样式修改失败：{exc}")
            return
        self._rebuild_document()
        candidates = self.model.text_spans(self.current_page)
        if candidates:
            new_span = min(
                candidates,
                key=lambda item: (item.origin[0] - span.origin[0]) ** 2
                + (item.origin[1] - span.origin[1]) ** 2,
            )
            self.current_span = new_span
            self.viewer.canvas.select_span(
                new_span, (font, size, color, bold, italic, underline)
            )
        self.statusBar().showMessage("文字样式已更新", 1600)

    def _new_text_committed(
        self,
        x: float,
        y: float,
        text: str,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool,
        italic: bool,
        underline: bool,
    ) -> None:
        try:
            self.model.add_text(
                self.current_page,
                (x, y),
                text,
                font,
                size,
                color,
                bold,
                italic,
                underline,
            )
        except Exception as exc:
            self._error(f"添加文字失败：{exc}")
            return
        self._rebuild_document()
        self.select_mode_action.setChecked(True)
        self._set_mode("select")
        self.statusBar().showMessage("文字已添加", 1800)

    def _move_selected_text(
        self,
        span: TextSpan,
        x: float,
        y: float,
        font: FontChoice,
        size: float,
        color: tuple[float, float, float],
        bold: bool,
        italic: bool,
        underline: bool,
    ) -> None:
        try:
            self.model.move_text(
                self.current_page,
                span,
                (x, y),
                font,
                size,
                color,
                bold,
                italic,
                underline,
            )
        except Exception as exc:
            self._error(f"移动文字失败：{exc}")
            self._render_current_page()
            return
        self._rebuild_document()
        candidates = [
            item for item in self.model.text_spans(self.current_page) if item.text == span.text
        ]
        if candidates:
            new_span = min(
                candidates,
                key=lambda item: (item.origin[0] - x) ** 2 + (item.origin[1] - y) ** 2,
            )
            self.current_span = new_span
            self.viewer.canvas.select_span(
                new_span, (font, size, color, bold, italic, underline)
            )
        self.statusBar().showMessage("文字位置已更新", 1800)

    def _form_field_edited(self, field: FormField, value: str) -> None:
        if str(value) == field.value:
            return
        try:
            self.model.set_form_field(field, value)
        except Exception as exc:
            self._error(f"填写表单失败：{exc}")
            self._render_current_page()
            return
        self._render_current_page()
        self.setWindowTitle(self._title())
        self._update_actions()
        self.statusBar().showMessage(f"表单字段“{field.label}”已保存", 1800)

    def _ink_stroke_committed(
        self,
        points: list[tuple[float, float]],
        color: tuple[float, float, float],
        width: float,
    ) -> None:
        try:
            self.model.add_ink_stroke(self.current_page, points, color, width)
        except Exception as exc:
            self._error(f"添加签名笔迹失败：{exc}")
            self._render_current_page()
            return
        self._render_current_page()
        self.setWindowTitle(self._title())
        self._update_actions()
        self.statusBar().showMessage("签名笔迹已添加，可继续绘制或按 Ctrl+Z 撤销", 1800)

    def _update_actions(self) -> None:
        opened = self.model.is_open
        selected_count = len(self._selected_pages()) if opened else 0
        for action in (
            self.export_action,
            self.insert_action,
            self.rotate_left_action,
            self.rotate_right_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_action,
            self.browse_mode_action,
            self.select_mode_action,
            self.add_mode_action,
            self.signature_mode_action,
        ):
            action.setEnabled(opened)
        self.form_mode_action.setEnabled(opened and self.model.form_field_count > 0)
        self.delete_page_action.setEnabled(opened and self.model.page_count > selected_count)
        self.undo_action.setEnabled(self.model.can_undo)
        self.redo_action.setEnabled(self.model.can_redo)
        self.undo_action.setText(
            f"撤销 {self.model.undo_label}" if self.model.undo_label else "撤销"
        )
        self.redo_action.setText(
            f"重做 {self.model.redo_label}" if self.model.redo_label else "重做"
        )
        self.prev_action.setEnabled(opened and self.current_page > 0)
        self.next_action.setEnabled(opened and self.current_page + 1 < self.model.page_count)

    def _error(self, message: str) -> None:
        QMessageBox.critical(self, APP_NAME, message)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "使用说明",
            "页面管理\n"
            "• 左侧拖拽缩略图可重新排序\n"
            "• 可多选页面后删除或旋转\n"
            "• “插入 PDF”可选择页码范围和插入位置\n\n"
            "文字编辑\n"
            "• 单击选择文字，Delete 或 Backspace 直接删除\n"
            "• 按住已选文字并拖动，可直接调整文本块位置\n"
            "• 双击原文即可在页面原位修改；Enter 或点击别处确认，Esc 取消\n"
            "• 字体、字号和颜色通过文字附近的浮动工具条修改\n"
            "• 浮动工具条中的 B / I / U 可设置加粗、斜体和下划线\n"
            "• 选择“添加文字”，点击页面位置后直接输入\n"
            "• 扫描件或纯图片 PDF 没有文本层，无法直接选择文字\n\n"
            "表单与签名\n"
            "• 检测到可填写字段后，选择“填写表单”并直接点击蓝框输入\n"
            "• 支持文本、复选、单选、下拉和列表字段，导出后仍可交互\n"
            "• 选择“签名画笔”后按住鼠标绘制，右上角可调整颜色和粗细\n"
            "• 每一笔都可通过 Ctrl+Z 撤销\n\n"
            "浏览\n"
            "• Ctrl + 鼠标滚轮缩放，PageUp/PageDown 翻页",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            f"<b>{APP_NAME} {APP_VERSION}</b><br>"
            "轻量 PDF 浏览、页面整理、表单填写、签名与文本层编辑工具。<br><br>"
            "完全免费并以 GNU AGPL v3 开源。<br>"
            "PDF 引擎：PyMuPDF · 界面：Qt for Python<br><br>"
            f'源代码：<a href="{PROJECT_URL}">{PROJECT_URL}</a>',
        )

    def _show_licenses(self) -> None:
        QMessageBox.information(
            self,
            "开源许可",
            f"{APP_NAME} 按 GNU AGPL v3 许可发布。\n\n"
            "PyMuPDF/MuPDF 使用 AGPL v3；Qt for Python/PySide6 使用其 GPL v3 "
            "开源许可选项。其他第三方组件及完整许可文本请查看项目根目录的 "
            "THIRD_PARTY_NOTICES.md 与 licenses 文件夹。\n\n"
            f"完整源代码：{PROJECT_URL}",
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.toLocalFile().lower().endswith(".pdf") for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith(".pdf")
        ]
        if not paths:
            return
        if not self.model.is_open:
            self.open_path(paths[0])
        else:
            self._insert_pdf(paths[0])
        event.acceptProposedAction()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self.fit_width and self.model.is_open:
            QTimer.singleShot(0, self._fit_to_width)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard_changes():
            self.model.close()
            event.accept()
        else:
            event.ignore()


def configure_application(app: QApplication) -> None:
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    font_family = "Segoe UI"
    windows_font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"
    if windows_font.exists():
        font_id = QFontDatabase.addApplicationFont(str(windows_font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if "Microsoft YaHei UI" in families:
            font_family = "Microsoft YaHei UI"
        elif families:
            font_family = families[0]
    font = QFont(font_family, 9)
    app.setFont(font)
