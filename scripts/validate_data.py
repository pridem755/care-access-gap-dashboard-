"""Command-line entry point: check data/processed/ with `python -m scripts.validate_data`."""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts import config, download_log
from scripts.checks import CheckResult, report
from scripts.download import configure_logging
from scripts.validation import markdown_report, output_checks
from scripts.validation.processed_files import expected_columns, read_as_text, table_path

logger = logging.getLogger("scripts.validate_data")


def missing_files(processed_dir: Path) -> list[str]:
    """Return the names of expected tables that have no file."""
    return [name for name in expected_columns() if not table_path(processed_dir, name).exists()]


def file_details(processed_dir: Path) -> list[tuple[str, int, str]]:
    """Return (file name, size, sha256) for every processed table."""
    paths = [table_path(processed_dir, name) for name in expected_columns()]
    return [(p.name, p.stat().st_size, download_log.sha256_of(p)) for p in paths]


Results = dict[str, list[CheckResult]]


def validate(processed_dir: Path) -> tuple[Results, list[tuple[str, str, int, int]], list[tuple[str, int, str]]]:
    """Return check results, missing-value counts and file details for the processed tables."""
    absent = missing_files(processed_dir)
    if absent:
        return {"files": [CheckResult("all processed tables exist", False, f"missing {absent}")]}, [], []
    tables = {name: read_as_text(table_path(processed_dir, name)) for name in expected_columns()}
    results = {"files": [CheckResult("all processed tables exist", True, f"{len(tables)} tables")]}
    results.update(output_checks.run_all(tables))
    return results, output_checks.missing_values(tables), file_details(processed_dir)


def main(
    argv: Sequence[str] | None = None,
    processed_dir: Path = config.PROCESSED_DIR,
    report_path: Path = config.VALIDATION_REPORT_PATH,
) -> int:
    """Validate the processed tables, update the report, and return 1 if any check failed."""
    parser = argparse.ArgumentParser(prog="python -m scripts.validate_data", description=__doc__)
    parser.add_argument("--no-report", action="store_true", help="do not update docs/validation_report.md")
    parser.add_argument("-v", "--verbose", action="store_true", help="show DEBUG messages")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    results, missing, files = validate(processed_dir)
    passed = all([
        report(table, processed_dir if table == "files" else table_path(processed_dir, table), rs)
        for table, rs in results.items()
    ])
    if not args.no_report:
        section = markdown_report.render(download_log.utc_now(), files, results, missing)
        markdown_report.update(report_path, section)
        logger.info("Updated %s", report_path.name)
    logger.info("Validation %s", "PASSED" if passed else "FAILED: do not load these files into Power BI")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
