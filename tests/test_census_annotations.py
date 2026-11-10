"""Tests for scripts.census_annotations."""
import logging

import numpy as np
import pandas as pd
import pytest

from scripts.census_annotations import (
    CENSUS_ANNOTATION_CODES,
    acs_value_columns,
    clean_census_values,
    summarize_annotations,
)

EST, MOE = "S2701_C05_001E", "S2701_C05_001M"


def frame(values, moe=None):
    """Build a small ACS-like table of text values, as the API returns them."""
    n = len(values)
    return pd.DataFrame({
        "NAME": [f"Place {i}, Virginia" for i in range(n)],
        "GEO_ID": [f"0500000US51{i:03d}" for i in range(n)],
        EST: values,
        MOE: moe if moe is not None else ["1.0"] * n,
        "state": ["51"] * n,
        "county": [f"{i:03d}" for i in range(n)],
        "fips": [f"51{i:03d}" for i in range(n)],
    })


@pytest.mark.parametrize("text", ["-666666666", "-666666666.0", "-666666666.00", " -666666666 "])
def test_annotation_code_in_any_text_form_becomes_nan(text):
    assert np.isnan(clean_census_values(frame([text]))[EST].iloc[0])


@pytest.mark.parametrize("code", sorted(CENSUS_ANNOTATION_CODES))
def test_every_documented_code_becomes_nan_in_estimates_and_moes(code):
    out = clean_census_values(frame([str(code)], moe=[f"{code}.0"]))
    assert out[EST].isna().all() and out[MOE].isna().all()


def test_undocumented_negative_becomes_nan_not_zero():
    out = clean_census_values(frame(["-123", "-0.5"]))
    assert out[EST].isna().all()


def test_valid_values_are_kept_as_numbers():
    out = clean_census_values(frame(["0", "12.5", "4521"]))
    assert out[EST].tolist() == [0.0, 12.5, 4521.0]
    assert out[EST].dtype == float


def test_identifier_columns_stay_text_and_unchanged():
    df = frame(["-666666666", "10"])
    out = clean_census_values(df)
    for col in ("NAME", "GEO_ID", "state", "county", "fips"):
        assert out[col].tolist() == df[col].tolist()
        assert pd.api.types.is_string_dtype(out[col])
    assert out.loc[1, "fips"] == "51001"


def test_value_columns_are_detected_without_ids():
    assert acs_value_columns(frame(["1"])) == [EST, MOE]


def test_refuses_to_convert_identifier_columns():
    with pytest.raises(ValueError, match="identifiers"):
        clean_census_values(frame(["1"]), columns=[EST, "county"])


def test_refuses_unknown_columns():
    with pytest.raises(ValueError, match="missing"):
        clean_census_values(frame(["1"]), columns=["S2701_C99_001E"])


def test_input_frame_is_not_modified():
    df = frame(["-666666666"])
    clean_census_values(df)
    assert df[EST].iloc[0] == "-666666666"


def test_logs_a_count_when_codes_are_found(caplog):
    with caplog.at_level(logging.INFO, logger="scripts.census_annotations"):
        clean_census_values(frame(["-666666666", "-666666666.0", "5"], moe=["-555555555", "1", "1"]))
    assert f"{EST}: 2 Census annotation codes" in caplog.text
    assert f"{MOE}: 1 Census annotation codes" in caplog.text


def test_logs_undocumented_negatives_as_warning(caplog):
    with caplog.at_level(logging.INFO, logger="scripts.census_annotations"):
        clean_census_values(frame(["-123"]))
    assert any(r.levelno == logging.WARNING and "undocumented" in r.message for r in caplog.records)


def test_nothing_logged_for_clean_data(caplog):
    with caplog.at_level(logging.INFO, logger="scripts.census_annotations"):
        clean_census_values(frame(["1", "2"]))
    assert caplog.text == ""


def test_summary_separates_codes_negatives_text_and_blanks():
    summary = summarize_annotations(frame(["-666666666.0", "-5", "N", "", "7"]), [EST])
    row = summary.loc[EST]
    assert (row["annotation_codes"], row["other_negatives"], row["non_numeric"], row["blank"]) == (1, 1, 1, 1)
    assert row["-666666666"] == 1
