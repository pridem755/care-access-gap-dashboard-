"""The expected columns of every processed table, and reading the files back as text."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import config

DIM_COLUMNS = [
    "fips", "locality_name", "locality_type", "metro_status",
    "rucc_code", "rucc_description", "population_2020", "land_area_sq_mi",
]
FACT_SUPPLY_COLUMNS = ["fips", "supply_sites", "active_sites_any_type"]


def acs_columns() -> list[str]:
    """Return fips plus value, _moe and _cv for every ACS variable in config."""
    names = [*config.ACS_S2701_VARIABLES.values(), *config.ACS_S1701_VARIABLES.values()]
    return ["fips"] + [f"{n}{suffix}" for n in names for suffix in ("", "_moe", "_cv")]


def places_columns() -> list[str]:
    """Return fips plus value, confidence limits and data year for every PLACES measure."""
    suffixes = ("_pct", "_ci_low", "_ci_high", "_data_year")
    return ["fips"] + [f"{n}{s}" for n in config.PLACES_MEASURES.values() for s in suffixes]


def site_columns() -> list[str]:
    """Return the columns of hrsa_sites_va."""
    return [*config.HRSA_SITE_FIELDS.values(), "fips_matched", "in_supply_measure"]


def expected_columns() -> dict[str, list[str]]:
    """Return the expected column list for every processed table."""
    return {
        "dim_geography": DIM_COLUMNS,
        "acs_va": acs_columns(),
        "places_va": places_columns(),
        config.SITE_TABLE: site_columns(),
        "fact_supply": FACT_SUPPLY_COLUMNS,
    }


def table_path(processed_dir: Path, name: str) -> Path:
    """Return the CSV path for a processed table."""
    return processed_dir / f"{name}.csv"


def read_as_text(path: Path) -> pd.DataFrame:
    """Read a processed CSV with every cell as text, exactly as written."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
