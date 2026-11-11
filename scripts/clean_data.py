"""Command-line entry point: build data/processed/ with `python -m scripts.clean_data`."""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from scripts import config
from scripts.atomic_write import write_atomic
from scripts.cleaning import CleaningError, raw_inputs
from scripts.cleaning import build_acs_va, build_dim_geography, build_hrsa_supply, build_places_va
from scripts.download import configure_logging

logger = logging.getLogger("scripts.clean_data")


def load_inputs(raw_dir: Path, log_path: Path) -> dict[str, pd.DataFrame]:
    """Load and verify the newest raw file for every source."""
    return {name: raw_inputs.load_input(name, raw_dir, log_path) for name in config.SOURCES}


def build_tables(inputs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Build every output table in memory; raises CleaningError if any rule is broken."""
    dim = build_dim_geography.build(inputs["boundaries"], inputs["rucc"])
    localities = dim["fips"].tolist()
    sites = build_hrsa_supply.sites_table(inputs["hrsa"], localities)
    log_duplicates(sites)
    return {
        "dim_geography": dim,
        "acs_va": build_acs_va.build(inputs["acs_s2701"], inputs["acs_s1701"], localities),
        "places_va": build_places_va.build(inputs["places"], localities),
        "hrsa_sites_va": sites,
        "fact_supply": build_hrsa_supply.supply_table(sites, localities),
        "supply_duplicates": build_hrsa_supply.duplicates_table(sites),
    }


def log_duplicates(sites: pd.DataFrame) -> None:
    """Log how many counted site records were merged as duplicates."""
    summary = build_hrsa_supply.duplicate_summary(sites)
    for label, value in summary.items():
        logger.info("Supply duplicates: %s: %d", label, value)
    if not summary["duplicate site records merged"]:
        logger.info("Supply duplicates: 0 duplicate site records")


def write_tables(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    """Write each table as UTF-8 CSV, each through a temporary file."""
    for name, table in tables.items():
        write_atomic(out_dir / f"{name}.csv", table.to_csv(index=False, lineterminator="\n").encode("utf-8"))
        logger.info("Output %-14s %4d rows, %2d columns", f"{name}.csv", len(table), len(table.columns))


def main(
    argv: Sequence[str] | None = None,
    raw_dir: Path = config.RAW_DIR,
    log_path: Path = config.DOWNLOAD_LOG_PATH,
    out_dir: Path = config.PROCESSED_DIR,
) -> int:
    """Build all tables, then write them only if every one passed; return an exit code."""
    parser = argparse.ArgumentParser(prog="python -m scripts.clean_data", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="show DEBUG messages")
    configure_logging(parser.parse_args(argv).verbose)
    try:
        tables = build_tables(load_inputs(raw_dir, log_path))
    except CleaningError as exc:
        logger.error("Cleaning stopped: %s", exc)
        logger.error("Nothing in %s/ was changed.", out_dir.name)
        return 1
    write_tables(tables, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
