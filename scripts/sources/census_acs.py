"""American Community Survey subject tables from the Census Data API."""
from __future__ import annotations

import os

import pandas as pd
import requests

from scripts import census_annotations, checks, config, http_client
from scripts.checks import CheckResult
from scripts.sources import Fetched

GEOGRAPHY_COLUMNS = ("state", "county")


def api_key() -> str:
    """Return the Census API key from the environment, or raise ApiKeyError."""
    key = os.environ.get(config.CENSUS_KEY_ENV, "").strip()
    if not key:
        raise http_client.ApiKeyError(
            f"{config.CENSUS_KEY_ENV} is not set; skipping ACS. "
            "Get a free key at https://api.census.gov/data/key_signup.html"
        )
    return key


def fetch(source: config.Source, session: requests.Session | None = None) -> Fetched:
    """Download one ACS table for all counties in the state, as raw JSON."""
    params = {**source.params, "key": api_key()}
    response = http_client.get(source.url, params, session)
    return Fetched(content=response.content, url=http_client.redact(response.url))


def requested_columns(source: config.Source) -> list[str]:
    """Return the columns the API should send back for this source."""
    return source.params["get"].split(",") + list(GEOGRAPHY_COLUMNS)


def check_state(df: pd.DataFrame) -> CheckResult:
    """Pass if every row belongs to the configured state."""
    other = sorted(set(df["state"]) - {config.STATE_FIPS})
    return CheckResult(f"all rows are state {config.STATE_FIPS}", not other, f"found {other}" if other else "")


def check_annotations(df: pd.DataFrame) -> CheckResult:
    """Report documented annotation codes; fail only on undocumented negatives or text."""
    summary = census_annotations.summarize_annotations(df, census_annotations.acs_value_columns(df))
    unexpected = summary[["other_negatives", "non_numeric"]]
    unexpected = unexpected[unexpected.sum(axis=1) > 0]
    detail = f"{int(summary['annotation_codes'].sum())} documented annotation codes (missing after cleaning)"
    if not unexpected.empty:
        detail += f"; unexpected: {unexpected.to_dict('index')}"
    return CheckResult("no undocumented negative or text values", unexpected.empty, detail)


def acs_checks(source: config.Source) -> checks.SourceCheck:
    """Build the check function for one ACS source."""
    def run(df: pd.DataFrame) -> list[CheckResult]:
        required = checks.expect_columns(df, requested_columns(source))
        if not required.passed:
            return [required, checks.expect_row_count(df, config.STATE_COUNTY_COUNT, "county rows")]
        fips = pd.DataFrame({"fips": df["state"] + df["county"]})
        return [
            required,
            checks.expect_row_count(df, config.STATE_COUNTY_COUNT, "county rows"),
            check_state(df),
            checks.expect_unique_count(fips, "fips", config.STATE_COUNTY_COUNT, "localities"),
            checks.expect_pattern(fips, "fips", config.FIPS_PATTERN, "fips is a 5-digit FIPS"),
            check_annotations(df),
        ]
    return run


for _source in config.SOURCES.values():
    if _source.prefix == "acs":
        checks.register(_source.name)(acs_checks(_source))
