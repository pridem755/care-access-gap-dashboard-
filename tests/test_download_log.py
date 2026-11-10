"""Tests for scripts.download_log. All files live in pytest's tmp_path."""
import hashlib
import re

import pytest

from scripts import config, download_log

SOURCE = config.SOURCES["acs_s2701"]


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "download_log.csv"


@pytest.fixture
def raw_file(tmp_path):
    path = tmp_path / "acs_s2701_2020-2024_20261110.json"
    path.write_bytes(b'[["NAME","GEO_ID"],["Accomack County, Virginia","0500000US51001"]]')
    return path


def test_sha256_matches_hashlib(raw_file):
    assert download_log.sha256_of(raw_file) == hashlib.sha256(raw_file.read_bytes()).hexdigest()


def test_utc_timestamp_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", download_log.utc_now())


def test_build_entry_describes_the_file(raw_file):
    entry = download_log.build_entry(SOURCE, raw_file, "https://api.census.gov/x", row_count=1)
    assert entry.source == "acs_s2701"
    assert entry.file_name == raw_file.name
    assert entry.version == "2020-2024"
    assert entry.row_count == 1
    assert entry.file_size_bytes == raw_file.stat().st_size


def test_build_entry_redacts_the_api_key(raw_file):
    entry = download_log.build_entry(SOURCE, raw_file, "https://api.census.gov/x?key=SECRET", 1)
    assert "SECRET" not in entry.url


def test_manual_file_is_logged_as_manual(raw_file):
    assert download_log.build_entry(SOURCE, raw_file, None, 1).url == "manual"


def test_append_then_read_round_trips(raw_file, log_path):
    first = download_log.build_entry(SOURCE, raw_file, "https://a", 1)
    second = download_log.build_entry(SOURCE, raw_file, None, None)
    download_log.append(first, log_path)
    download_log.append(second, log_path)
    assert download_log.read_entries(log_path) == [first, second]
    assert log_path.read_text(encoding="utf-8").count("source,file_name") == 1


def test_read_missing_log_returns_empty_list(log_path):
    assert download_log.read_entries(log_path) == []


def test_read_rejects_unexpected_columns(log_path):
    log_path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(download_log.DownloadLogError):
        download_log.read_entries(log_path)


def test_latest_entry_returns_most_recent(raw_file, log_path):
    download_log.append(download_log.build_entry(SOURCE, raw_file, "https://old", 1), log_path)
    download_log.append(download_log.build_entry(SOURCE, raw_file, "https://new", 1), log_path)
    assert download_log.latest_entry(raw_file.name, log_path).url == "https://new"


def test_skip_when_file_matches_its_logged_checksum(raw_file, log_path):
    download_log.append(download_log.build_entry(SOURCE, raw_file, "https://a", 1), log_path)
    assert download_log.is_already_downloaded(raw_file, log_path)


def test_no_skip_when_file_missing(tmp_path, log_path):
    assert not download_log.is_already_downloaded(tmp_path / "nope.csv", log_path)


def test_no_skip_when_file_not_logged(raw_file, log_path, caplog):
    assert not download_log.is_already_downloaded(raw_file, log_path)
    assert "not in the download log" in caplog.text


def test_no_skip_when_file_was_edited(raw_file, log_path, caplog):
    download_log.append(download_log.build_entry(SOURCE, raw_file, "https://a", 1), log_path)
    raw_file.write_bytes(b"edited")
    assert not download_log.is_already_downloaded(raw_file, log_path)
    assert "checksum" in caplog.text


def test_locked_log_gives_a_helpful_error(raw_file, log_path, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError
    monkeypatch.setattr(type(log_path), "open", locked)
    entry = download_log.Entry("s", "f", "u", "v", "t", 1, 1, "h")
    with pytest.raises(download_log.DownloadLogError, match="Excel"):
        download_log.append(entry, log_path)
