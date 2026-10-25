import pytest

from app.services.extraction_service import ExtractionError, extract
from tests.sample_files import (
    make_corrupt_docx,
    make_docx,
    make_encrypted_pdf,
    make_image_only_pdf,
    make_mixed_pdf,
    make_pdf,
)

# ---------- PDF ----------


def test_pdf_preserves_page_numbers_and_skips_empty_pages():
    result = extract(make_pdf(["Alpha agreement.", "", "Payment terms."]), "pdf")

    assert result.page_count == 3
    assert [(s.page, s.text) for s in result.segments] == [
        (1, "Alpha agreement."),
        (3, "Payment terms."),
    ]


def test_pdf_image_only_is_reported_as_scanned():
    with pytest.raises(ExtractionError, match="scanned or image-only"):
        extract(make_image_only_pdf(), "pdf")


def test_pdf_with_some_image_only_pages_warns():
    result = extract(make_mixed_pdf(), "pdf")
    assert [s.page for s in result.segments] == [1]
    assert "Pages 2" in result.warnings[0]


def test_pdf_corrupted():
    with pytest.raises(ExtractionError, match="corrupted"):
        extract(b"%PDF-1.7 this is not really a pdf", "pdf")


def test_pdf_password_protected():
    with pytest.raises(ExtractionError, match="Password-protected"):
        extract(make_encrypted_pdf(), "pdf")


# ---------- DOCX ----------


def test_docx_keeps_order_of_paragraphs_and_tables_with_sections():
    data = make_docx(
        [
            ("h", "Payment Terms"),
            ("p", "Fees are due annually."),
            ("t", [["Item", "Fee"], ["Support", "50000"]]),
            ("h", "Termination"),
            ("p", "Either party may terminate."),
        ]
    )
    result = extract(data, "docx")

    assert [(s.paragraph, s.section, s.text) for s in result.segments] == [
        (1, "Payment Terms", "Payment Terms"),
        (2, "Payment Terms", "Fees are due annually."),
        (3, "Payment Terms", "Item | Fee"),
        (3, "Payment Terms", "Support | 50000"),
        (4, "Termination", "Termination"),
        (5, "Termination", "Either party may terminate."),
    ]
    assert result.page_count is None  # never invented for DOCX


def test_docx_corrupted():
    with pytest.raises(ExtractionError, match="corrupted"):
        extract(make_corrupt_docx(), "docx")


def test_docx_without_text():
    with pytest.raises(ExtractionError, match="no extractable text"):
        extract(make_docx([("p", "   ")]), "docx")


# ---------- TXT ----------


def test_txt_preserves_line_numbers():
    result = extract(b"first line\n\nthird line\n", "txt")
    assert [(s.line, s.text) for s in result.segments] == [(1, "first line"), (3, "third line")]


def test_txt_utf8_with_bom_and_unicode():
    result = extract("﻿Payment of ₹50,000".encode("utf-8"), "txt")
    assert result.segments[0].text == "Payment of ₹50,000"
    assert result.warnings == []


def test_txt_utf16_from_windows_notepad():
    result = extract("Unicode notes".encode("utf-16"), "txt")
    assert result.segments[0].text == "Unicode notes"


def test_txt_invalid_utf8_is_replaced_with_warning():
    result = extract(b"caf\xe9 menu", "txt")
    assert result.segments[0].text == "caf� menu"
    assert "not valid UTF-8" in result.warnings[0]


def test_txt_empty_or_whitespace_only():
    with pytest.raises(ExtractionError, match="no extractable text"):
        extract(b"  \n\n \t\n", "txt")
