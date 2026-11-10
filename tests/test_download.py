"""Tests for scripts.download. Fetchers are faked; files live in tmp_path."""
from datetime import date

import pytest

from scripts import checks, config, download, download_log, http_client
from scripts.download import Status
from scripts.sources import Fetched

TODAY = date(2026, 11, 10)
CSV_BYTES = b"fips,value\n51001,10\n51003,20\n"
DEMO = config.Source(
    name="demo", prefix="demo", content="data", version="1",
    extension="csv", url="https://example.gov/demo.csv", manual_allowed=True,
)


@pytest.fixture
def paths(tmp_path):
    return download.Paths(raw_dir=tmp_path / "raw", log_path=tmp_path / "raw" / "download_log.csv")


@pytest.fixture
def fetcher(monkeypatch):
    """Install a fake fetcher for DEMO and count its calls."""
    calls = []

    def fake(source, session):
        calls.append(source.name)
        return Fetched(content=CSV_BYTES, url="https://example.gov/demo.csv?key=***")

    monkeypatch.setitem(download.FETCHERS, "demo", fake)
    return calls


@pytest.fixture
def demo_registered(monkeypatch):
    monkeypatch.setitem(config.SOURCES, "demo", DEMO)


def raw_path(paths):
    return paths.raw_dir / DEMO.filename(TODAY)


def test_write_atomic_leaves_no_part_file(tmp_path):
    target = tmp_path / "a" / "file.csv"
    download.write_atomic(target, b"data")
    assert target.read_bytes() == b"data"
    assert list(target.parent.iterdir()) == [target]


def test_write_atomic_keeps_old_file_if_write_fails(tmp_path, monkeypatch):
    target = tmp_path / "file.csv"
    target.write_bytes(b"old")
    def disk_full(*args):
        raise OSError("disk full")
    monkeypatch.setattr(download.os, "replace", disk_full)
    with pytest.raises(OSError):
        download.write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert not (tmp_path / "file.csv.part").exists()


def test_download_saves_bytes_exactly_and_logs(paths, fetcher):
    outcome = download.download_source(DEMO, False, paths, TODAY)
    assert outcome.status is Status.DOWNLOADED
    assert raw_path(paths).read_bytes() == CSV_BYTES
    entry = download_log.latest_entry(raw_path(paths).name, paths.log_path)
    assert entry.row_count == 2
    assert entry.url.endswith("key=***")


def test_second_run_skips_and_force_redownloads(paths, fetcher):
    download.download_source(DEMO, False, paths, TODAY)
    assert download.download_source(DEMO, False, paths, TODAY).status is Status.SKIPPED
    assert download.download_source(DEMO, True, paths, TODAY).status is Status.DOWNLOADED
    assert fetcher == ["demo", "demo"]
    assert len(download_log.read_entries(paths.log_path)) == 2


def test_edited_file_is_downloaded_again(paths, fetcher):
    download.download_source(DEMO, False, paths, TODAY)
    raw_path(paths).write_bytes(b"edited by hand")
    assert download.download_source(DEMO, False, paths, TODAY).status is Status.DOWNLOADED
    assert raw_path(paths).read_bytes() == CSV_BYTES


def test_failed_checks_keep_the_file_and_are_reported(paths, fetcher, monkeypatch):
    monkeypatch.setitem(checks.SOURCE_CHECKS, "demo", lambda df: [checks.expect_row_count(df, 133)])
    outcome = download.download_source(DEMO, False, paths, TODAY)
    assert outcome.status is Status.CHECKS_FAILED
    assert raw_path(paths).exists()


def test_missing_api_key_is_not_run_and_writes_nothing(paths, monkeypatch):
    def no_key(source, session):
        raise http_client.ApiKeyError("CENSUS_API_KEY is not set")
    monkeypatch.setitem(download.FETCHERS, "demo", no_key)
    outcome = download.download_source(DEMO, False, paths, TODAY)
    assert outcome.status is Status.NOT_RUN
    assert not paths.log_path.exists()


def test_http_failure_is_failed(paths, monkeypatch):
    def broken(source, session):
        raise http_client.DownloadError("HTTP 404")
    monkeypatch.setitem(download.FETCHERS, "demo", broken)
    assert download.download_source(DEMO, False, paths, TODAY).status is Status.FAILED


def test_source_without_fetcher_suggests_manual_file(paths):
    outcome = download.download_source(DEMO, False, paths, TODAY)
    assert outcome.status is Status.NOT_RUN
    assert "--manual-file demo" in outcome.detail


def test_manual_file_is_copied_exactly_and_logged_as_manual(paths, tmp_path):
    incoming = tmp_path / "Downloaded From Website.csv"
    incoming.write_bytes(CSV_BYTES)
    outcome = download.ingest_manual(DEMO, incoming, False, paths, TODAY)
    assert outcome.status is Status.INGESTED
    assert raw_path(paths).read_bytes() == CSV_BYTES
    assert download_log.latest_entry(raw_path(paths).name, paths.log_path).url == "manual"


def test_same_manual_file_twice_is_skipped(paths, tmp_path):
    incoming = tmp_path / "x.csv"
    incoming.write_bytes(CSV_BYTES)
    download.ingest_manual(DEMO, incoming, False, paths, TODAY)
    assert download.ingest_manual(DEMO, incoming, False, paths, TODAY).status is Status.SKIPPED


def test_different_manual_file_same_day_needs_force(paths, tmp_path):
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_bytes(CSV_BYTES)
    second.write_bytes(CSV_BYTES + b"51005,30\n")
    download.ingest_manual(DEMO, first, False, paths, TODAY)
    assert download.ingest_manual(DEMO, second, False, paths, TODAY).status is Status.FAILED
    assert download.ingest_manual(DEMO, second, True, paths, TODAY).status is Status.INGESTED
    assert raw_path(paths).read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    "setup, message",
    [
        (lambda p: p.write_bytes(b"x"), "expected a .csv file"),
        (lambda p: None, "file not found"),
    ],
)
def test_manual_file_problems(paths, tmp_path, setup, message):
    incoming = tmp_path / ("wrong.xlsx" if "expected" in message else "missing.csv")
    setup(incoming)
    outcome = download.ingest_manual(DEMO, incoming, False, paths, TODAY)
    assert outcome.status is Status.FAILED and message in outcome.detail


def test_manual_file_rejected_for_api_sources(paths, tmp_path):
    incoming = tmp_path / "x.json"
    incoming.write_bytes(b"[]")
    outcome = download.ingest_manual(config.SOURCES["acs_s2701"], incoming, False, paths, TODAY)
    assert "does not accept manual files" in outcome.detail


def test_group_shortcut_expands_to_both_acs_tables():
    assert [s.name for s in download.resolve_sources(["acs"])] == ["acs_s2701", "acs_s1701"]


def test_cli_requires_a_mode():
    with pytest.raises(SystemExit):
        download.build_parser().parse_args([])


def test_cli_rejects_unknown_source():
    with pytest.raises(SystemExit):
        download.build_parser().parse_args(["--source", "nope"])


def test_cli_end_to_end_exit_codes(paths, fetcher, demo_registered, monkeypatch):
    monkeypatch.setattr(download, "today_utc", lambda: TODAY)
    assert download.main(["--source", "demo"], paths) == 0
    monkeypatch.setitem(checks.SOURCE_CHECKS, "demo", lambda df: [checks.expect_row_count(df, 133)])
    assert download.main(["--source", "demo", "--force"], paths) == 1


def test_cli_manual_file(paths, tmp_path, demo_registered, monkeypatch):
    monkeypatch.setattr(download, "today_utc", lambda: TODAY)
    incoming = tmp_path / "x.csv"
    incoming.write_bytes(CSV_BYTES)
    assert download.main(["--manual-file", "demo", str(incoming)], paths) == 0
    assert raw_path(paths).exists()


def test_one_failing_source_does_not_stop_the_others(paths, fetcher, demo_registered, monkeypatch):
    def broken(source, session):
        raise http_client.DownloadError("HTTP 500")
    monkeypatch.setitem(download.FETCHERS, "acs_s2701", broken)
    monkeypatch.setattr(download, "today_utc", lambda: TODAY)
    assert download.main(["--source", "acs_s2701", "--source", "demo"], paths) == 1
    assert raw_path(paths).exists()
