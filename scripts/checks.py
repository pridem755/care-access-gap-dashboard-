"""Post-download sanity checks. Checks only read files; they never change them."""
from __future__ import annotations

import json
import logging
import re
import struct
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CSV_ENCODINGS = ("utf-8-sig", "cp1252")
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj")
HTML_STARTS = (b"<!doctype html", b"<html")
UTF8_BOM = b"\xef\xbb\xbf"
DBF_HEADER_END = 0x0D


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check."""

    name: str
    passed: bool
    detail: str = ""


SourceCheck = Callable[[pd.DataFrame], list[CheckResult]]
SOURCE_CHECKS: dict[str, SourceCheck] = {}


def register(source_name: str) -> Callable[[SourceCheck], SourceCheck]:
    """Decorator that attaches a check function to a source."""
    def wrap(func: SourceCheck) -> SourceCheck:
        SOURCE_CHECKS[source_name] = func
        return func
    return wrap


def read_csv(path: Path) -> tuple[pd.DataFrame, str]:
    """Read a CSV as text columns; return the table and the encoding that worked."""
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"not readable as {' or '.join(CSV_ENCODINGS)}")


def read_census_json(path: Path) -> pd.DataFrame:
    """Read Census API JSON (a list of rows, header first) as text columns."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(rows, list) and rows and all(isinstance(r, list) for r in rows)):
        raise ValueError("expected a JSON list of rows with a header row first")
    header, *data = rows
    return pd.DataFrame(data, columns=header, dtype=str)


def read_xlsx(path: Path) -> pd.DataFrame:
    """Read the first sheet of a workbook as text columns."""
    return pd.read_excel(path, dtype=str, keep_default_na=False, engine="openpyxl")


def dbf_record_count(path: Path) -> int:
    """Return the record count stored in the .dbf header inside a shapefile ZIP."""
    with zipfile.ZipFile(path) as archive:
        dbf = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
        with archive.open(dbf) as handle:
            header = handle.read(8)
    return struct.unpack("<I", header[4:8])[0]


def dbf_fields(data: bytes) -> list[tuple[str, int]]:
    """Return (name, width) for each field described in a .dbf header."""
    fields, pos = [], 32
    while data[pos] != DBF_HEADER_END:
        descriptor = data[pos:pos + 32]
        fields.append((descriptor[:11].split(b"\0")[0].decode("ascii"), descriptor[16]))
        pos += 32
    return fields


def read_dbf(path: Path) -> pd.DataFrame:
    """Read the attribute table (.dbf) inside a shapefile ZIP as text columns."""
    with zipfile.ZipFile(path) as archive:
        data = archive.read(next(n for n in archive.namelist() if n.lower().endswith(".dbf")))
    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = dbf_fields(data)
    rows = []
    for i in range(n_records):
        record = data[header_len + i * record_len:header_len + (i + 1) * record_len]
        if record[:1] == b"*":
            continue
        values, offset = [], 1
        for _, width in fields:
            values.append(record[offset:offset + width].decode("utf-8", "replace").strip())
            offset += width
        rows.append(values)
    return pd.DataFrame(rows, columns=[name for name, _ in fields], dtype=str)


def load_table(path: Path) -> pd.DataFrame:
    """Parse a CSV, Census JSON, XLSX or shapefile ZIP into a DataFrame of strings."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)[0]
    if suffix == ".json":
        return read_census_json(path)
    if suffix == ".xlsx":
        return read_xlsx(path)
    if suffix == ".zip":
        return read_dbf(path)
    raise ValueError(f"no table reader for {suffix} files")


def count_rows(path: Path) -> int:
    """Return the data rows the checks see: table rows, or live shapefile records."""
    return len(load_table(path))


def check_not_empty(path: Path) -> CheckResult:
    """Pass if the file exists and has at least one byte."""
    size = path.stat().st_size if path.exists() else 0
    return CheckResult("file is not empty", size > 0, f"{size:,} bytes")


def check_not_html(path: Path) -> CheckResult:
    """Fail if the file is a web page (e.g. an error page) rather than data."""
    with path.open("rb") as handle:
        start = handle.read(1024).lstrip().removeprefix(UTF8_BOM).lstrip().lower()
    is_html = start.startswith(HTML_STARTS)
    return CheckResult("file is data, not an HTML page", not is_html, "starts like a web page" if is_html else "")


def check_zip(path: Path) -> list[CheckResult]:
    """Check that a ZIP is intact and holds a complete shapefile."""
    if not zipfile.is_zipfile(path):
        return [CheckResult("parses as ZIP", False, "not a ZIP archive")]
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        names = [n.lower() for n in archive.namelist()]
    missing = [ext for ext in SHAPEFILE_PARTS if not any(n.endswith(ext) for n in names)]
    results = [
        CheckResult("parses as ZIP", bad_member is None, f"corrupt member: {bad_member}" if bad_member else ""),
        CheckResult("ZIP holds .shp/.shx/.dbf/.prj", not missing, f"missing {missing}" if missing else ""),
    ]
    if not missing:
        records = dbf_record_count(path)
        results.append(CheckResult("shapefile has records", records > 0, f"{records:,} records"))
    return results


def expect_columns(df: pd.DataFrame, columns: Iterable[str]) -> CheckResult:
    """Pass if every named column is present."""
    missing = [c for c in columns if c not in df.columns]
    return CheckResult("required columns present", not missing, f"missing {missing}" if missing else "")


def expect_row_count(df: pd.DataFrame, expected: int, label: str = "rows") -> CheckResult:
    """Pass if the table has exactly the expected number of rows."""
    return CheckResult(f"exactly {expected} {label}", len(df) == expected, f"found {len(df)}")


def expect_pattern(df: pd.DataFrame, column: str, pattern: str, label: str | None = None) -> CheckResult:
    """Pass if every value in a column fully matches a regular expression."""
    name = label or f"{column} matches {pattern}"
    if column not in df.columns:
        return CheckResult(name, False, f"no column {column!r}")
    bad = df.loc[~df[column].fillna("").str.fullmatch(pattern), column]
    detail = f"{len(bad)} bad values, e.g. {bad.head(3).tolist()}" if len(bad) else ""
    return CheckResult(name, bad.empty, detail)


def expect_unique_count(df: pd.DataFrame, column: str, expected: int, label: str = "") -> CheckResult:
    """Pass if a column has exactly `expected` distinct values and no duplicates."""
    name = f"{label or column}: {expected} unique {column}"
    if column not in df.columns:
        return CheckResult(name, False, f"no column {column!r}")
    unique, rows = df[column].nunique(), len(df)
    return CheckResult(name, unique == expected == rows, f"{rows} rows, {unique} unique")


def expect_no_duplicates(df: pd.DataFrame, column: str, label: str) -> CheckResult:
    """Pass if no value in a column appears more than once."""
    name = f"{label} have no duplicates"
    if column not in df.columns:
        return CheckResult(name, False, f"no column {column!r}")
    dupes = int(df[column].duplicated().sum())
    return CheckResult(name, dupes == 0, f"{dupes} duplicate rows" if dupes else "")


def expect_values_in(df: pd.DataFrame, column: str, allowed: Iterable[str]) -> CheckResult:
    """Pass if every value in a column is one of the allowed values."""
    name = f"{column} has only documented values"
    if column not in df.columns:
        return CheckResult(name, False, f"no column {column!r}")
    unexpected = sorted(set(df[column]) - set(allowed))
    return CheckResult(name, not unexpected, f"unexpected {unexpected}" if unexpected else "")


def expect_any_rows(df: pd.DataFrame, label: str) -> CheckResult:
    """Pass if a filtered table has at least one row."""
    return CheckResult(f"{label} present", len(df) > 0, f"{len(df):,} rows")


def run_source_checks(source_name: str, df: pd.DataFrame) -> list[CheckResult]:
    """Run the source's registered checks; report a crash as a failed check."""
    check = SOURCE_CHECKS.get(source_name)
    if check is None:
        return []
    try:
        return check(df)
    except Exception as exc:
        return [CheckResult(f"{source_name} checks ran", False, f"{type(exc).__name__}: {exc}")]


def run_checks(source_name: str, path: Path) -> list[CheckResult]:
    """Run file-level checks, then the source's own checks if the file parsed."""
    results = [check_not_empty(path)]
    if not results[0].passed:
        return results
    if path.suffix.lower() == ".zip":
        results += check_zip(path)
        if not all(r.passed for r in results):
            return results
        kind = "shapefile attribute table"
    else:
        results.append(check_not_html(path))
        kind = path.suffix[1:].upper()
    try:
        df = load_table(path)
    except Exception as exc:
        return results + [CheckResult(f"parses as {kind}", False, str(exc))]
    results += [
        CheckResult(f"parses as {kind}", True, f"{len(df.columns)} columns"),
        CheckResult("has data rows", len(df) > 0, f"{len(df):,} rows"),
    ]
    return results + run_source_checks(source_name, df)


def report(source_name: str, path: Path, results: list[CheckResult]) -> bool:
    """Log every result, failures as loud warnings; return True if all passed."""
    for r in results:
        if r.passed:
            logger.info("PASS [%s] %s %s", source_name, r.name, f"({r.detail})" if r.detail else "")
        else:
            logger.warning("CHECK FAILED [%s] %s: %s (file kept: %s)", source_name, r.name, r.detail, path.name)
    failed = sum(not r.passed for r in results)
    if failed:
        logger.warning("%d of %d checks FAILED for %s. Inspect the file before using it.",
                       failed, len(results), path.name)
    return failed == 0
