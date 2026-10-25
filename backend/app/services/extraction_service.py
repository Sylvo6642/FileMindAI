"""Text extraction for PDF, DOCX and TXT.

Each extractor turns a file into a list of TextSegments. A segment is a small
piece of text plus *where it came from* (page, paragraph or line). Keeping the
source reference from the very start is what later lets the assistant say
"page 3 of agreement_001.pdf" instead of just "somewhere in this file".
"""

import io
from dataclasses import dataclass, field

import docx
import pymupdf
from docx.table import Table
from docx.text.paragraph import Paragraph


class ExtractionError(Exception):
    """The file is structurally valid but no usable text could be extracted."""


@dataclass
class TextSegment:
    text: str
    page: int | None = None  # PDF, 1-based
    paragraph: int | None = None  # DOCX block number (paragraphs and tables), 1-based
    line: int | None = None  # TXT, 1-based
    section: str | None = None  # DOCX nearest heading


@dataclass
class ExtractionResult:
    segments: list[TextSegment]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(segment.text) for segment in self.segments)


def extract(data: bytes, file_type: str) -> ExtractionResult:
    extractors = {"pdf": extract_pdf, "docx": extract_docx, "txt": extract_txt}
    result = extractors[file_type](data)
    if not result.segments:
        raise ExtractionError("The file contains no extractable text.")
    return result


# ---------- PDF ----------


def extract_pdf(data: bytes) -> ExtractionResult:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ExtractionError("Could not read the PDF. The file may be corrupted.")

    with doc:
        if doc.needs_pass:
            raise ExtractionError("Password-protected PDFs are not supported.")

        segments: list[TextSegment] = []
        image_only_pages: list[int] = []
        for page_number, page in enumerate(doc, start=1):
            # "blocks" groups text into visual paragraphs; sort=True gives reading order.
            blocks = page.get_text("blocks", sort=True)
            texts = [b[4].strip() for b in blocks if b[6] == 0 and b[4].strip()]
            if texts:
                segments.extend(TextSegment(text=t, page=page_number) for t in texts)
            elif page.get_images():
                image_only_pages.append(page_number)
        page_count = doc.page_count

    if not segments:
        if image_only_pages:
            raise ExtractionError(
                "This PDF appears to be scanned or image-only. OCR is not supported yet."
            )
        raise ExtractionError("The PDF contains no selectable text.")

    warnings = []
    if image_only_pages:
        pages = ", ".join(map(str, image_only_pages))
        warnings.append(f"Pages {pages} contain only images; OCR is not supported, so they were skipped.")
    return ExtractionResult(segments=segments, page_count=page_count, warnings=warnings)


# ---------- DOCX ----------


def extract_docx(data: bytes) -> ExtractionResult:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception:
        raise ExtractionError("Could not read the DOCX. The file may be corrupted.")

    segments: list[TextSegment] = []
    section: str | None = None
    block_number = 0

    # iter_inner_content yields paragraphs and tables in document order.
    for block in document.iter_inner_content():
        block_number += 1
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if _is_heading(block):
                section = text
            segments.append(TextSegment(text=text, paragraph=block_number, section=section))
        elif isinstance(block, Table):
            for row_text in _table_rows(block):
                segments.append(TextSegment(text=row_text, paragraph=block_number, section=section))

    # python-docx cannot compute page numbers: pagination happens in Word's renderer.
    return ExtractionResult(segments=segments, page_count=None)


def _is_heading(paragraph: Paragraph) -> bool:
    try:
        name = paragraph.style.name if paragraph.style is not None else ""
    except Exception:
        return False
    return name.startswith("Heading") or name == "Title"


def _table_rows(table: Table) -> list[str]:
    rows = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            # Merged cells are repeated by python-docx; keep one copy.
            if text and (not cells or cells[-1] != text):
                cells.append(text)
        if cells:
            rows.append(" | ".join(cells))
    return rows


# ---------- TXT ----------


def extract_txt(data: bytes) -> ExtractionResult:
    text, warnings = _decode_text(data)
    segments = [
        TextSegment(text=line.strip(), line=number)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    return ExtractionResult(segments=segments, warnings=warnings)


def _decode_text(data: bytes) -> tuple[str, list[str]]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), []
    try:
        # utf-8-sig handles both plain UTF-8 and UTF-8 with a BOM.
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        text = data.decode("utf-8-sig", errors="replace")
        return text, ["Some characters were not valid UTF-8 and were replaced."]
