"""Census ACS annotation values (jam values) and turning them into missing data."""
from __future__ import annotations

import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CENSUS_ANNOTATION_CODES: dict[int, str] = {
    -999999999: "N: too few sample cases in the geography",
    -888888888: "(X): not applicable or not available",
    -666666666: "-: estimate could not be computed (too few observations)",
    -555555555: "*****: MOE not appropriate (estimate is controlled)",
    -333333333: "***: MOE could not be computed (median in open-ended interval)",
    -222222222: "**: MOE could not be computed (too few observations)",
}
ACS_VALUE_COLUMN = re.compile(r"^[A-Z]+\d+[A-Z]*_(?:C\d{2}_)?\d{3}[EM]$")
SUMMARY_COLUMNS = ["annotation_codes", "other_negatives", "non_numeric", "blank"]


def acs_value_columns(df: pd.DataFrame) -> list[str]:
    """Return ACS estimate (..E) and margin-of-error (..M) columns, never ID columns."""
    return [c for c in df.columns if ACS_VALUE_COLUMN.match(str(c))]


def to_numbers(values: pd.Series) -> pd.Series:
    """Convert text to floats; blanks and non-numeric text become NaN."""
    return pd.to_numeric(values.astype(str).str.strip(), errors="coerce").astype(float)


def is_blank(values: pd.Series) -> pd.Series:
    """Return True where a value is already missing or an empty string."""
    return values.isna() | (values.astype(str).str.strip() == "")


def summarize_annotations(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Count annotation codes, other negatives, non-numeric text and blanks per column."""
    rows = []
    for col in columns:
        numbers = to_numbers(df[col])
        is_code = numbers.isin(list(CENSUS_ANNOTATION_CODES))
        rows.append({
            "column": col,
            "annotation_codes": int(is_code.sum()),
            "other_negatives": int(((numbers < 0) & ~is_code).sum()),
            "non_numeric": int((numbers.isna() & ~is_blank(df[col])).sum()),
            "blank": int(is_blank(df[col]).sum()),
            **{str(code): int((numbers == code).sum()) for code in CENSUS_ANNOTATION_CODES},
        })
    code_columns = [str(code) for code in CENSUS_ANNOTATION_CODES]
    return pd.DataFrame(rows, columns=["column", *SUMMARY_COLUMNS, *code_columns]).set_index("column")


def log_summary(summary: pd.DataFrame) -> None:
    """Log one line per column that contains annotation codes or unexpected values."""
    for col, row in summary.iterrows():
        codes = {k: int(v) for k, v in row.items() if k.startswith("-") and v}
        if codes:
            logger.info("%s: %d Census annotation codes -> missing %s", col, row["annotation_codes"], codes)
        if row["other_negatives"] or row["non_numeric"]:
            logger.warning(
                "%s: %d undocumented negatives and %d non-numeric values -> missing",
                col, row["other_negatives"], row["non_numeric"],
            )


def clean_census_values(df: pd.DataFrame, columns: Sequence[str] | None = None) -> pd.DataFrame:
    """Return a copy with ACS value columns as floats and every negative value as NaN."""
    columns = list(acs_value_columns(df) if columns is None else columns)
    not_found = [c for c in columns if c not in df.columns]
    not_values = [c for c in columns if c in df.columns and not ACS_VALUE_COLUMN.match(c)]
    if not_found or not_values:
        raise ValueError(f"not ACS value columns: missing {not_found}, identifiers {not_values}")
    log_summary(summarize_annotations(df, columns))
    out = df.copy()
    for col in columns:
        numbers = to_numbers(df[col])
        out[col] = numbers.mask(numbers < 0)
    return out


def main(paths: Sequence[str]) -> int:
    """Log an annotation summary for each raw ACS JSON file given."""
    from scripts.checks import read_census_json

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    pd.set_option("display.width", 200)
    for path in map(Path, paths):
        df = read_census_json(path)
        summary = summarize_annotations(df, acs_value_columns(df))
        logger.info("%s (%d rows)\n%s", path.name, len(df), summary.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
