from __future__ import annotations

import os
from pathlib import Path

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit

from pdf_helper.ui import MainWindow, configure_application


def test_window_opens_pdf(tmp_path: Path) -> None:
    path = tmp_path / "smoke.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "SMOKE TEST", fontsize=16)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.open_path(str(path))
    app.processEvents()

    assert window.model.page_count == 1
    assert window.viewer.isVisible() is False  # top-level window itself is not shown in the test
    assert window.text_status.text().strip().endswith("text blocks")
    assert window.viewer.canvas.pixmap() is not None
    window.model.close()


def test_double_click_edits_text_inline(tmp_path: Path) -> None:
    path = tmp_path / "inline.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((40, 80), "OLD VALUE", fontsize=18)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.select_mode_action.trigger()
    app.processEvents()

    span = next(item for item in window.model.text_spans(0) if item.text == "OLD VALUE")
    x0, y0, x1, y1 = span.bbox
    click = QPoint(
        round((x0 + x1) / 2 * window.zoom),
        round((y0 + y1) / 2 * window.zoom),
    )
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=click)
    app.processEvents()
    toolbar = window.viewer.canvas.floating_toolbar
    target = QRect(
        round(x0 * window.zoom),
        round(y0 * window.zoom),
        round((x1 - x0) * window.zoom),
        round((y1 - y0) * window.zoom),
    )
    assert toolbar.isVisible()
    assert not toolbar.geometry().intersects(target)

    QTest.mouseDClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=click)
    app.processEvents()

    editor = window.viewer.canvas._inline_editor
    assert editor is not None
    assert editor.text() == "OLD VALUE"
    editor.setText("NEW VALUE")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()

    assert window.model.doc is not None
    assert "NEW VALUE" in window.model.doc.load_page(0).get_text()
    assert "OLD VALUE" not in window.model.doc.load_page(0).get_text()
    window.model.close()
    window.close()


@pytest.mark.parametrize("delete_key", [Qt.Key.Key_Delete, Qt.Key.Key_Backspace])
def test_selected_text_deletes_with_delete_or_backspace(tmp_path: Path, delete_key) -> None:
    path = tmp_path / "delete.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((40, 80), "DELETE ME", fontsize=18)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.select_mode_action.trigger()
    app.processEvents()

    span = next(item for item in window.model.text_spans(0) if item.text == "DELETE ME")
    x0, y0, x1, y1 = span.bbox
    click = QPoint(round((x0 + x1) / 2 * window.zoom), round((y0 + y1) / 2 * window.zoom))
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=click)
    QTest.keyClick(window.viewer.canvas, delete_key)
    app.processEvents()

    assert window.model.doc is not None
    assert "DELETE ME" not in window.model.doc.load_page(0).get_text()
    window.model.close()
    window.close()


def test_floating_toolbar_changes_selected_text_size(tmp_path: Path) -> None:
    path = tmp_path / "style.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((40, 80), "STYLE ME", fontsize=18)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.select_mode_action.trigger()
    app.processEvents()

    span = next(item for item in window.model.text_spans(0) if item.text == "STYLE ME")
    x0, y0, x1, y1 = span.bbox
    click = QPoint(round((x0 + x1) / 2 * window.zoom), round((y0 + y1) / 2 * window.zoom))
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=click)
    toolbar = window.viewer.canvas.floating_toolbar
    toolbar.size_combo.setEditText("24")
    toolbar._emit_style()
    app.processEvents()

    changed = next(item for item in window.model.text_spans(0) if item.text == "STYLE ME")
    assert changed.size == pytest.approx(24, abs=0.2)
    assert toolbar.isVisible()
    window.model.close()
    window.close()


def test_add_text_edits_on_page_and_click_away_saves(tmp_path: Path) -> None:
    path = tmp_path / "add.pdf"
    doc = pymupdf.open()
    doc.new_page(width=360, height=240)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.add_mode_action.trigger()
    app.processEvents()

    insert_point = QPoint(round(120 * window.zoom), round(150 * window.zoom))
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=insert_point)
    app.processEvents()
    editor = window.viewer.canvas._inline_editor
    assert editor is not None
    QTest.keyClicks(editor, "ADDED NOTE")
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    app.processEvents()

    assert window.model.doc is not None
    assert "ADDED NOTE" in window.model.doc.load_page(0).get_text()
    assert window.viewer.canvas._inline_editor is None
    window.model.close()
    window.close()


def test_selected_text_can_be_dragged_to_a_new_position(tmp_path: Path) -> None:
    path = tmp_path / "drag.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    page.insert_text((40, 80), "DRAG ME", fontsize=18)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.select_mode_action.trigger()
    app.processEvents()

    original = next(item for item in window.model.text_spans(0) if item.text == "DRAG ME")
    x0, y0, x1, y1 = original.bbox
    start = QPoint(
        round((x0 + x1) / 2 * window.zoom),
        round((y0 + y1) / 2 * window.zoom),
    )
    end = start + QPoint(round(125 * window.zoom), round(90 * window.zoom))
    canvas = window.viewer.canvas

    # A tiny hand movement remains a click instead of moving the PDF text.
    tiny_end = start + QPoint(1, 1)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    tiny_move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(tiny_end),
        QPointF(canvas.mapToGlobal(tiny_end)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, tiny_move)
    assert not canvas._dragging
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=tiny_end)
    app.processEvents()
    unchanged = next(item for item in window.model.text_spans(0) if item.text == "DRAG ME")
    assert unchanged.origin == pytest.approx(original.origin, abs=0.2)

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    global_end = canvas.mapToGlobal(end)
    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(end),
        QPointF(global_end),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, move_event)
    assert canvas._dragging
    assert not canvas.floating_toolbar.isVisible()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()

    moved = next(item for item in window.model.text_spans(0) if item.text == "DRAG ME")
    assert moved.origin[0] == pytest.approx(original.origin[0] + 125, abs=1.0)
    assert moved.origin[1] == pytest.approx(original.origin[1] + 90, abs=1.0)
    assert window.current_span == moved
    assert canvas.floating_toolbar.isVisible()
    window.model.close()
    window.close()


def test_form_mode_edits_text_and_checkbox_in_place(tmp_path: Path) -> None:
    path = tmp_path / "form-ui.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    text = pymupdf.Widget()
    text.field_name = "customer"
    text.field_label = "Customer"
    text.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    text.rect = pymupdf.Rect(40, 60, 260, 90)
    text.field_value = ""
    page.add_widget(text)
    check = pymupdf.Widget()
    check.field_name = "approved"
    check.field_label = "Approved"
    check.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    check.rect = pymupdf.Rect(40, 120, 62, 142)
    check.field_value = False
    page.add_widget(check)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    assert window.form_mode_action.isEnabled()
    window.form_mode_action.trigger()
    app.processEvents()

    canvas = window.viewer.canvas
    assert canvas.mode == "form"
    assert len(canvas._form_controls) == 2
    editor = next(item for item in canvas._form_controls if isinstance(item, QLineEdit))
    editor.setText("Bob Chen")
    editor.editingFinished.emit()
    app.processEvents()
    values = {field.name: field.value for field in window.model.form_fields(0)}
    assert values["customer"] == "Bob Chen"

    checkbox = next(item for item in canvas._form_controls if isinstance(item, QCheckBox))
    checkbox.click()
    app.processEvents()
    values = {field.name: field.value for field in window.model.form_fields(0)}
    assert values["approved"] != "Off"
    assert canvas.mode == "form"
    window.model.close()
    window.close()


def test_signature_mode_draws_ink_annotation(tmp_path: Path) -> None:
    path = tmp_path / "ink-ui.pdf"
    doc = pymupdf.open()
    doc.new_page(width=420, height=300)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.signature_mode_action.trigger()
    app.processEvents()

    canvas = window.viewer.canvas
    start = QPoint(round(70 * window.zoom), round(210 * window.zoom))
    path_points = [
        start + QPoint(round(dx * window.zoom), round(dy * window.zoom))
        for dx, dy in ((25, -25), (55, 4), (88, -30), (125, 0))
    ]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    for point in path_points:
        move_event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(canvas.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(canvas, move_event)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=path_points[-1])
    app.processEvents()

    assert window.model.doc is not None
    ink = [
        annot
        for annot in window.model.doc[0].annots()
        if annot.type[0] == pymupdf.PDF_ANNOT_INK
    ]
    assert len(ink) == 1
    assert canvas.mode == "signature"
    assert canvas.ink_toolbar.isVisible()
    window.model.close()
    window.close()


def test_new_text_supports_bold_italic_and_underline(tmp_path: Path) -> None:
    path = tmp_path / "styled-add-ui.pdf"
    doc = pymupdf.open()
    doc.new_page(width=420, height=300)
    doc.save(path)
    doc.close()

    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(path))
    window.add_mode_action.trigger()
    app.processEvents()

    insert_point = QPoint(round(80 * window.zoom), round(120 * window.zoom))
    QTest.mouseClick(window.viewer.canvas, Qt.MouseButton.LeftButton, pos=insert_point)
    toolbar = window.viewer.canvas.floating_toolbar
    toolbar.bold_button.click()
    toolbar.italic_button.click()
    toolbar.underline_button.click()
    app.processEvents()
    editor = window.viewer.canvas._inline_editor
    assert editor is not None
    editor.setText("STYLED NOTE")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()

    span = next(item for item in window.model.text_spans(0) if item.text == "STYLED NOTE")
    assert span.flags & (1 << 4)
    assert span.flags & (1 << 1)
    assert span.underline
    window.model.close()
    window.close()
