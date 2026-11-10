"""Tests for scripts.sources.census_acs. HTTP is mocked; no key is needed."""
import json
from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from scripts import checks, config, http_client
from scripts.sources import census_acs

SOURCE = config.SOURCES["acs_s2701"]
SECRET = "test-key-123"


def acs_rows(n=133, state="51", value="1234"):
    header = census_acs.requested_columns(SOURCE)
    n_values = len(header) - 4
    rows = [
        [f"County {i}, Virginia", f"0500000US51{i:03d}", *[value] * n_values, state, f"{i:03d}"]
        for i in range(1, n + 1)
    ]
    return [header, *rows]


def write_json(tmp_path, rows):
    path = tmp_path / SOURCE.filename(date(2026, 11, 10))
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def failed(results):
    return {r.name for r in results if not r.passed}


@pytest.fixture
def session():
    response = MagicMock(spec=requests.Response)
    response.ok, response.status_code, response.history = True, 200, []
    response.headers = {"Content-Type": "application/json;charset=utf-8"}
    response.content = b'[["NAME"]]'
    response.url = f"{SOURCE.url}?get=NAME&key={SECRET}"
    s = MagicMock(spec=requests.Session)
    s.get.return_value = response
    return s


def test_fetch_sends_key_and_geography(monkeypatch, session):
    monkeypatch.setenv(config.CENSUS_KEY_ENV, SECRET)
    census_acs.fetch(SOURCE, session)
    params = session.get.call_args.kwargs["params"]
    assert params["key"] == SECRET
    assert params["for"] == "county:*" and params["in"] == "state:51"


def test_fetch_returns_bytes_as_received_and_redacted_url(monkeypatch, session):
    monkeypatch.setenv(config.CENSUS_KEY_ENV, SECRET)
    fetched = census_acs.fetch(SOURCE, session)
    assert fetched.content == b'[["NAME"]]'
    assert SECRET not in fetched.url


def test_missing_key_fails_before_any_request(monkeypatch, session):
    monkeypatch.delenv(config.CENSUS_KEY_ENV, raising=False)
    with pytest.raises(http_client.ApiKeyError, match=config.CENSUS_KEY_ENV):
        census_acs.fetch(SOURCE, session)
    session.get.assert_not_called()


def test_blank_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv(config.CENSUS_KEY_ENV, "   ")
    with pytest.raises(http_client.ApiKeyError):
        census_acs.api_key()


def test_both_acs_sources_have_registered_checks():
    assert {"acs_s2701", "acs_s1701"} <= set(checks.SOURCE_CHECKS)


def test_good_file_passes_all_checks(tmp_path):
    results = checks.run_checks(SOURCE.name, write_json(tmp_path, acs_rows()))
    assert failed(results) == set()


def test_wrong_row_count_fails(tmp_path):
    results = checks.run_checks(SOURCE.name, write_json(tmp_path, acs_rows(n=132)))
    assert failed(results) == {"exactly 133 county rows", "localities: 133 unique fips"}


def test_duplicate_fips_with_133_rows_fails(tmp_path):
    rows = acs_rows()
    rows[-1] = rows[1]
    assert failed(checks.run_checks(SOURCE.name, write_json(tmp_path, rows))) == {"localities: 133 unique fips"}


def test_missing_geography_columns_still_report_row_count(tmp_path):
    rows = [r[:-2] for r in acs_rows()]
    results = {r.name: r for r in checks.run_checks(SOURCE.name, write_json(tmp_path, rows))}
    assert "state" in results["required columns present"].detail
    assert results["exactly 133 county rows"].passed


def test_missing_variable_fails(tmp_path):
    rows = acs_rows()
    rows[0][2] = "S2701_C99_001E"
    assert "required columns present" in failed(checks.run_checks(SOURCE.name, write_json(tmp_path, rows)))


def test_short_fips_fails(tmp_path):
    rows = acs_rows()
    rows[1][-1] = "1"
    assert "fips is a 5-digit FIPS" in failed(checks.run_checks(SOURCE.name, write_json(tmp_path, rows)))


def test_other_state_fails(tmp_path):
    results = checks.run_checks(SOURCE.name, write_json(tmp_path, acs_rows(state="24")))
    assert "all rows are state 51" in failed(results)


def test_documented_annotation_codes_pass_but_are_counted(tmp_path):
    results = checks.run_checks(SOURCE.name, write_json(tmp_path, acs_rows(value="-666666666.0")))
    result = next(r for r in results if r.name == "no undocumented negative or text values")
    assert result.passed and result.detail.startswith("798 documented")


def test_undocumented_negative_fails_the_download_check(tmp_path):
    results = checks.run_checks(SOURCE.name, write_json(tmp_path, acs_rows(value="-123")))
    assert "no undocumented negative or text values" in failed(results)
