"""CDC PLACES county data from the Socrata API, downloaded page by page."""
from __future__ import annotations

import csv
import io
import logging

import pandas as pd
import requests

from scripts import checks, config, http_client
from scripts.checks import CheckResult
from scripts.sources import Fetched

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = (
    "year", "stateabbr", "locationname", "locationid",
    "measureid", "datavaluetypeid", "data_value",
)


def check_release(session: requests.Session) -> None:
    """Raise DownloadError unless the dataset's title names the configured release."""
    title = http_client.get(config.PLACES_METADATA_URL, session=session).json().get("name", "")
    if f"{config.PLACES_RELEASE} release" not in title:
        raise http_client.DownloadError(
            f"PLACES dataset {config.PLACES_DATASET_ID} is {title!r}, not the "
            f"{config.PLACES_RELEASE} release; update PLACES_DATASET_ID or PLACES_RELEASE in config.py"
        )


def expected_row_count(session: requests.Session) -> int:
    """Ask Socrata how many rows the dataset has."""
    response = http_client.get(config.PLACES_COUNT_URL, {"$select": "count(*)"}, session)
    return int(response.json()[0]["count"])


def page_params(offset: int) -> dict[str, str]:
    """Return query parameters for one page in a stable order."""
    return {
        "$order": config.PLACES_ORDER_BY,
        "$limit": str(config.PLACES_PAGE_SIZE),
        "$offset": str(offset),
    }


def count_records(page: bytes) -> int:
    """Count CSV data rows in one page, allowing for line breaks inside quotes."""
    return max(sum(1 for _ in csv.reader(io.StringIO(page.decode("utf-8")))) - 1, 0)


def split_header(page: bytes) -> tuple[bytes, bytes]:
    """Split a page into its header line and its data rows."""
    header, _, body = page.partition(b"\n")
    return header + b"\n", body


def join_pages(pages: list[bytes]) -> bytes:
    """Join CSV pages into one file, keeping the first header and checking the rest match."""
    header, body = split_header(pages[0])
    parts = [header, body]
    for number, page in enumerate(pages[1:], start=2):
        page_header, page_body = split_header(page)
        if page_header != header:
            raise http_client.DownloadError(f"PLACES page {number} has different columns than page 1")
        parts.append(page_body)
    return b"".join(p if p.endswith(b"\n") or not p else p + b"\n" for p in parts)


def fetch(source: config.Source, session: requests.Session | None = None) -> Fetched:
    """Download every row, page by page, and verify none were cut off."""
    session = session or http_client.build_session()
    check_release(session)
    expected = expected_row_count(session)
    pages, received = [], 0
    while True:
        page = http_client.get(source.url, page_params(received), session).content
        rows = count_records(page)
        pages.append(page)
        received += rows
        logger.info("places: %s of %s rows", f"{received:,}", f"{expected:,}")
        if rows < config.PLACES_PAGE_SIZE or received > expected:
            break
    if received != expected:
        raise http_client.DownloadError(
            f"PLACES download incomplete: received {received:,} rows, dataset has {expected:,}"
        )
    logger.info("places: all %s rows received in %d pages", f"{received:,}", len(pages))
    url = f"{source.url}?$order={config.PLACES_ORDER_BY}&$limit={config.PLACES_PAGE_SIZE}"
    return Fetched(content=join_pages(pages), url=url)


def places_checks(df: pd.DataFrame) -> list[CheckResult]:
    """Check that Virginia has both measures, both value types, for every locality."""
    required = checks.expect_columns(df, REQUIRED_COLUMNS)
    if not required.passed:
        return [required]
    va = df[df["stateabbr"] == config.STATE_ABBR]
    results = [required, checks.expect_any_rows(va, f"{config.STATE_ABBR} rows")]
    for measure in config.PLACES_MEASURES:
        for value_type in config.PLACES_VALUE_TYPES:
            subset = va[(va["measureid"] == measure) & (va["datavaluetypeid"] == value_type)]
            results.append(checks.expect_unique_count(
                subset, "locationid", config.STATE_COUNTY_COUNT, f"{measure} {value_type}"
            ))
    results.append(checks.expect_pattern(
        va, "locationid", config.FIPS_PATTERN, f"{config.STATE_ABBR} locationid is a 5-digit FIPS"
    ))
    return results


checks.register("places")(places_checks)
