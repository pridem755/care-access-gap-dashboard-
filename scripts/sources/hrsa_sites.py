"""HRSA Health Center Service Delivery and Look-Alike Sites (one row per site)."""
from __future__ import annotations

import pandas as pd

from scripts import checks, config
from scripts.checks import CheckResult
from scripts.sources import fetch_file_from_url

fetch = fetch_file_from_url.fetch
COL = config.HRSA_COLUMNS


def check_coordinates(va: pd.DataFrame) -> CheckResult:
    """Pass if every Virginia site has numeric latitude and longitude."""
    coords = va[[COL["latitude"], COL["longitude"]]].apply(pd.to_numeric, errors="coerce")
    bad = int(coords.isna().any(axis=1).sum())
    return CheckResult(f"{config.STATE_ABBR} sites have numeric coordinates", bad == 0,
                       f"{bad} sites without usable coordinates" if bad else "")


def report_duplicate_sites(va: pd.DataFrame) -> CheckResult:
    """Count duplicate site IDs; they are expected and removed during cleaning, so this passes."""
    dupes = int(va[COL["site_id"]].duplicated().sum())
    return CheckResult(f"{config.STATE_ABBR} duplicate site IDs counted", True,
                       f"{dupes} duplicate rows (removed during cleaning)" if dupes else "none")


def hrsa_checks(df: pd.DataFrame) -> list[CheckResult]:
    """Check columns, documented values, Virginia rows, FIPS and coordinates; count duplicates."""
    required = checks.expect_columns(df, COL.values())
    if not required.passed:
        return [required]
    va = df[df[COL["state"]] == config.STATE_ABBR]
    results = [required, checks.expect_any_rows(va, f"{config.STATE_ABBR} sites")]
    results += [
        checks.expect_values_in(df, COL[key], allowed)
        for key, allowed in config.HRSA_VALID_VALUES.items()
    ]
    results += [
        checks.expect_pattern(va, COL["county_fips"], config.FIPS_PATTERN,
                              f"{config.STATE_ABBR} county FIPS is a 5-digit FIPS"),
        report_duplicate_sites(va),
        check_coordinates(va),
    ]
    return results


checks.register("hrsa")(hrsa_checks)
