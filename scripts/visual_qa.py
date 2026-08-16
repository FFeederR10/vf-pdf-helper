from __future__ import annotations

import os
from pathlib import Path

import pymupdf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pdf_helper.model import BUILTIN_FONTS, PdfDocumentModel
from pdf_helper.ui import MainWindow, configure_application


ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / "tmp" / "pdfs"
OUTPUT = ROOT / "output" / "pdf"
TEMP.mkdir(parents=True, exist_ok=True)
OUTPUT.mkdir(parents=True, exist_ok=True)


def create_cad_pdf(path: Path, page_labels: list[str]) -> None:
    doc = pymupdf.open()
    for index, label in enumerate(page_labels):
        page = doc.new_page(width=842, height=595)
        page.draw_rect((32, 32, 810, 563), color=(0.12, 0.18, 0.28), width=1.2)
        page.draw_rect((615, 447, 810, 563), color=(0.12, 0.18, 0.28), width=1)
        for x in range(90, 600, 70):
            page.draw_line((x, 85), (x, 430), color=(0.65, 0.69, 0.75), width=0.5)
        for y in range(85, 431, 55):
            page.draw_line((90, y), (580, y), color=(0.65, 0.69, 0.75), width=0.5)
        page.draw_circle((335, 258), 115, color=(0.05, 0.35, 0.78), width=2)
        page.draw_line((220, 258), (450, 258), color=(0.05, 0.35, 0.78), width=1)
        page.draw_line((335, 143), (335, 373), color=(0.05, 0.35, 0.78), width=1)
        page.insert_text((50, 65), f"CAD DRAWING / {label}", fontsize=20, fontname="hebo")
        page.insert_text((628, 474), f"SHEET: {index + 1}", fontsize=11, fontname="cour")
        page.insert_text((628, 500), "SCALE: 1:100", fontsize=11, fontname="cour")
        page.insert_text((628, 526), "REV: A", fontsize=11, fontname="cour")
        page.insert_text((270, 410), "Ø 230.00", fontsize=13, fontname="helv")
    doc.save(path)
    doc.close()


def build_edited_sample() -> Path:
    source = TEMP / "cad-source.pdf"
    insert = TEMP / "cad-insert.pdf"
    result = OUTPUT / "vf-pdf-helper-qa.pdf"
    create_cad_pdf(source, ["GROUND FLOOR", "FIRST FLOOR", "DETAIL"])
    create_cad_pdf(insert, ["INSERTED SHEET"])

    model = PdfDocumentModel()
    model.open_file(str(source))
    model.reorder_pages([2, 0, 1])
    model.insert_pdf(str(insert), 1)
    target = next(span for span in model.text_spans(0) if span.text == "REV: A")
    model.replace_text(0, target, "REV: B", BUILTIN_FONTS[4], 11, (0.8, 0.1, 0.1))
    model.add_text(0, (55, 545), "Edited with VF PDF Helper", BUILTIN_FONTS[1], 12, (0.05, 0.35, 0.78))
    model.save_as(str(result))
    model.close()
    return result


def capture_ui(pdf_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    window.show()
    window.open_path(str(pdf_path))
    window.select_mode_action.trigger()
    inline_span = next(span for span in window.model.text_spans(0) if span.text == "REV: B")
    window.viewer.canvas._open_existing_editor(inline_span)

    def capture() -> None:
        window.grab().save(str(TEMP / "vf-pdf-helper-window.png"))
        window.close()
        app.quit()

    QTimer.singleShot(800, capture)
    app.exec()


if __name__ == "__main__":
    sample = build_edited_sample()
    capture_ui(sample)
    print(sample)
    print(TEMP / "vf-pdf-helper-window.png")
