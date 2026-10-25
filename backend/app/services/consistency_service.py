"""Keep the three stores in agreement: SQLite rows, original files and vectors.

Every document lives in three places. A crash, a file deleted by hand or a
delete interrupted halfway can make them disagree, and each disagreement shows
up differently in the app:

  orphan file      file in uploads/ with no row       -> wasted disk, invisible
  orphan vectors   vectors with no indexed row        -> search finds a ghost
  missing file     row whose original is gone         -> "Open file" fails
  vector mismatch  indexed row with wrong vector count -> search sees part of it

check() only reports. repair() fixes what is safe to fix automatically and
runs at startup, when no upload or delete can be in flight.
"""

import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.services import metadata_service, vector_service

logger = logging.getLogger("filemind")

# Only files the app itself wrote ({uuid}.{type}) are ever considered orphans.
_STORED_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(pdf|docx|txt)$")

MISSING_FILE_MESSAGE = "The original file is missing from storage. Delete this document and upload it again."
MISMATCH_MESSAGE = "Search data for this document was incomplete. Retry indexing."


@dataclass
class ConsistencyReport:
    documents: int = 0
    vectors: int = 0
    orphan_files: list[str] = field(default_factory=list)
    orphan_vectors: dict[str, int] = field(default_factory=dict)
    missing_files: list[str] = field(default_factory=list)
    vector_mismatches: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (
            self.orphan_files or self.orphan_vectors or self.missing_files or self.vector_mismatches
        )


def check() -> ConsistencyReport:
    records = {record.file_id: record for record in metadata_service.list_documents()}
    vector_counts = vector_service.vector_counts_by_file()
    report = ConsistencyReport(documents=len(records), vectors=sum(vector_counts.values()))

    stored_names = {record.stored_name for record in records.values()}
    for path in sorted(settings.uploads_dir.iterdir()):
        if path.is_file() and _STORED_NAME.match(path.name) and path.name not in stored_names:
            report.orphan_files.append(path.name)

    for file_id, count in vector_counts.items():
        record = records.get(file_id)
        # 'processing' documents are being written right now; leave them alone.
        if record is None or record.status in ("pending", "failed"):
            report.orphan_vectors[file_id] = count

    for record in records.values():
        if not (settings.uploads_dir / record.stored_name).is_file():
            report.missing_files.append(record.file_id)
        elif record.status == "indexed":
            stored = vector_counts.get(record.file_id, 0)
            if stored != record.chunk_count:
                report.vector_mismatches[record.file_id] = {
                    "expected": record.chunk_count or 0,
                    "stored": stored,
                }

    return report


def repair() -> ConsistencyReport:
    """Fix every problem check() finds. Returns what was found before fixing."""
    report = check()

    for name in report.orphan_files:
        (settings.uploads_dir / name).unlink(missing_ok=True)
    for file_id in report.orphan_vectors:
        vector_service.delete_file_vectors(file_id)
    for file_id in report.missing_files:
        vector_service.delete_file_vectors(file_id)
        metadata_service.update_status(file_id, "failed", MISSING_FILE_MESSAGE)
    for file_id in report.vector_mismatches:
        # Partial vectors would make search see only part of the document.
        vector_service.delete_file_vectors(file_id)
        metadata_service.update_status(file_id, "failed", MISMATCH_MESSAGE)

    if not report.ok:
        logger.warning(
            "Consistency repair: %d orphan file(s), %d orphan vector set(s), "
            "%d missing original(s), %d vector mismatch(es)",
            len(report.orphan_files),
            len(report.orphan_vectors),
            len(report.missing_files),
            len(report.vector_mismatches),
        )
    return report
