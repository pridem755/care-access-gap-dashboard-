"""USDA ERS Rural-Urban Continuum Codes (long format: one row per county and attribute)."""
from __future__ import annotations

import pandas as pd

from scripts import checks, config
from scripts.checks import CheckResult
from scripts.sources import fetch_file_from_url

fetch = fetch_file_from_url.fetch


def rucc_checks(df: pd.DataFrame) -> list[CheckResult]:
    """Check that every Virginia locality has exactly one valid RUCC code."""
    required = checks.expect_columns(df, config.RUCC_COLUMNS)
    if not required.passed:
        return [required]
    codes = df[(df["State"] == config.STATE_ABBR) & (df["Attribute"] == config.RUCC_ATTRIBUTE)]
    return [
        required,
        checks.expect_unique_count(codes, "FIPS", config.STATE_COUNTY_COUNT,
                                   f"{config.STATE_ABBR} {config.RUCC_ATTRIBUTE}"),
        checks.expect_pattern(codes, "FIPS", config.FIPS_PATTERN, f"{config.STATE_ABBR} FIPS is a 5-digit FIPS"),
        checks.expect_values_in(codes, "Value", config.RUCC_VALID_CODES),
    ]


checks.register("rucc")(rucc_checks)
