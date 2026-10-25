"""Upload validation: filename, extension, size and actual file structure.

Never trust the extension alone: a renamed .exe called "contract.pdf" must be
rejected because its bytes do not look like a PDF.
"""

import io
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath, PureWindowsPath

from app.core.config import settings
from app.core.errors import ApiError

ALLOWED_TYPES = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}

# Guards against "zip bombs": tiny .docx files that expand to gigabytes.
MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def sanitize_filename(raw: str | None) -> str:
    """Return a display-safe filename. It is never used as a filesystem path."""
    name = raw or ""
    # Drop any directory part a client might send, e.g. "..\\..\\evil.txt".
    name = PureWindowsPath(PurePosixPath(name).name).name
    name = unicodedata.normalize("NFKC", name)
    name = _FORBIDDEN_CHARS.sub("_", name)
    name = name.strip().strip(".")
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = f"{stem[: 200 - len(ext) - 1]}.{ext}" if dot else name[:200]
    return name or "document"


def file_type_for(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise ApiError(
            415,
            "unsupported_file_type",
            f"Unsupported file type '{suffix or 'none'}'. Allowed: PDF, DOCX, TXT.",
        )
    return ALLOWED_TYPES[suffix]


def validate_upload(filename: str, data: bytes) -> str:
    """Validate an upload and return its file type ('pdf', 'docx' or 'txt')."""
    file_type = file_type_for(filename)

    if not data:
        raise ApiError(400, "empty_file", "The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise ApiError(413, "file_too_large", _too_large_message())

    if file_type == "pdf":
        _check_pdf(data)
    elif file_type == "docx":
        _check_docx(data)
    else:
        _check_txt(data)
    return file_type


def _too_large_message() -> str:
    return f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit."


def _check_pdf(data: bytes) -> None:
    # The PDF header must appear near the start of the file.
    if b"%PDF-" not in data[:1024]:
        raise ApiError(400, "invalid_file_content", "File does not look like a valid PDF.")


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        raise ApiError(400, "invalid_file_content", "File does not look like a valid DOCX.")
    if "word/document.xml" not in names or "[Content_Types].xml" not in names:
        raise ApiError(400, "invalid_file_content", "File does not look like a valid DOCX.")
    if total > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise ApiError(400, "invalid_file_content", "DOCX expands to an unsafe size.")


def _check_txt(data: bytes) -> None:
    has_utf16_bom = data.startswith((b"\xff\xfe", b"\xfe\xff"))
    # NUL bytes almost always mean a binary file renamed to .txt.
    if not has_utf16_bom and b"\x00" in data[:8192]:
        raise ApiError(400, "invalid_file_content", "File looks like binary data, not text.")
