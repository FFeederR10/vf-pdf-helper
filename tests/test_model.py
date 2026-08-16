from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pymupdf
import pytest

from pdf_helper.model import (
    BUILTIN_FONTS,
    PdfDocumentModel,
    _font_allows_editable_embedding,
    available_fonts,
)


def make_pdf(path: Path, labels: list[str]) -> None:
    doc = pymupdf.open()
    for label in labels:
        page = doc.new_page(width=420, height=300)
        page.insert_text((40, 70), label, fontsize=18, fontname="helv")
        page.insert_text((40, 110), "CAD-100", fontsize=12, fontname="cour")
        page.draw_line((30, 140), (390, 140), color=(0, 0, 0), width=1)
    doc.save(path)
    doc.close()


def make_form_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=300)
    page.insert_text((35, 42), "Application Form", fontsize=16, fontname="hebo")

    name = pymupdf.Widget()
    name.field_name = "full_name"
    name.field_label = "Full name"
    name.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    name.rect = pymupdf.Rect(40, 60, 280, 88)
    name.field_value = ""
    page.add_widget(name)

    agree = pymupdf.Widget()
    agree.field_name = "agree"
    agree.field_label = "I agree"
    agree.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    agree.rect = pymupdf.Rect(40, 110, 60, 130)
    agree.field_value = False
    page.add_widget(agree)

    country = pymupdf.Widget()
    country.field_name = "country"
    country.field_label = "Country"
    country.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
    country.rect = pymupdf.Rect(40, 150, 210, 178)
    country.choice_values = ["Australia", "China", "Singapore"]
    country.field_value = "Australia"
    page.add_widget(country)

    doc.save(path)
    doc.close()


def page_texts(model: PdfDocumentModel) -> list[str]:
    assert model.doc is not None
    return [model.doc.load_page(i).get_text() for i in range(model.page_count)]


def test_page_workflow_and_export(tmp_path: Path) -> None:
    base = tmp_path / "base.pdf"
    extra = tmp_path / "extra.pdf"
    output = tmp_path / "output.pdf"
    make_pdf(base, ["PAGE-A", "PAGE-B", "PAGE-C"])
    make_pdf(extra, ["EXTRA-1", "EXTRA-2"])

    model = PdfDocumentModel()
    model.open_file(str(base))
    assert model.page_count == 3
    assert "PAGE-A" in page_texts(model)[0]

    model.reorder_pages([2, 0, 1])
    assert ["PAGE-C", "PAGE-A", "PAGE-B"] == [
        text.splitlines()[0] for text in page_texts(model)
    ]

    model.insert_pdf(str(extra), 1, 0, 1)
    assert model.page_count == 5
    assert "EXTRA-1" in page_texts(model)[1]
    assert "EXTRA-2" in page_texts(model)[2]

    model.delete_pages([2])
    assert model.page_count == 4
    assert "EXTRA-2" not in "\n".join(page_texts(model))

    model.rotate_pages([0], 90)
    assert model.doc is not None
    assert model.doc.load_page(0).rotation == 90

    model.save_as(str(output))
    assert output.exists()
    check = pymupdf.open(output)
    assert check.page_count == 4
    assert "EXTRA-1" in check.load_page(1).get_text()
    check.close()


def test_text_replace_add_delete_and_undo(tmp_path: Path) -> None:
    source = tmp_path / "text.pdf"
    make_pdf(source, ["DRAWING-42"])
    model = PdfDocumentModel()
    model.open_file(str(source))

    spans = model.text_spans(0)
    target = next(span for span in spans if span.text == "DRAWING-42")
    model.replace_text(0, target, "DRAWING-99", BUILTIN_FONTS[0], 18, (0, 0, 1))
    assert model.doc is not None
    text = model.doc.load_page(0).get_text()
    assert "DRAWING-42" not in text
    assert "DRAWING-99" in text

    model.add_text(0, (40, 190), "NEW NOTE", BUILTIN_FONTS[1], 14, (1, 0, 0))
    assert "NEW NOTE" in model.doc.load_page(0).get_text()

    added_span = next(span for span in model.text_spans(0) if span.text == "NEW NOTE")
    model.replace_text(0, added_span, "", BUILTIN_FONTS[0], 14, (0, 0, 0))
    assert "NEW NOTE" not in model.doc.load_page(0).get_text()

    assert model.undo() == "编辑文字"
    assert "NEW NOTE" in model.doc.load_page(0).get_text()
    assert model.redo() == "编辑文字"
    assert "NEW NOTE" not in model.doc.load_page(0).get_text()


def test_move_text_repositions_once_and_can_be_undone(tmp_path: Path) -> None:
    source = tmp_path / "move.pdf"
    make_pdf(source, ["DRAWING-42"])
    model = PdfDocumentModel()
    model.open_file(str(source))

    target = next(span for span in model.text_spans(0) if span.text == "DRAWING-42")
    destination = (210.0, 190.0)
    model.move_text(
        0,
        target,
        destination,
        BUILTIN_FONTS[0],
        target.size,
        target.color,
    )

    assert model.doc is not None
    assert model.doc.load_page(0).get_text().count("DRAWING-42") == 1
    moved = next(span for span in model.text_spans(0) if span.text == "DRAWING-42")
    assert moved.origin == pytest.approx(destination, abs=0.2)
    assert moved.origin != pytest.approx(target.origin, abs=0.2)

    assert model.undo() == "移动文字"
    restored = next(span for span in model.text_spans(0) if span.text == "DRAWING-42")
    assert restored.origin == pytest.approx(target.origin, abs=0.2)


def test_render_and_text_metadata(tmp_path: Path) -> None:
    source = tmp_path / "render.pdf"
    make_pdf(source, ["RENDER"])
    model = PdfDocumentModel()
    model.open_file(str(source))

    samples, width, height, stride = model.render_page(0, 1.0)
    assert samples
    assert width == 420
    assert height == 300
    assert stride >= width * 3

    spans = model.text_spans(0)
    assert any(span.text == "RENDER" for span in spans)
    assert all(len(span.color) == 3 for span in spans)


def test_chinese_text_uses_system_font_fallback(tmp_path: Path) -> None:
    if not any(font.file_path for font in available_fonts()):
        return
    source = tmp_path / "chinese.pdf"
    make_pdf(source, ["BASE"])
    model = PdfDocumentModel()
    model.open_file(str(source))
    model.add_text(0, (40, 230), "中文备注 123", BUILTIN_FONTS[0], 14, (0, 0, 0))
    assert model.doc is not None
    extracted = model.doc.load_page(0).get_text().replace("\xa0", " ")
    assert "中文备注 123" in extracted


def test_non_font_resource_name_collision_does_not_break_text_insertion(tmp_path: Path) -> None:
    unicode_font = next((font for font in available_fonts() if font.file_path), None)
    if unicode_font is None:
        return
    source = tmp_path / "font-resource-collision.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=360, height=240)
    page.insert_text((30, 50), "BASE", fontsize=12, fontname="helv")
    non_font_xref = doc.get_new_xref()
    doc.update_object(
        non_font_xref,
        "<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] >>",
    )
    resources_xref = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    hashed_name = "PHF" + hashlib.sha1(
        unicode_font.file_path.lower().encode("utf-8")
    ).hexdigest()[:10]
    doc.xref_set_key(
        resources_xref,
        f"Font/{unicode_font.pdf_name}",
        f"{non_font_xref} 0 R",
    )
    doc.xref_set_key(
        resources_xref,
        f"Font/{hashed_name}",
        f"{non_font_xref} 0 R",
    )
    doc.save(source)
    doc.close()

    model = PdfDocumentModel()
    model.open_file(str(source))
    model.add_text(0, (40, 100), "冲突后仍可写入", BUILTIN_FONTS[0], 14, (0, 0, 0))
    assert model.doc is not None
    extracted = model.doc.load_page(0).get_text().replace("\xa0", " ")
    assert "冲突后仍可写入" in extracted


def test_fillable_form_fields_remain_interactive_and_undoable(tmp_path: Path) -> None:
    source = tmp_path / "form.pdf"
    output = tmp_path / "filled.pdf"
    make_form_pdf(source)
    model = PdfDocumentModel()
    model.open_file(str(source))

    fields = {field.name: field for field in model.form_fields(0)}
    assert model.form_field_count == 3
    assert fields["country"].choices == ("Australia", "China", "Singapore")

    model.set_form_field(fields["full_name"], "Bob Chen")
    fields = {field.name: field for field in model.form_fields(0)}
    model.set_form_field(fields["agree"], fields["agree"].on_value or "Yes")
    fields = {field.name: field for field in model.form_fields(0)}
    model.set_form_field(fields["country"], "China")

    filled = {field.name: field for field in model.form_fields(0)}
    assert filled["full_name"].value == "Bob Chen"
    assert filled["agree"].value != "Off"
    assert filled["country"].value == "China"
    assert model.undo() == "填写表单"
    assert {field.name: field.value for field in model.form_fields(0)}["country"] == "Australia"

    model.redo()
    model.save_as(str(output))
    check = pymupdf.open(output)
    widgets = {widget.field_name: widget for widget in check[0].widgets()}
    assert widgets["full_name"].field_value == "Bob Chen"
    assert widgets["agree"].field_value != "Off"
    assert widgets["country"].field_value == "China"
    for widget in widgets.values():
        assert check.xref_get_key(widget.xref, "AP")[0] != "null"
    check.close()


def test_signature_ink_and_text_emphasis_are_real_pdf_objects(tmp_path: Path) -> None:
    source = tmp_path / "signature-style.pdf"
    doc = pymupdf.open()
    doc.new_page(width=420, height=300)
    doc.save(source)
    doc.close()

    model = PdfDocumentModel()
    model.open_file(str(source))
    model.add_ink_stroke(
        0,
        [(60, 220), (95, 190), (125, 225), (165, 185), (205, 218)],
        (0.0, 0.2, 0.65),
        3,
    )
    assert model.doc is not None
    ink = [annot for annot in model.doc[0].annots() if annot.type[0] == pymupdf.PDF_ANNOT_INK]
    assert len(ink) == 1
    assert ink[0].info["subject"] == "VF PDF Helper signature ink"

    model.add_text(
        0,
        (55, 90),
        "Bold Italic Underline",
        BUILTIN_FONTS[0],
        18,
        (0.1, 0.1, 0.1),
        True,
        True,
        True,
    )
    styled = next(span for span in model.text_spans(0) if span.text == "Bold Italic Underline")
    assert styled.flags & (1 << 4)
    assert styled.flags & (1 << 1)
    assert styled.underline

    model.replace_text(
        0,
        styled,
        styled.text,
        BUILTIN_FONTS[0],
        18,
        styled.color,
        False,
        False,
        False,
    )
    regular = next(span for span in model.text_spans(0) if span.text == styled.text)
    assert not (regular.flags & (1 << 4))
    assert not (regular.flags & (1 << 1))
    assert not regular.underline
    assert not any(
        annot.type[0] == pymupdf.PDF_ANNOT_UNDERLINE
        and annot.info.get("subject") == "VF PDF Helper underline"
        for annot in model.doc[0].annots() or ()
    )


@pytest.mark.parametrize(
    ("fs_type", "allowed"),
    [
        (0x0000, True),
        (0x0002, False),
        (0x0004, False),
        (0x0008, True),
        (0x0004 | 0x0008, True),
        (0x0008 | 0x0200, False),
    ],
)
def test_editable_font_embedding_flags(
    tmp_path: Path, fs_type: int, allowed: bool
) -> None:
    font_path = tmp_path / "font.ttf"
    table_offset = 28
    sfnt_header = b"\x00\x01\x00\x00" + struct.pack(">H", 1) + b"\x00" * 6
    table_record = b"OS/2" + b"\x00" * 4 + struct.pack(">II", table_offset, 10)
    os2_table = b"\x00" * 8 + struct.pack(">H", fs_type)
    font_path.write_bytes(sfnt_header + table_record + os2_table)

    _font_allows_editable_embedding.cache_clear()
    assert _font_allows_editable_embedding(str(font_path)) is allowed
    _font_allows_editable_embedding.cache_clear()
