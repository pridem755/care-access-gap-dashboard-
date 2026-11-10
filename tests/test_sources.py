"""Tests for the PLACES, boundary, HRSA and RUCC source modules. HTTP is mocked."""
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from scripts import checks, config, download, http_client
from scripts.sources import cdc_places, fetch_file_from_url

HEADER = b'"stateabbr","locationid","measure"\n'
VA_FIPS = [f"51{i:03d}" for i in range(1, 134)]


RELEASE_TITLE = f"PLACES: Local Data for Better Health, County Data, {config.PLACES_RELEASE} release"


def response(content=b"", json_data=None, url="https://example.gov/x", content_type="text/csv"):
    r = MagicMock(spec=requests.Response)
    r.ok, r.status_code, r.history, r.url, r.content = True, 200, [], url, content
    r.headers = {"Content-Type": content_type}
    r.json.return_value = json_data
    return r


def places_session(rows, total=None, title=RELEASE_TITLE):
    """Fake Socrata: serves `rows` (list of CSV lines) in pages honouring $limit/$offset."""
    def get(url, params=None, timeout=None):
        if url == config.PLACES_METADATA_URL:
            return response(json_data={"name": title}, content_type="application/json")
        if url == config.PLACES_COUNT_URL:
            return response(json_data=[{"count": str(len(rows) if total is None else total)}])
        start, size = int(params["$offset"]), int(params["$limit"])
        return response(HEADER + b"".join(rows[start:start + size]))
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = get
    return session


def failed(results):
    return {r.name for r in results if not r.passed}


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(config, "PLACES_PAGE_SIZE", 2)


def test_places_pages_are_joined_with_one_header(small_pages):
    rows = [f'"VA","51{i:03d}","x"\n'.encode() for i in range(5)]
    session = places_session(rows)
    fetched = cdc_places.fetch(config.SOURCES["places"], session)
    assert fetched.content == HEADER + b"".join(rows)
    data_calls = [c for c in session.get.call_args_list if c.args[0] == config.PLACES_URL]
    offsets = [c.kwargs["params"]["$offset"] for c in data_calls]
    assert offsets == ["0", "2", "4"]


def test_places_pages_use_a_stable_order(small_pages):
    session = places_session([b'"VA","51001","x"\n'])
    cdc_places.fetch(config.SOURCES["places"], session)
    data_calls = [c for c in session.get.call_args_list if c.args[0] == config.PLACES_URL]
    assert all(c.kwargs["params"]["$order"] == ":id" for c in data_calls)


def test_places_exact_multiple_of_page_size_ends_with_empty_page(small_pages):
    rows = [f'"VA","51{i:03d}","x"\n'.encode() for i in range(4)]
    assert cdc_places.fetch(config.SOURCES["places"], places_session(rows)).content.count(b"\n") == 5


def test_places_truncated_download_raises(small_pages):
    rows = [b'"VA","51001","x"\n'] * 3
    with pytest.raises(http_client.DownloadError, match="incomplete: received 3 rows, dataset has 10"):
        cdc_places.fetch(config.SOURCES["places"], places_session(rows, total=10))


def test_places_wrong_release_is_refused_before_downloading(small_pages):
    session = places_session([b'"VA","51001","x"\n'], title="PLACES: County Data, 2026 release")
    with pytest.raises(http_client.DownloadError, match="not the 2025 release"):
        cdc_places.fetch(config.SOURCES["places"], session)
    assert all(c.args[0] != config.PLACES_URL for c in session.get.call_args_list)


def test_places_count_handles_line_breaks_inside_quotes():
    page = HEADER + b'"VA","51001","line one\nline two"\n"VA","51003","x"\n'
    assert cdc_places.count_records(page) == 2


def test_places_pages_with_different_headers_raise():
    with pytest.raises(http_client.DownloadError, match="different columns"):
        cdc_places.join_pages([HEADER + b'"VA","51001","x"\n', b'"other"\n"y"\n'])


def places_frame(drop=None):
    rows = [
        {"year": "2023", "stateabbr": "VA", "locationname": f"L{f}", "locationid": f,
         "measureid": m, "datavaluetypeid": t, "data_value": "10.1"}
        for f in VA_FIPS for m in config.PLACES_MEASURES for t in config.PLACES_VALUE_TYPES
        if (m, t) != drop
    ]
    rows.append({**rows[0], "stateabbr": "US", "locationid": "59"})
    return pd.DataFrame(rows)


def test_places_checks_pass_for_complete_virginia():
    assert failed(cdc_places.places_checks(places_frame())) == set()


def test_places_checks_fail_when_age_adjusted_is_missing():
    assert failed(cdc_places.places_checks(places_frame(drop=("DIABETES", "AgeAdjPrv")))) == {
        "DIABETES AgeAdjPrv: 133 unique locationid"
    }


def test_places_checks_report_missing_columns_without_crashing():
    results = cdc_places.places_checks(places_frame().drop(columns="measureid"))
    assert [r.name for r in results] == ["required columns present"] and not results[0].passed


def boundary_rows(n=133):
    return [["51", fips] for fips in VA_FIPS[:n]] + [["24", "24001"]]


def test_boundary_checks_pass_on_virginia_shapes(tmp_path, make_shapefile_zip):
    path = make_shapefile_zip(tmp_path / "b.zip", [("STATEFP", 2), ("GEOID", 5)], boundary_rows())
    assert failed(checks.run_checks("boundaries", path)) == set()


def test_boundary_checks_fail_on_missing_shape(tmp_path, make_shapefile_zip):
    path = make_shapefile_zip(tmp_path / "b.zip", [("STATEFP", 2), ("GEOID", 5)], boundary_rows(132))
    assert failed(checks.run_checks("boundaries", path)) == {"VA shapes: 133 unique GEOID"}


COL = config.HRSA_COLUMNS


def hrsa_frame(**overrides):
    rows = [{
        COL["site_id"]: f"BPS-{i}", COL["state"]: "VA", COL["county_fips"]: "51760",
        COL["status"]: "Active", COL["site_type"]: "Service Delivery Site",
        COL["location_type"]: "Permanent", COL["latitude"]: "37.54", COL["longitude"]: "-77.43",
    } for i in range(3)]
    rows[0].update(overrides)
    return pd.DataFrame(rows)


def test_hrsa_checks_pass():
    assert failed(checks.SOURCE_CHECKS["hrsa"](hrsa_frame())) == set()


def test_hrsa_duplicate_site_ids_are_counted_not_failed():
    results = {r.name: r for r in checks.SOURCE_CHECKS["hrsa"](hrsa_frame(**{COL["site_id"]: "BPS-1"}))}
    duplicates = results["VA duplicate site IDs counted"]
    assert duplicates.passed and duplicates.detail.startswith("1 duplicate rows")


@pytest.mark.parametrize("overrides, failing", [
    ({COL["status"]: "Closed"}, f"{COL['status']} has only documented values"),
    ({COL["county_fips"]: "5176"}, "VA county FIPS is a 5-digit FIPS"),
    ({COL["latitude"]: ""}, "VA sites have numeric coordinates"),
])
def test_hrsa_checks_catch_bad_rows(overrides, failing):
    assert failed(checks.SOURCE_CHECKS["hrsa"](hrsa_frame(**overrides))) == {failing}


def test_hrsa_checks_need_virginia_rows():
    assert "VA sites present" in failed(checks.SOURCE_CHECKS["hrsa"](hrsa_frame()[0:0]))


def rucc_frame(n=133, code="2"):
    rows = []
    for fips in VA_FIPS[:n]:
        rows += [
            {"FIPS": fips, "State": "VA", "County_Name": "X", "Attribute": "Population_2020", "Value": "100"},
            {"FIPS": fips, "State": "VA", "County_Name": "X", "Attribute": config.RUCC_ATTRIBUTE, "Value": code},
        ]
    return pd.DataFrame(rows)


def test_rucc_checks_pass_and_ignore_other_attributes():
    assert failed(checks.SOURCE_CHECKS["rucc"](rucc_frame())) == set()


def test_rucc_checks_catch_missing_locality_and_bad_code():
    assert failed(checks.SOURCE_CHECKS["rucc"](rucc_frame(n=132))) == {"VA RUCC_2023: 133 unique FIPS"}
    assert failed(checks.SOURCE_CHECKS["rucc"](rucc_frame(code="10"))) == {"Value has only documented values"}


def test_fetch_file_from_url_returns_bytes_as_received():
    session = MagicMock(spec=requests.Session)
    session.get.return_value = response(b"FIPS,State\n51001,VA\n", url=config.RUCC_URL)
    fetched = fetch_file_from_url.fetch(config.SOURCES["rucc"], session)
    assert fetched.content == b"FIPS,State\n51001,VA\n" and fetched.url == config.RUCC_URL


def test_every_source_has_a_fetcher_and_checks():
    assert set(download.FETCHERS) == set(config.SOURCES)
    assert set(checks.SOURCE_CHECKS) == set(config.SOURCES)


def test_failed_manual_capable_download_suggests_manual_file(tmp_path, monkeypatch):
    def blocked(source, session):
        raise http_client.DownloadError("HTTP 403 from ers.usda.gov.")
    monkeypatch.setitem(download.FETCHERS, "rucc", blocked)
    paths = download.Paths(raw_dir=tmp_path, log_path=tmp_path / "log.csv")
    outcome = download.download_source(config.SOURCES["rucc"], False, paths, date(2026, 11, 10))
    assert "--manual-file rucc <path>" in outcome.detail
