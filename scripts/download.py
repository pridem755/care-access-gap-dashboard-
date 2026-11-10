"""Command-line entry point: rebuild data/raw/ with `python -m scripts.download --all`."""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

import requests

from scripts import checks, config, download_log, http_client
from scripts.atomic_write import write_atomic
from scripts.config import Source
from scripts.sources import (
    Fetched,
    cdc_places,
    census_acs,
    census_boundaries,
    hrsa_sites,
    usda_rucc,
)

logger = logging.getLogger("scripts.download")
SECRET_IN_URL = re.compile(r"([?&]key=)[^&\s\"']+", re.IGNORECASE)

Fetcher = Callable[[Source, requests.Session | None], Fetched]
FETCHERS: dict[str, Fetcher] = {
    "acs_s2701": census_acs.fetch,
    "acs_s1701": census_acs.fetch,
    "places": cdc_places.fetch,
    "boundaries": census_boundaries.fetch,
    "hrsa": hrsa_sites.fetch,
    "rucc": usda_rucc.fetch,
}


class Status(str, Enum):
    """What happened to one source in this run."""

    DOWNLOADED = "downloaded"
    INGESTED = "ingested"
    SKIPPED = "up to date"
    NOT_RUN = "not run"
    CHECKS_FAILED = "checks failed"
    FAILED = "failed"


@dataclass(frozen=True)
class Outcome:
    """Result of processing one source."""

    source: str
    status: Status
    detail: str = ""


@dataclass(frozen=True)
class Paths:
    """Where raw files and the download log are written."""

    raw_dir: Path = field(default_factory=lambda: config.RAW_DIR)
    log_path: Path = field(default_factory=lambda: config.DOWNLOAD_LOG_PATH)


def today_utc() -> date:
    """Return today's date in UTC, used in raw file names."""
    return datetime.now(timezone.utc).date()


def supersede(path: Path, data: bytes) -> Path | None:
    """Move an existing file aside if `data` differs from it, so no raw version is lost."""
    if not path.exists() or download_log.sha256_of(path) == download_log.sha256_of_bytes(data):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.parent / config.SUPERSEDED_DIR_NAME / f"{stamp}_{path.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, target)
    logger.warning("%s had different content; kept the old copy as %s/%s",
                   path.name, config.SUPERSEDED_DIR_NAME, target.name)
    return target


def save(path: Path, data: bytes) -> None:
    """Keep any different existing copy, then write the new bytes atomically."""
    supersede(path, data)
    write_atomic(path, data)


def safe_row_count(path: Path) -> int | None:
    """Return the row count, or None if the file cannot be parsed."""
    try:
        return checks.count_rows(path)
    except Exception:
        return None


def recheck(source: Source, path: Path) -> Outcome:
    """Re-run checks on an unchanged file so a file that failed is never reported as up to date."""
    passed = checks.report(source.name, path, checks.run_checks(source.name, path))
    return Outcome(source.name, Status.SKIPPED if passed else Status.CHECKS_FAILED, path.name)


def record(source: Source, path: Path, url: str | None, paths: Paths, status: Status) -> Outcome:
    """Log a saved file, run its checks, and return the outcome."""
    entry = download_log.build_entry(source, path, url, safe_row_count(path))
    download_log.append(entry, paths.log_path)
    logger.info("Saved %s (%s bytes)", path.name, f"{entry.file_size_bytes:,}")
    passed = checks.report(source.name, path, checks.run_checks(source.name, path))
    return Outcome(source.name, status if passed else Status.CHECKS_FAILED, path.name)


def download_source(
    source: Source,
    force: bool,
    paths: Paths,
    today: date,
    session: requests.Session | None = None,
) -> Outcome:
    """Download one source unless today's copy is already logged and unchanged."""
    fetcher = FETCHERS.get(source.name)
    if fetcher is None:
        hint = f"use --manual-file {source.name} <path>" if source.manual_allowed else "not implemented yet"
        logger.warning("%s: no downloader; %s", source.name, hint)
        return Outcome(source.name, Status.NOT_RUN, hint)
    path = paths.raw_dir / source.filename(today)
    if not force and download_log.is_already_downloaded(path, paths.log_path):
        logger.info("%s: %s already downloaded today; re-checking (use --force to re-download)",
                    source.name, path.name)
        return recheck(source, path)
    logger.info("%s: downloading", source.name)
    try:
        fetched = fetcher(source, session)
    except http_client.ApiKeyError as exc:
        logger.warning("%s: %s", source.name, exc)
        return Outcome(source.name, Status.NOT_RUN, str(exc))
    except http_client.DownloadError as exc:
        message = str(exc)
        if source.manual_allowed:
            message += f" Download it in a browser and run: --manual-file {source.name} <path>"
        logger.error("%s: %s", source.name, message)
        return Outcome(source.name, Status.FAILED, message)
    save(path, fetched.content)
    return record(source, path, fetched.url, paths, Status.DOWNLOADED)


def ingest_manual(source: Source, file: Path, force: bool, paths: Paths, today: date) -> Outcome:
    """Copy a manually downloaded file into data/raw/ and log it as 'manual'."""
    problem = None
    if not source.manual_allowed:
        problem = f"{source.name} does not accept manual files"
    elif not file.is_file():
        problem = f"file not found: {file}"
    elif file.suffix.lower() != f".{source.extension}":
        problem = f"expected a .{source.extension} file, got {file.name}"
    if problem:
        logger.error("%s: %s", source.name, problem)
        return Outcome(source.name, Status.FAILED, problem)
    path = paths.raw_dir / source.filename(today)
    if path.exists() and not force:
        same = download_log.sha256_of(file) == download_log.sha256_of(path)
        if same and download_log.is_already_downloaded(path, paths.log_path):
            logger.info("%s: this file was already ingested today as %s", source.name, path.name)
            return recheck(source, path)
        if not same:
            problem = f"{path.name} already exists with different content; use --force to replace it"
            logger.error("%s: %s", source.name, problem)
            return Outcome(source.name, Status.FAILED, problem)
    save(path, file.read_bytes())
    return record(source, path, None, paths, Status.INGESTED)


def run_safely(name: str, step: Callable[[], Outcome]) -> Outcome:
    """Run one source's step, turning file-system errors into a failed outcome."""
    try:
        return step()
    except (OSError, download_log.DownloadLogError) as exc:
        logger.error("%s: %s", name, exc)
        return Outcome(name, Status.FAILED, str(exc))
    except Exception as exc:
        logger.exception("%s: unexpected error", name)
        return Outcome(name, Status.FAILED, f"unexpected {type(exc).__name__}: {exc}")


def group_names() -> list[str]:
    """Return prefixes shared by several sources, usable as --source shortcuts."""
    prefixes = [s.prefix for s in config.SOURCES.values()]
    return sorted({p for p in prefixes if prefixes.count(p) > 1})


def resolve_sources(names: Sequence[str]) -> list[Source]:
    """Expand source names and group shortcuts (e.g. 'acs') into Source objects."""
    chosen: dict[str, Source] = {}
    for name in names:
        for source in config.SOURCES.values():
            if name in (source.name, source.prefix):
                chosen[source.name] = source
    return list(chosen.values())


def summarize(outcomes: list[Outcome]) -> int:
    """Log one line per source; return 1 if anything failed, else 0."""
    logger.info("Summary:")
    for o in outcomes:
        level = logging.INFO if o.status in (Status.DOWNLOADED, Status.INGESTED, Status.SKIPPED) else logging.WARNING
        logger.log(level, "  %-12s %-14s %s", o.source, o.status.value, o.detail)
    return 1 if any(o.status in (Status.FAILED, Status.CHECKS_FAILED, Status.NOT_RUN) for o in outcomes) else 0


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line options."""
    choices = sorted(config.SOURCES) + group_names()
    parser = argparse.ArgumentParser(
        prog="python -m scripts.download",
        description="Download raw datasets into data/raw/ and record them in download_log.csv.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="download every source")
    mode.add_argument("--source", action="append", choices=choices, metavar="NAME",
                      help=f"download one source (repeatable): {', '.join(choices)}")
    mode.add_argument("--manual-file", nargs=2, metavar=("SOURCE", "PATH"),
                      help="copy a manually downloaded file into data/raw/ and log it")
    parser.add_argument("--force", action="store_true", help="re-download even if today's file is up to date")
    parser.add_argument("-v", "--verbose", action="store_true", help="show DEBUG messages")
    return parser


class RedactKeyFilter(logging.Filter):
    """Mask API keys in every log record, including those from third-party libraries."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the message with key=*** and keep the record."""
        record.msg, record.args = SECRET_IN_URL.sub(r"\1***", record.getMessage()), None
        return True


def configure_logging(verbose: bool) -> None:
    """Send log messages to the console, INFO level by default."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactKeyFilter())


def main(argv: Sequence[str] | None = None, paths: Paths | None = None) -> int:
    """Parse arguments, process the chosen sources, and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    paths = paths or Paths()
    today = today_utc()
    if args.manual_file:
        name, file = args.manual_file
        if name not in config.SOURCES:
            parser.error(f"unknown source {name!r}; choose from {', '.join(sorted(config.SOURCES))}")
        source = config.SOURCES[name]
        outcomes = [run_safely(name, lambda: ingest_manual(source, Path(file), args.force, paths, today))]
    else:
        sources = list(config.SOURCES.values()) if args.all else resolve_sources(args.source)
        session = http_client.build_session()
        outcomes = [
            run_safely(s.name, lambda s=s: download_source(s, args.force, paths, today, session))
            for s in sources
        ]
    return summarize(outcomes)


if __name__ == "__main__":
    sys.exit(main())
