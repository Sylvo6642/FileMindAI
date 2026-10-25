import pytest

from app.core.config import settings
from app.core.errors import ApiError
from app.services.validation_service import sanitize_filename, validate_upload
from tests.sample_files import make_docx, make_pdf


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("contract.pdf", "contract.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\Windows\\evil.docx", "evil.docx"),
        ('bad<>:"|?*name.txt', "bad_______name.txt"),
        ("   ", "document"),
        (None, "document"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_but_keeps_extension():
    name = sanitize_filename("a" * 500 + ".pdf")
    assert len(name) <= 200
    assert name.endswith(".pdf")


def test_accepts_supported_types():
    assert validate_upload("a.pdf", make_pdf(["hello"])) == "pdf"
    assert validate_upload("a.docx", make_docx([("p", "hello")])) == "docx"
    assert validate_upload("a.TXT", b"hello") == "txt"


def _error_code(filename: str, data: bytes) -> tuple[int, str]:
    with pytest.raises(ApiError) as exc_info:
        validate_upload(filename, data)
    return exc_info.value.status_code, exc_info.value.code


def test_rejects_unsupported_extension():
    assert _error_code("virus.exe", b"MZ...") == (415, "unsupported_file_type")
    assert _error_code("noextension", b"hello") == (415, "unsupported_file_type")


def test_rejects_empty_file():
    assert _error_code("empty.txt", b"") == (400, "empty_file")


def test_rejects_too_large(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    assert _error_code("big.txt", b"x" * 11) == (413, "file_too_large")


def test_rejects_content_that_does_not_match_extension():
    assert _error_code("fake.pdf", b"this is plain text") == (400, "invalid_file_content")
    assert _error_code("fake.docx", b"this is plain text") == (400, "invalid_file_content")
    assert _error_code("fake.txt", b"MZ\x90\x00\x03\x00binary") == (400, "invalid_file_content")


def test_rejects_zip_that_is_not_a_docx():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.md", "just a zip")
    assert _error_code("x.docx", buffer.getvalue()) == (400, "invalid_file_content")
