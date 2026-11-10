"""Tests for scripts.checks, using small files written to tmp_path."""
import json

import pandas as pd
import pytest

from scripts import checks


def write_census_json(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


FIELDS = [("STATEFP", 2), ("GEOID", 5), ("NAME", 20)]


@pytest.fixture
def write_shapefile_zip(make_shapefile_zip):
    def write(path, records=133, parts=(".shp", ".shx", ".dbf", ".prj")):
        rows = [["51", f"51{i:03d}", f"Place {i}"] for i in range(records)]
        return make_shapefile_zip(path, FIELDS, rows, parts)
    return write


@pytest.fixture
def census_json(tmp_path):
    return write_census_json(
        tmp_path / "acs.json",
        [["NAME", "state", "county"], ["Accomack County, Virginia", "51", "001"]],
    )


def by_name(results):
    return {r.name: r for r in results}


def test_census_json_keeps_leading_zeros(census_json):
    df = checks.read_census_json(census_json)
    assert df.loc[0, "county"] == "001"


def test_census_json_rejects_other_shapes(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"error": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError):
        checks.read_census_json(path)


def test_csv_keeps_leading_zeros_and_blank_cells(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("fips,value\n01001,\n", encoding="utf-8")
    df, encoding = checks.read_csv(path)
    assert df.loc[0, "fips"] == "01001"
    assert df.loc[0, "value"] == ""
    assert encoding == "utf-8-sig"


def test_csv_falls_back_to_windows_encoding(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes("name\nDoña Ana\n".encode("cp1252"))
    df, encoding = checks.read_csv(path)
    assert df.loc[0, "name"] == "Doña Ana"
    assert encoding == "cp1252"


def test_xlsx_is_read_as_text(tmp_path):
    path = tmp_path / "x.xlsx"
    pd.DataFrame({"FIPS": ["51001"]}).to_excel(path, index=False)
    assert checks.read_xlsx(path).loc[0, "FIPS"] == "51001"


def test_count_rows_for_table_and_zip(census_json, tmp_path, write_shapefile_zip):
    assert checks.count_rows(census_json) == 1
    assert checks.count_rows(write_shapefile_zip(tmp_path / "b.zip", records=3235)) == 3235


def test_empty_file_fails_and_stops(tmp_path):
    path = tmp_path / "empty.csv"
    path.touch()
    results = checks.run_checks("places", path)
    assert [r.passed for r in results] == [False]


def test_unparseable_file_fails(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("<html>Missing Key</html>", encoding="utf-8")
    results = by_name(checks.run_checks("acs_s2701", path))
    assert not results["parses as JSON"].passed


def test_good_table_passes_file_checks(census_json):
    assert all(r.passed for r in checks.run_checks("unregistered", census_json))


def test_header_only_table_fails_data_rows_check(tmp_path):
    path = write_census_json(tmp_path / "a.json", [["NAME"]])
    assert not by_name(checks.run_checks("x", path))["has data rows"].passed


def test_complete_shapefile_zip_passes(tmp_path, write_shapefile_zip):
    results = checks.run_checks("boundaries", write_shapefile_zip(tmp_path / "b.zip"))
    assert all(r.passed for r in results)


@pytest.mark.parametrize("missing", [".dbf", ".prj"])
def test_zip_missing_a_shapefile_part_fails(tmp_path, write_shapefile_zip, missing):
    parts = tuple(p for p in (".shp", ".shx", ".dbf", ".prj") if p != missing)
    result = by_name(checks.run_checks("boundaries", write_shapefile_zip(tmp_path / "b.zip", parts=parts)))
    assert not result["ZIP holds .shp/.shx/.dbf/.prj"].passed and missing in result["ZIP holds .shp/.shx/.dbf/.prj"].detail


def test_html_after_byte_order_mark_fails(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes(b"\xef\xbb\xbf<!DOCTYPE html><html>error</html>\n")
    assert not by_name(checks.run_checks("unregistered", path))["file is data, not an HTML page"].passed


def test_csv_with_byte_order_mark_is_still_data(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes(b"\xef\xbb\xbfFIPS,State\n51001,VA\n")
    assert by_name(checks.run_checks("unregistered", path))["file is data, not an HTML page"].passed


def test_row_count_ignores_deleted_shapefile_records(tmp_path, make_shapefile_zip):
    path = make_shapefile_zip(tmp_path / "b.zip", [("GEOID", 5)], [["51001"], ["51003"]], deleted={0})
    assert checks.dbf_record_count(path) == 2
    assert checks.count_rows(path) == 1 == len(checks.read_dbf(path))


def test_non_zip_with_zip_extension_fails(tmp_path):
    path = tmp_path / "b.zip"
    path.write_text("<html>404</html>")
    assert not by_name(checks.run_checks("boundaries", path))["parses as ZIP"].passed


def test_expect_columns_lists_missing_ones():
    result = checks.expect_columns(pd.DataFrame(columns=["a"]), ["a", "b"])
    assert not result.passed and "b" in result.detail


def test_expect_row_count():
    df = pd.DataFrame({"a": range(133)})
    assert checks.expect_row_count(df, 133).passed
    assert not checks.expect_row_count(df.head(5), 133).passed


@pytest.mark.parametrize("bad", ["5101", "51ABC", "24001", "510011", ""])
def test_expect_pattern_rejects_non_virginia_fips(bad):
    df = pd.DataFrame({"fips": ["51001", bad]})
    result = checks.expect_pattern(df, "fips", r"51\d{3}")
    assert not result.passed and "1 bad values" in result.detail


def test_expect_unique_count_catches_duplicates_hidden_by_row_count():
    fips = [f"51{i:03d}" for i in range(1, 133)] + ["51001"]
    result = checks.expect_unique_count(pd.DataFrame({"fips": fips}), "fips", 133)
    assert not result.passed and "133 rows, 132 unique" in result.detail


def test_expect_no_duplicates():
    assert checks.expect_no_duplicates(pd.DataFrame({"id": ["a", "b"]}), "id", "ids").passed
    result = checks.expect_no_duplicates(pd.DataFrame({"id": ["a", "a"]}), "id", "ids")
    assert not result.passed and "1 duplicate" in result.detail


def test_expect_values_in_lists_unexpected_values():
    result = checks.expect_values_in(pd.DataFrame({"s": ["Active", "Closed"]}), "s", ["Active"])
    assert not result.passed and "Closed" in result.detail


@pytest.mark.parametrize("helper", [
    lambda df: checks.expect_pattern(df, "x", r"\d"),
    lambda df: checks.expect_unique_count(df, "x", 1),
    lambda df: checks.expect_no_duplicates(df, "x", "x"),
    lambda df: checks.expect_values_in(df, "x", []),
])
def test_helpers_fail_instead_of_crashing_on_missing_column(helper):
    assert not helper(pd.DataFrame({"y": ["1"]})).passed


@pytest.mark.parametrize("start", [b"<!DOCTYPE html>", b"  \n<html lang='en'>", b"<HTML>"])
def test_html_page_saved_as_csv_fails(tmp_path, start):
    path = tmp_path / "places.csv"
    path.write_bytes(start + b"<body>Service unavailable</body></html>\n")
    assert not by_name(checks.run_checks("unregistered", path))["file is data, not an HTML page"].passed


def test_read_dbf_reads_attribute_rows(tmp_path, make_shapefile_zip):
    path = make_shapefile_zip(tmp_path / "b.zip", [("GEOID", 5), ("NAME", 12)],
                              [["51159", "Richmond"], ["51760", "Richmond"]])
    df = checks.read_dbf(path)
    assert df.to_dict("list") == {"GEOID": ["51159", "51760"], "NAME": ["Richmond", "Richmond"]}


def test_registered_source_checks_run(census_json, monkeypatch):
    monkeypatch.setitem(checks.SOURCE_CHECKS, "demo", lambda df: [checks.expect_row_count(df, 2)])
    assert not by_name(checks.run_checks("demo", census_json))["exactly 2 rows"].passed


def test_crashing_source_check_is_reported_not_raised(census_json, monkeypatch):
    monkeypatch.setitem(checks.SOURCE_CHECKS, "demo", lambda df: 1 / 0)
    results = checks.run_checks("demo", census_json)
    assert not results[-1].passed and "ZeroDivisionError" in results[-1].detail


def test_checks_never_modify_the_file(census_json):
    before = census_json.read_bytes()
    checks.run_checks("acs_s2701", census_json)
    assert census_json.read_bytes() == before


def test_report_logs_failures_loudly(census_json, caplog):
    results = [checks.CheckResult("ok", True), checks.CheckResult("bad", False, "why")]
    assert checks.report("demo", census_json, results) is False
    assert "CHECK FAILED [demo] bad: why" in caplog.text
    assert "1 of 2 checks FAILED" in caplog.text
