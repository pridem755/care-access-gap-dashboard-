"""Census cartographic boundary file of US counties (1:500k shapefile ZIP)."""
from __future__ import annotations

import pandas as pd

from scripts import checks, config
from scripts.checks import CheckResult
from scripts.sources import fetch_file_from_url

fetch = fetch_file_from_url.fetch


def boundary_checks(df: pd.DataFrame) -> list[CheckResult]:
    """Check that the attribute table has every Virginia locality exactly once."""
    required = checks.expect_columns(df, (config.BOUNDARY_STATE_COLUMN, config.BOUNDARY_FIPS_COLUMN))
    if not required.passed:
        return [required]
    va = df[df[config.BOUNDARY_STATE_COLUMN] == config.STATE_FIPS]
    return [
        required,
        checks.expect_unique_count(
            va, config.BOUNDARY_FIPS_COLUMN, config.STATE_COUNTY_COUNT, f"{config.STATE_ABBR} shapes"
        ),
        checks.expect_pattern(
            va, config.BOUNDARY_FIPS_COLUMN, config.FIPS_PATTERN, f"{config.STATE_ABBR} GEOID is a 5-digit FIPS"
        ),
    ]


checks.register("boundaries")(boundary_checks)
