"""Rules every cleaned table follows: one row per locality, FIPS as text, strict numbers."""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from scripts import config
from scripts.cleaning import CleaningError


def require_localities(df: pd.DataFrame, table: str, expected_fips: Iterable[str]) -> None:
    """Raise CleaningError unless the table has exactly one text FIPS row per expected locality."""
    if "fips" not in df.columns:
        raise CleaningError(f"{table}: no fips column")
    fips, expected = df["fips"], set(expected_fips)
    problems = []
    if not pd.api.types.is_string_dtype(fips):
        problems.append(f"fips is stored as {fips.dtype}, not text")
    malformed = fips[~fips.astype(str).str.fullmatch(config.FIPS_PATTERN)]
    if len(malformed):
        problems.append(f"{len(malformed)} malformed FIPS, e.g. {malformed.head(3).tolist()}")
    duplicated = sorted(set(fips[fips.duplicated()]))
    if duplicated:
        problems.append(f"duplicate FIPS {duplicated[:5]}")
    missing, extra = sorted(expected - set(fips)), sorted(set(fips) - expected)
    if missing:
        problems.append(f"{len(missing)} localities missing, e.g. {missing[:5]}")
    if extra:
        problems.append(f"{len(extra)} unexpected FIPS, e.g. {extra[:5]}")
    if len(expected) != config.STATE_COUNTY_COUNT:
        problems.append(f"expected {config.STATE_COUNTY_COUNT} localities, reference list has {len(expected)}")
    if problems:
        raise CleaningError(f"{table}: " + "; ".join(problems))


def to_number(values: pd.Series, label: str) -> pd.Series:
    """Parse text as floats; blanks become NaN, any other non-number raises CleaningError."""
    text = values.astype("string").str.strip()
    numbers = pd.to_numeric(text.replace("", pd.NA), errors="coerce").astype(float)
    bad = text[numbers.isna() & text.notna() & (text != "")]
    if len(bad):
        raise CleaningError(f"{label}: {len(bad)} values are not numbers, e.g. {bad.head(3).tolist()}")
    return numbers


def as_whole_numbers(values: pd.Series) -> pd.Series:
    """Return nullable integers when every present value is whole, else the floats unchanged."""
    present = values.dropna()
    return values.round().astype("Int64") if (present == present.round()).all() else values
