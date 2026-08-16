from __future__ import annotations

import hashlib
import os
import struct
import tempfile
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pymupdf

from pdf_helper.app_info import APP_NAME


class PdfError(RuntimeError):
    """A user-facing PDF operation error."""


class PasswordRequired(PdfError):
    """Raised when a PDF needs a password or the supplied password is invalid."""


@dataclass(frozen=True)
class TextSpan:
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]
    text: str
    font: str
    size: float
    color: tuple[float, float, float]
    flags: int
    underline: bool = False


@dataclass(frozen=True)
class FontChoice:
    label: str
    pdf_name: str
    file_path: str | None = None


@dataclass(frozen=True)
class FormField:
    page_index: int
    xref: int
    name: str
    label: str
    field_type: int
    field_type_string: str
    value: str
    choices: tuple[str, ...]
    rect: tuple[float, float, float, float]
    read_only: bool
    multiline: bool
    password: bool
    max_length: int
    on_value: str | None = None


BUILTIN_FONTS: tuple[FontChoice, ...] = (
    FontChoice("Helvetica", "helv"),
    FontChoice("Helvetica Bold", "hebo"),
    FontChoice("Times Roman", "tiro"),
    FontChoice("Times Bold", "tibo"),
    FontChoice("Courier", "cour"),
    FontChoice("Courier Bold", "cobo"),
    FontChoice("Helvetica Oblique", "heit"),
    FontChoice("Helvetica Bold Oblique", "hebi"),
    FontChoice("Times Italic", "tiit"),
    FontChoice("Times Bold Italic", "tibi"),
    FontChoice("Courier Oblique", "coit"),
    FontChoice("Courier Bold Oblique", "cobi"),
)


@lru_cache(maxsize=32)
def _font_allows_editable_embedding(file_path: str) -> bool:
    """Return whether a font's OpenType flags permit editable PDF embedding."""
    try:
        with Path(file_path).open("rb") as stream:
            signature = stream.read(4)
            if signature == b"ttcf":
                stream.seek(8)
                count_data = stream.read(4)
                if len(count_data) != 4 or struct.unpack(">I", count_data)[0] < 1:
                    return False
                offset_data = stream.read(4)
                if len(offset_data) != 4:
                    return False
                font_offset = struct.unpack(">I", offset_data)[0]
            else:
                font_offset = 0

            stream.seek(font_offset)
            sfnt_header = stream.read(12)
            if len(sfnt_header) != 12 or sfnt_header[:4] not in {
                b"\x00\x01\x00\x00",
                b"OTTO",
                b"true",
                b"typ1",
            }:
                return False
            table_count = struct.unpack(">H", sfnt_header[4:6])[0]
            if table_count < 1 or table_count > 4096:
                return False

            fs_type = None
            for _ in range(table_count):
                record = stream.read(16)
                if len(record) != 16:
                    return False
                if record[:4] != b"OS/2":
                    continue
                table_offset, table_length = struct.unpack(">II", record[8:16])
                if table_length < 10:
                    return False
                stream.seek(table_offset + 8)
                value = stream.read(2)
                if len(value) != 2:
                    return False
                fs_type = struct.unpack(">H", value)[0]
                break
            if fs_type is None:
                return False
    except (OSError, OverflowError, struct.error, ValueError):
        return False

    # Editable embedding is more permissive than preview-and-print/restricted.
    # Bit 9 means bitmap-only embedding, which is incompatible with PDF text.
    if fs_type & 0x0200:
        return False
    if fs_type & 0x0008:
        return True
    if fs_type & (0x0002 | 0x0004):
        return False
    return True


def available_fonts() -> tuple[FontChoice, ...]:
    # The family dropdown only shows regular faces. Bold and italic are controlled
    # by dedicated style buttons and resolved to the appropriate face on insertion.
    fonts = [BUILTIN_FONTS[0], BUILTIN_FONTS[2], BUILTIN_FONTS[4]]
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = (
        ("微软雅黑", "yahei", windows / "msyh.ttc"),
        ("宋体", "simsun", windows / "simsun.ttc"),
        ("黑体", "simhei", windows / "simhei.ttf"),
        ("Arial", "arial", windows / "arial.ttf"),
    )
    for label, name, path in candidates:
        if path.exists() and _font_allows_editable_embedding(str(path)):
            fonts.append(FontChoice(label, name, str(path)))
    return tuple(fonts)


class PdfDocumentModel:
    MAX_HISTORY = 12

    def __init__(self) -> None:
        self.doc: pymupdf.Document | None = None
        self.source_path: str | None = None
        self.saved_path: str | None = None
        self.modified = False
        self._undo: list[tuple[bytes, str]] = []
        self._redo: list[tuple[bytes, str]] = []

    @property
    def is_open(self) -> bool:
        return self.doc is not None and not self.doc.is_closed

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.is_open else 0

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1][1] if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1][1] if self._redo else ""

    def close(self) -> None:
        if self.doc and not self.doc.is_closed:
            self.doc.close()
        self.doc = None
        self.source_path = None
        self.saved_path = None
        self.modified = False
        self._undo.clear()
        self._redo.clear()

    def open_file(self, path: str, password: str = "") -> None:
        try:
            data = Path(path).read_bytes()
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise PdfError(f"无法打开 PDF：{exc}") from exc

        if not doc.is_pdf:
            doc.close()
            raise PdfError("所选文件不是有效的 PDF。")
        if doc.needs_pass and (not password or not doc.authenticate(password)):
            doc.close()
            raise PasswordRequired("此 PDF 需要密码，或输入的密码不正确。")

        self.close()
        self.doc = doc
        self.source_path = str(Path(path).resolve())
        self.saved_path = self.source_path
        self.modified = False

    def _require_doc(self) -> pymupdf.Document:
        if not self.is_open:
            raise PdfError("请先打开一个 PDF 文件。")
        assert self.doc is not None
        return self.doc

    def _bytes(self) -> bytes:
        doc = self._require_doc()
        return doc.tobytes(garbage=3, deflate=True)

    def _checkpoint(self, label: str) -> None:
        self._undo.append((self._bytes(), label))
        if len(self._undo) > self.MAX_HISTORY:
            del self._undo[0]
        self._redo.clear()

    def _restore(self, data: bytes) -> None:
        if self.doc and not self.doc.is_closed:
            self.doc.close()
        self.doc = pymupdf.open(stream=data, filetype="pdf")
        self.modified = True

    def _refresh_document(self) -> None:
        """Reopen edited bytes so MuPDF drops stale page/font resource caches."""
        data = self._bytes()
        if self.doc and not self.doc.is_closed:
            self.doc.close()
        self.doc = pymupdf.open(stream=data, filetype="pdf")

    def undo(self) -> str | None:
        if not self._undo:
            return None
        data, label = self._undo.pop()
        self._redo.append((self._bytes(), label))
        self._restore(data)
        return label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        data, label = self._redo.pop()
        self._undo.append((self._bytes(), label))
        self._restore(data)
        return label

    def page_size(self, page_index: int) -> tuple[float, float]:
        rect = self._require_doc().load_page(page_index).rect
        return rect.width, rect.height

    def render_page(
        self, page_index: int, scale: float, *, annotations: bool = True
    ) -> tuple[bytes, int, int, int]:
        page = self._require_doc().load_page(page_index)
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            alpha=False,
            annots=annotations,
        )
        return pix.samples, pix.width, pix.height, pix.stride

    def render_thumbnail(self, page_index: int, max_width: int = 132) -> tuple[bytes, int, int, int]:
        page = self._require_doc().load_page(page_index)
        scale = min(1.0, max_width / max(page.rect.width, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
        return pix.samples, pix.width, pix.height, pix.stride

    def text_spans(self, page_index: int) -> list[TextSpan]:
        page = self._require_doc().load_page(page_index)
        underlines: list[pymupdf.Rect] = []
        for annot in page.annots() or ():
            if (
                annot.type[0] == pymupdf.PDF_ANNOT_UNDERLINE
                and annot.info.get("subject") == f"{APP_NAME} underline"
            ):
                underlines.append(pymupdf.Rect(annot.rect))
        blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT).get("blocks", [])
        spans: list[TextSpan] = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for raw in line.get("spans", []):
                    text = raw.get("text", "")
                    bbox = raw.get("bbox")
                    origin = raw.get("origin")
                    if not text or not bbox or not origin:
                        continue
                    rgb = pymupdf.sRGB_to_rgb(int(raw.get("color", 0)))
                    span = TextSpan(
                            bbox=tuple(float(v) for v in bbox),
                            origin=tuple(float(v) for v in origin),
                            text=text,
                            font=str(raw.get("font", "")),
                            size=float(raw.get("size", 11)),
                            color=tuple(channel / 255 for channel in rgb),
                            flags=int(raw.get("flags", 0)),
                        )
                    if any(rect.intersects(pymupdf.Rect(span.bbox)) for rect in underlines):
                        span = replace(span, underline=True)
                    spans.append(span)
        return spans

    def form_fields(self, page_index: int) -> list[FormField]:
        page = self._require_doc().load_page(page_index)
        fields: list[FormField] = []
        for widget in page.widgets() or ():
            flags = int(widget.field_flags or 0)
            field_type = int(widget.field_type or pymupdf.PDF_WIDGET_TYPE_UNKNOWN)
            value = widget.field_value
            if value is None or value is False:
                value = "Off" if field_type in (
                    pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                ) else ""
            on_value = None
            if field_type in (
                pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
            ):
                try:
                    on_value = str(widget.on_state())
                except Exception:
                    on_value = "Yes"
            rect = pymupdf.Rect(widget.rect)
            choices = tuple(str(item) for item in (widget.choice_values or ()))
            fields.append(
                FormField(
                    page_index=page_index,
                    xref=int(widget.xref),
                    name=str(widget.field_name or f"field-{widget.xref}"),
                    label=str(widget.field_label or widget.field_name or "表单字段"),
                    field_type=field_type,
                    field_type_string=str(widget.field_type_string or "Unknown"),
                    value=str(value),
                    choices=choices,
                    rect=(rect.x0, rect.y0, rect.x1, rect.y1),
                    read_only=bool(flags & pymupdf.PDF_FIELD_IS_READ_ONLY),
                    multiline=bool(flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE),
                    password=bool(flags & pymupdf.PDF_TX_FIELD_IS_PASSWORD),
                    max_length=max(0, int(widget.text_maxlen or 0)),
                    on_value=on_value,
                )
            )
        return fields

    @property
    def form_field_count(self) -> int:
        if not self.is_open:
            return 0
        return sum(len(self.form_fields(index)) for index in range(self.page_count))

    def set_form_field(self, field: FormField, value: str) -> None:
        if field.read_only:
            raise PdfError("这个表单字段是只读的。")
        doc = self._require_doc()
        page = doc.load_page(field.page_index)
        widget = page.load_widget(field.xref)
        if widget is None or str(widget.field_name or "") != field.name:
            widget = next(
                (item for item in page.widgets() or () if item.field_name == field.name),
                None,
            )
        if widget is None:
            raise PdfError("找不到这个表单字段，请重新打开 PDF 后再试。")
        current = str(widget.field_value or "")
        if current == str(value):
            return
        self._checkpoint("填写表单")
        widget.field_value = str(value)
        widget.update()
        self.modified = True
        self._refresh_document()

    def reorder_pages(self, order: Iterable[int]) -> None:
        order_list = list(order)
        doc = self._require_doc()
        if order_list == list(range(doc.page_count)):
            return
        if sorted(order_list) != list(range(doc.page_count)):
            raise PdfError("页面顺序无效，请重新尝试。")
        self._checkpoint("重新排列页面")
        doc.select(order_list)
        self.modified = True

    def delete_pages(self, page_indices: Iterable[int]) -> None:
        indices = sorted(set(int(i) for i in page_indices))
        doc = self._require_doc()
        if not indices:
            return
        if indices[0] < 0 or indices[-1] >= doc.page_count:
            raise PdfError("要删除的页码无效。")
        if len(indices) == doc.page_count:
            raise PdfError("PDF 至少需要保留一页。")
        self._checkpoint("删除页面")
        doc.delete_pages(indices)
        self.modified = True

    def insert_pdf(
        self,
        source_path: str,
        insert_at: int,
        from_page: int = 0,
        to_page: int | None = None,
        password: str = "",
    ) -> int:
        doc = self._require_doc()
        try:
            source = pymupdf.open(source_path)
        except Exception as exc:
            raise PdfError(f"无法打开要插入的 PDF：{exc}") from exc
        try:
            if not source.is_pdf:
                raise PdfError("要插入的文件不是有效的 PDF。")
            if source.needs_pass and (not password or not source.authenticate(password)):
                raise PasswordRequired("要插入的 PDF 需要密码，或密码不正确。")
            if source.page_count == 0:
                raise PdfError("要插入的 PDF 没有页面。")
            last = source.page_count - 1 if to_page is None else to_page
            if from_page < 0 or last < from_page or last >= source.page_count:
                raise PdfError("插入页码范围无效。")
            insert_at = max(0, min(insert_at, doc.page_count))
            self._checkpoint("插入 PDF")
            doc.insert_pdf(source, from_page=from_page, to_page=last, start_at=insert_at)
            self.modified = True
            return last - from_page + 1
        finally:
            source.close()

    def rotate_pages(self, page_indices: Iterable[int], degrees: int) -> None:
        indices = sorted(set(int(i) for i in page_indices))
        doc = self._require_doc()
        if not indices:
            return
        self._checkpoint("旋转页面")
        for index in indices:
            page = doc.load_page(index)
            page.set_rotation((page.rotation + degrees) % 360)
        self.modified = True

    @staticmethod
    def _install_font(page: pymupdf.Page, font: FontChoice) -> str:
        if not font.file_path:
            return font.pdf_name
        if not _font_allows_editable_embedding(font.file_path):
            raise PdfError(
                "所选字体的许可不允许嵌入可继续编辑的 PDF，请换用其他字体。"
            )
        digest = hashlib.sha1(font.file_path.lower().encode("utf-8")).hexdigest()[:10]
        base_name = f"PHF{digest}"
        fonts = page.get_fonts(full=True)
        by_name = {str(item[4]).lstrip("/"): item for item in fonts if len(item) > 4}
        candidate = base_name
        suffix = 1
        while candidate in by_name:
            xref = int(by_name[candidate][0])
            object_type = page.parent.xref_get_key(xref, "Type")
            if object_type == ("name", "/Font"):
                break
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        if candidate not in by_name:
            page.insert_font(fontname=candidate, fontfile=font.file_path)
        return candidate

    @staticmethod
    def _insert_lines(
        page: pymupdf.Page,
        point: tuple[float, float],
        text: str,
        font: FontChoice,
        font_size: float,
        color: tuple[float, float, float],
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        if any(ord(character) > 255 for character in text) and not font.file_path:
            unicode_font = next(
                (choice for choice in available_fonts() if choice.file_path), None
            )
            if unicode_font is None:
                raise PdfError("当前系统未找到可写入中文的字体，请选择一个中文字体。")
            font = unicode_font
        font, synthetic_bold, synthetic_italic = PdfDocumentModel._styled_font(
            font, bold, italic
        )
        font_name = PdfDocumentModel._install_font(page, font)
        try:
            metrics_font = (
                pymupdf.Font(fontfile=font.file_path)
                if font.file_path
                else pymupdf.Font(fontname=font.pdf_name)
            )
        except Exception:
            metrics_font = pymupdf.Font(fontname="helv")
        x, y = point
        line_height = max(font_size * 1.25, 5)
        for offset, line in enumerate(text.splitlines() or [""]):
            if not line:
                continue
            baseline = y + offset * line_height
            insert_point = pymupdf.Point(x, baseline)
            morph = None
            if synthetic_italic:
                morph = (insert_point, pymupdf.Matrix(1, 0, -0.22, 1, 0, 0))
            render_mode = 2 if synthetic_bold else 0
            page.insert_text(
                insert_point,
                line,
                fontname=font_name,
                fontsize=font_size,
                color=color,
                fill=color,
                render_mode=render_mode,
                border_width=max(0.1, font_size * 0.008) if synthetic_bold else 0.05,
                morph=morph,
                overlay=True,
            )
            if underline:
                width = metrics_font.text_length(line, fontsize=font_size)
                quad_rect = pymupdf.Rect(
                    x,
                    baseline - font_size * 0.9,
                    x + max(width, 1),
                    baseline + font_size * 0.2,
                )
                annot = page.add_underline_annot(quad_rect.quad)
                annot.set_colors(stroke=color)
                annot.set_info(subject=f"{APP_NAME} underline")
                annot.update(opacity=1)

    @staticmethod
    def _styled_font(
        font: FontChoice, bold: bool, italic: bool
    ) -> tuple[FontChoice, bool, bool]:
        label = font.label.lower()
        if label.startswith("helvetica"):
            choice = {
                (False, False): FontChoice("Helvetica", "helv"),
                (True, False): FontChoice("Helvetica Bold", "hebo"),
                (False, True): FontChoice("Helvetica Oblique", "heit"),
                (True, True): FontChoice("Helvetica Bold Oblique", "hebi"),
            }[(bold, italic)]
            return choice, False, False
        if label.startswith("times"):
            choice = {
                (False, False): FontChoice("Times Roman", "tiro"),
                (True, False): FontChoice("Times Bold", "tibo"),
                (False, True): FontChoice("Times Italic", "tiit"),
                (True, True): FontChoice("Times Bold Italic", "tibi"),
            }[(bold, italic)]
            return choice, False, False
        if label.startswith("courier"):
            choice = {
                (False, False): FontChoice("Courier", "cour"),
                (True, False): FontChoice("Courier Bold", "cobo"),
                (False, True): FontChoice("Courier Oblique", "coit"),
                (True, True): FontChoice("Courier Bold Oblique", "cobi"),
            }[(bold, italic)]
            return choice, False, False

        if font.file_path:
            path = Path(font.file_path)
            windows = path.parent
            stem = path.stem.lower()
            variant: Path | None = None
            if stem == "arial":
                variant = windows / {
                    (False, False): "arial.ttf",
                    (True, False): "arialbd.ttf",
                    (False, True): "ariali.ttf",
                    (True, True): "arialbi.ttf",
                }[(bold, italic)]
            elif stem == "msyh" and bold:
                variant = windows / "msyhbd.ttc"
            if variant and variant.exists():
                return FontChoice(font.label, font.pdf_name, str(variant)), False, (
                    italic and stem != "arial"
                )
            return font, bold, italic
        return font, bold, italic

    def replace_text(
        self,
        page_index: int,
        span: TextSpan,
        replacement: str,
        font: FontChoice,
        font_size: float,
        color: tuple[float, float, float],
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        doc = self._require_doc()
        self._checkpoint("编辑文字")
        page = doc.load_page(page_index)
        self._erase_span(page, span)
        if replacement:
            self._insert_lines(
                page, span.origin, replacement, font, font_size, color, bold, italic, underline
            )
        self.modified = True
        self._refresh_document()

    @staticmethod
    def _erase_span(page: pymupdf.Page, span: TextSpan) -> None:
        for annot in list(page.annots() or ()):
            if (
                annot.type[0] == pymupdf.PDF_ANNOT_UNDERLINE
                and annot.info.get("subject") == f"{APP_NAME} underline"
                and pymupdf.Rect(annot.rect).intersects(pymupdf.Rect(span.bbox))
            ):
                page.delete_annot(annot)
        rect = pymupdf.Rect(span.bbox)
        # A tiny inset avoids touching adjacent CAD linework while covering font antialiasing.
        rect = pymupdf.Rect(rect.x0 - 0.35, rect.y0 - 0.35, rect.x1 + 0.35, rect.y1 + 0.35)
        rect &= page.rect
        page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

    def move_text(
        self,
        page_index: int,
        span: TextSpan,
        point: tuple[float, float],
        font: FontChoice,
        font_size: float,
        color: tuple[float, float, float],
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        dx = point[0] - span.origin[0]
        dy = point[1] - span.origin[1]
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            return
        doc = self._require_doc()
        page = doc.load_page(page_index)
        moved_rect = pymupdf.Rect(span.bbox) + (dx, dy, dx, dy)
        if not page.rect.contains(moved_rect):
            raise PdfError("文字不能移动到页面外。")
        self._checkpoint("移动文字")
        self._erase_span(page, span)
        self._insert_lines(
            page, point, span.text, font, font_size, color, bold, italic, underline
        )
        self.modified = True
        self._refresh_document()

    def add_text(
        self,
        page_index: int,
        point: tuple[float, float],
        text: str,
        font: FontChoice,
        font_size: float,
        color: tuple[float, float, float],
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        if not text:
            raise PdfError("请输入要添加的文字。")
        doc = self._require_doc()
        page = doc.load_page(page_index)
        if not page.rect.contains(pymupdf.Point(point)):
            raise PdfError("文字位置不在当前页面内。")
        self._checkpoint("添加文字")
        self._insert_lines(page, point, text, font, font_size, color, bold, italic, underline)
        self.modified = True

    def add_ink_stroke(
        self,
        page_index: int,
        points: Iterable[tuple[float, float]],
        color: tuple[float, float, float] = (0.03, 0.16, 0.38),
        width: float = 2.0,
    ) -> None:
        point_list = [(float(x), float(y)) for x, y in points]
        if not point_list:
            return
        if len(point_list) == 1:
            point_list.append((point_list[0][0] + 0.15, point_list[0][1] + 0.15))
        page = self._require_doc().load_page(page_index)
        if any(not page.rect.contains(pymupdf.Point(point)) for point in point_list):
            raise PdfError("签名笔迹不能画到页面外。")
        self._checkpoint("添加签名笔迹")
        annot = page.add_ink_annot([point_list])
        annot.set_colors(stroke=color)
        annot.set_border(width=max(0.5, min(float(width), 20.0)))
        annot.set_info(subject=f"{APP_NAME} signature ink")
        annot.update(opacity=1)
        self.modified = True

    def save_as(self, path: str) -> None:
        doc = self._require_doc()
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            handle, temp_path = tempfile.mkstemp(
                prefix=f".{target.stem}-",
                suffix=".pdf.tmp",
                dir=str(target.parent),
            )
            os.close(handle)
            doc.save(temp_path, garbage=4, deflate=True, clean=True)
            # Reopen before replacing the user's chosen output.
            check = pymupdf.open(temp_path)
            try:
                if not check.is_pdf or check.page_count != doc.page_count:
                    raise PdfError("导出校验失败：生成文件的页数不一致。")
            finally:
                check.close()
            os.replace(temp_path, target)
            temp_path = None
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError(f"导出 PDF 失败：{exc}") from exc
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        self.saved_path = str(target)
        self.modified = False
