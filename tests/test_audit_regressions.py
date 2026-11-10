"""Regression tests for the bugs found in the download audit."""
import logging
from datetime import date

import pytest

from scripts import config, download
from scripts.download import Status
from scripts.sources import Fetched

TODAY = date(2026, 11, 10)
HTML = b"<!DOCTYPE html><html><body>Down for maintenance</body></html>\n"
CSV = b"a,b\n1,2\n"


@pytest.fixture
def paths(tmp_path):
    return download.Paths(raw_dir=tmp_path / "raw", log_path=tmp_path / "raw" / "download_log.csv")


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(download, "today_utc", lambda: TODAY)


def serve(monkeypatch, name, content):
    monkeypatch.setitem(download.FETCHERS, name, lambda source, session: Fetched(content, "https://example.gov/f"))


def test_file_that_failed_checks_is_not_up_to_date_on_rerun(paths, monkeypatch):
    serve(monkeypatch, "hrsa", HTML)
    assert download.main(["--source", "hrsa"], paths) == 1
    assert download.main(["--source", "hrsa"], paths) == 1


def test_rerun_of_a_good_file_is_still_up_to_date(paths, monkeypatch):
    monkeypatch.setitem(download.checks.SOURCE_CHECKS, "hrsa", lambda df: [])
    serve(monkeypatch, "hrsa", CSV)
    assert download.main(["--source", "hrsa"], paths) == 0
    outcome = download.download_source(config.SOURCES["hrsa"], False, paths, TODAY)
    assert outcome.status is Status.SKIPPED


def test_verbose_logging_never_shows_the_api_key(monkeypatch):
    root, urllib3_logger = logging.getLogger(), logging.getLogger("urllib3")
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)
    monkeypatch.setattr(urllib3_logger, "level", logging.NOTSET)
    download.configure_logging(verbose=True)
    assert root.isEnabledFor(logging.DEBUG)
    assert not urllib3_logger.isEnabledFor(logging.DEBUG)


def test_key_filter_masks_keys_from_any_library():
    record = logging.LogRecord("urllib3.connectionpool", logging.DEBUG, "", 0,
                               '"GET /data?get=NAME&key=%s HTTP/1.1" 200', ("SECRET123",), None)
    assert download.RedactKeyFilter().filter(record)
    assert "SECRET123" not in record.getMessage() and "key=***" in record.getMessage()


def test_missing_api_key_makes_the_run_fail(paths, monkeypatch):
    monkeypatch.delenv(config.CENSUS_KEY_ENV, raising=False)
    assert download.main(["--source", "acs"], paths) == 1


def test_unexpected_error_in_one_source_does_not_stop_the_others(paths, monkeypatch):
    def shape_changed(source, session):
        return {}["count"]
    monkeypatch.setitem(download.FETCHERS, "places", shape_changed)
    monkeypatch.setitem(download.checks.SOURCE_CHECKS, "rucc", lambda df: [])
    serve(monkeypatch, "rucc", CSV)
    assert download.main(["--source", "places", "--source", "rucc"], paths) == 1
    assert (paths.raw_dir / config.SOURCES["rucc"].filename(TODAY)).exists()


def test_force_with_changed_content_keeps_the_old_raw_file(paths, monkeypatch):
    monkeypatch.setitem(download.checks.SOURCE_CHECKS, "rucc", lambda df: [])
    serve(monkeypatch, "rucc", b"x\n1\n")
    download.main(["--source", "rucc"], paths)
    serve(monkeypatch, "rucc", b"x\n2\n")
    download.main(["--source", "rucc", "--force"], paths)
    current = paths.raw_dir / config.SOURCES["rucc"].filename(TODAY)
    kept = list((paths.raw_dir / config.SUPERSEDED_DIR_NAME).iterdir())
    assert current.read_bytes() == b"x\n2\n"
    assert len(kept) == 1 and kept[0].read_bytes() == b"x\n1\n"
    assert kept[0].name.endswith(current.name)
    first, second = download.download_log.read_entries(paths.log_path)
    assert download.download_log.sha256_of(kept[0]) == first.sha256


def test_force_with_identical_content_keeps_no_extra_copy(paths, monkeypatch):
    monkeypatch.setitem(download.checks.SOURCE_CHECKS, "rucc", lambda df: [])
    serve(monkeypatch, "rucc", CSV)
    download.main(["--source", "rucc"], paths)
    download.main(["--source", "rucc", "--force"], paths)
    assert not (paths.raw_dir / config.SUPERSEDED_DIR_NAME).exists()


def test_manual_force_with_different_file_keeps_the_old_one(paths, tmp_path, monkeypatch):
    monkeypatch.setitem(download.checks.SOURCE_CHECKS, "hrsa", lambda df: [])
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_bytes(b"x\n1\n")
    second.write_bytes(b"x\n2\n")
    download.main(["--manual-file", "hrsa", str(first)], paths)
    download.main(["--manual-file", "hrsa", str(second), "--force"], paths)
    kept = list((paths.raw_dir / config.SUPERSEDED_DIR_NAME).iterdir())
    assert [k.read_bytes() for k in kept] == [b"x\n1\n"]
