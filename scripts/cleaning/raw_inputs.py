"""Find the newest logged raw file for a source, verify it, and load it as text columns."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from scripts import checks, config, download_log
from scripts.cleaning import CleaningError
from scripts.sources import cdc_places, census_acs, census_boundaries, hrsa_sites, usda_rucc  # noqa: F401

logger = logging.getLogger(__name__)


def latest_entry(source_name: str, log_path: Path) -> download_log.Entry:
    """Return the newest download-log entry for a source."""
    entries = [e for e in download_log.read_entries(log_path) if e.source == source_name]
    if not entries:
        raise CleaningError(
            f"no {source_name} download in {log_path.name}; run: python -m scripts.download --source {source_name}"
        )
    return entries[-1]


def load_input(
    source_name: str,
    raw_dir: Path = config.RAW_DIR,
    log_path: Path = config.DOWNLOAD_LOG_PATH,
) -> pd.DataFrame:
    """Load the newest raw file for a source if it exists, is unchanged and passes its checks."""
    entry = latest_entry(source_name, log_path)
    path = raw_dir / entry.file_name
    if not path.exists():
        raise CleaningError(f"{entry.file_name} is in the download log but not in {raw_dir.name}/; re-download it")
    if download_log.sha256_of(path) != entry.sha256:
        raise CleaningError(f"{entry.file_name} changed after it was downloaded; re-download it with --force")
    failed = [r for r in checks.run_checks(source_name, path) if not r.passed]
    if failed:
        details = "; ".join(f"{r.name} ({r.detail})" for r in failed)
        raise CleaningError(f"{entry.file_name} fails its download checks: {details}")
    logger.info("Input  %-11s %s (sha256 %s...)", source_name, entry.file_name, entry.sha256[:12])
    return checks.load_table(path)
