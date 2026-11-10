"""Tests for scripts.config."""
import re
from datetime import date

import pytest

from scripts import config

FILENAME_PATTERN = re.compile(r"^[a-z]+_[a-z0-9]+_[a-z0-9-]+_\d{8}\.(csv|json|zip|xlsx)$")


def test_with_moe_pairs_each_estimate_with_its_margin():
    assert config.with_moe(("S2701_C01_001E",)) == ("S2701_C01_001E", "S2701_C01_001M")


def test_with_moe_rejects_non_estimate_codes():
    with pytest.raises(ValueError):
        config.with_moe(("S2701_C01_001M",))


def test_acs_params_request_ids_estimates_and_moes_for_virginia_counties():
    params = config.SOURCES["acs_s2701"].params
    fields = params["get"].split(",")
    assert fields[:2] == ["NAME", "GEO_ID"]
    assert len(fields) == 2 + 6
    assert params["for"] == "county:*"
    assert params["in"] == "state:51"


def test_acs_release_is_derived_from_end_year():
    assert config.ACS_RELEASE == f"{config.ACS_END_YEAR - 4}-{config.ACS_END_YEAR}"
    assert str(config.ACS_END_YEAR) in config.ACS_SUBJECT_URL


def test_example_filename_from_spec():
    name = config.SOURCES["acs_s2701"].filename(date(2026, 11, 10))
    assert name == "acs_s2701_2020-2024_20261110.json"


@pytest.mark.parametrize("source", config.SOURCES.values(), ids=lambda s: s.name)
def test_every_filename_follows_naming_convention(source):
    assert FILENAME_PATTERN.match(source.filename(date(2026, 11, 10)))


@pytest.mark.parametrize("source", config.SOURCES.values(), ids=lambda s: s.name)
def test_every_source_has_a_url_or_accepts_manual_files(source):
    assert source.url or source.manual_allowed


def test_raw_dir_is_inside_project():
    assert config.RAW_DIR == config.PROJECT_ROOT / "data" / "raw"


@pytest.mark.parametrize("fips, ok", [("51001", True), ("51760", True), ("24001", False), ("5101", False)])
def test_fips_pattern(fips, ok):
    assert bool(re.fullmatch(config.FIPS_PATTERN, fips)) is ok


@pytest.mark.parametrize("label, url", [
    (config.RUCC_YEAR, config.RUCC_URL),
    (str(config.BOUNDARY_YEAR), config.BOUNDARY_URL),
    (str(config.ACS_END_YEAR), config.ACS_SUBJECT_URL),
    (config.PLACES_DATASET_ID, config.PLACES_URL),
    (config.PLACES_DATASET_ID, config.PLACES_METADATA_URL),
])
def test_version_labels_match_their_urls(label, url):
    assert label in url


def test_boundary_year_matches_acs_release():
    assert config.BOUNDARY_YEAR == config.ACS_END_YEAR


def test_every_source_now_has_a_url():
    assert all(s.url for s in config.SOURCES.values())
