from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pdf_helper.model import PdfDocumentModel
from pdf_helper.three_d import ThreeDViewerDialog
from pdf_helper.ui import configure_application


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit(
            "Usage: python -m scripts.visual_qa_3d input-3d.pdf [output.png] "
            "[balanced|high|full]"
        )
    source = Path(args[0]).resolve()
    output = (
        Path(args[1]).resolve()
        if len(args) > 1
        else Path("tmp/pdfs/vf-pdf-helper-3d-view.png").resolve()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    quality = args[2].lower() if len(args) > 2 else "balanced"
    quality_indices = {"balanced": 0, "high": 1, "full": 2}
    if quality not in quality_indices:
        raise SystemExit("U3D quality must be balanced, high, or full.")

    model = PdfDocumentModel()
    model.open_file(str(source))
    annotation = next(
        item
        for page_index in range(model.page_count)
        for item in model.three_d_annotations(page_index)
        if item.format in {"PRC", "U3D"}
    )
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    dialog = ThreeDViewerDialog(
        model.three_d_stream(annotation), annotation.page_index + 1, annotation.format
    )
    dialog.show()

    result = {"ok": False, "quality_selected": False}
    window_output = output.with_name(f"{output.stem}-window.png")

    def capture() -> None:
        image = dialog.canvas.grabFramebuffer()
        result["ok"] = image.save(str(output))
        screen = dialog.screen()
        if screen is not None:
            screen.grabWindow(int(dialog.winId())).save(str(window_output))
        dialog.close()
        model.close()
        app.quit()

    def wait_until_ready() -> None:
        if annotation.format == "U3D" and dialog.loading_panel.isVisible():
            QTimer.singleShot(250, wait_until_ready)
            return
        if annotation.format == "U3D" and not dialog.detail_combo.isEnabled():
            QTimer.singleShot(250, wait_until_ready)
            return
        quality_index = quality_indices[quality]
        if (
            annotation.format == "U3D"
            and not result["quality_selected"]
            and dialog.detail_combo.currentIndex() != quality_index
        ):
            result["quality_selected"] = True
            dialog.detail_combo.setCurrentIndex(quality_index)
            QTimer.singleShot(250, wait_until_ready)
            return
        QTimer.singleShot(1500, capture)

    QTimer.singleShot(250, wait_until_ready)
    app.exec()
    if not result["ok"]:
        raise RuntimeError("Could not save the 3D viewer framebuffer.")
    print(output)
    print(window_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
