from __future__ import annotations

import sys
from pathlib import Path

from pdf_helper.model import BUILTIN_FONTS, PdfDocumentModel


def main() -> int:
    source = Path(sys.argv[1])
    model = PdfDocumentModel()
    model.open_file(str(source))
    existing = next(
        span
        for span in model.text_spans(0)
        if span.text.strip() and all(ord(character) < 128 for character in span.text)
    )
    model.replace_text(
        0,
        existing,
        existing.text,
        BUILTIN_FONTS[0],
        existing.size,
        existing.color,
    )
    model.add_text(
        0,
        (100, 760),
        "字体冲突回归测试",
        BUILTIN_FONTS[0],
        12,
        (0, 0, 0),
    )
    model.add_text(
        0,
        (100, 790),
        "第二次字体写入",
        BUILTIN_FONTS[0],
        12,
        (0, 0, 0),
    )
    assert model.doc is not None
    extracted = model.doc.load_page(0).get_text().replace("\xa0", " ")
    assert "字体冲突回归测试" in extracted
    assert "第二次字体写入" in extracted
    if len(sys.argv) > 2:
        model.save_as(sys.argv[2])
    print("PASS: Chinese text inserted and remains extractable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
