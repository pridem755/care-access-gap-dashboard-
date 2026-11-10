"""Append-only record of every raw file the pipeline has saved."""
from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from scripts import config
from scripts.http_client import redact

logger = logging.getLogger(__name__)

MANUAL = "manual"
CHUNK_BYTES = 1024 * 1024


class DownloadLogError(Exception):
    """The download log could not be read or written."""


@dataclass(frozen=True)
class Entry:
    """One line of the download log."""

    source: str
    file_name: str
    url: str
    version: str
    downloaded_at_utc: str
    row_count: int | None
    file_size_bytes: int
    sha256: str


COLUMNS = [f.name for f in fields(Entry)]


def sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of bytes, matching sha256_of for the same content."""
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string, e.g. 2026-11-10T14:03:22Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_entry(
    source: config.Source,
    path: Path,
    url: str | None,
    row_count: int | None,
) -> Entry:
    """Describe a saved raw file; url=None marks a manually supplied file."""
    return Entry(
        source=source.name,
        file_name=path.name,
        url=redact(url) if url else MANUAL,
        version=source.version,
        downloaded_at_utc=utc_now(),
        row_count=row_count,
        file_size_bytes=path.stat().st_size,
        sha256=sha256_of(path),
    )


def append(entry: Entry, log_path: Path = config.DOWNLOAD_LOG_PATH) -> None:
    """Add one entry to the log, writing the header if the log is new."""
    is_new = not log_path.exists() or log_path.stat().st_size == 0
    row = {k: ("" if v is None else v) for k, v in asdict(entry).items()}
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except PermissionError as exc:
        raise DownloadLogError(
            f"Cannot write {log_path.name}. Is it open in Excel? Close it and re-run."
        ) from exc
    logger.info("Logged %s (%s rows, sha256 %s...)", entry.file_name, entry.row_count, entry.sha256[:12])


def parse_row(row: dict[str, str]) -> Entry:
    """Convert one CSV row back into an Entry."""
    return Entry(
        source=row["source"],
        file_name=row["file_name"],
        url=row["url"],
        version=row["version"],
        downloaded_at_utc=row["downloaded_at_utc"],
        row_count=int(row["row_count"]) if row["row_count"] else None,
        file_size_bytes=int(row["file_size_bytes"]),
        sha256=row["sha256"],
    )


def read_entries(log_path: Path = config.DOWNLOAD_LOG_PATH) -> list[Entry]:
    """Return all entries in the order they were written."""
    if not log_path.exists():
        return []
    with log_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise DownloadLogError(f"{log_path.name} has unexpected columns: {reader.fieldnames}")
        return [parse_row(row) for row in reader]


def latest_entry(file_name: str, log_path: Path = config.DOWNLOAD_LOG_PATH) -> Entry | None:
    """Return the most recent entry for a file name, if any."""
    matches = [e for e in read_entries(log_path) if e.file_name == file_name]
    return matches[-1] if matches else None


def is_already_downloaded(path: Path, log_path: Path = config.DOWNLOAD_LOG_PATH) -> bool:
    """Return True if the file exists and matches its logged checksum."""
    if not path.exists():
        return False
    entry = latest_entry(path.name, log_path)
    if entry is None:
        logger.warning("%s exists but is not in the download log; downloading again.", path.name)
        return False
    if sha256_of(path) != entry.sha256:
        logger.warning("%s does not match its logged checksum (edited?); downloading again.", path.name)
        return False
    return True
