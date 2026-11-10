"""Checks on the processed tables: each project rule, plus consistency between tables."""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from scripts import config
from scripts.checks import CheckResult
from scripts.validation.processed_files import expected_columns

Tables = dict[str, pd.DataFrame]
NUMBER = r"-?\d+(\.\d+)?([eE][-+]?\d+)?"
WHOLE_NUMBER = r"\d+"


def result(name: str, problems: list[str]) -> CheckResult:
    """Pass when there are no problems; otherwise list up to three of them."""
    detail = "; ".join(problems[:3]) + (f" (+{len(problems) - 3} more)" if len(problems) > 3 else "")
    return CheckResult(name, not problems, detail)


def numbers(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a text column as floats, with blanks as NaN."""
    return pd.to_numeric(df[column].where(df[column] != ""), errors="coerce").astype(float)


def check_columns(name: str, df: pd.DataFrame) -> CheckResult:
    """Pass if the table has exactly the expected columns."""
    expected = expected_columns()[name]
    problems = []
    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]
    if missing:
        problems.append(f"missing {missing}")
    if extra:
        problems.append(f"unexpected {extra}")
    return result("columns match the schema", problems)


def check_fips_text(df: pd.DataFrame) -> CheckResult:
    """Pass if every FIPS is written as 5 digits starting with the state code (rule 1)."""
    bad = df.loc[~df["fips"].str.fullmatch(config.FIPS_PATTERN), "fips"]
    return result("fips is 5-character text starting with 51", [repr(v) for v in bad.head(3)] if len(bad) else [])


def check_one_row_per_locality(df: pd.DataFrame, reference: set[str]) -> CheckResult:
    """Pass if the table has exactly one row for each of the 133 localities (rule 6)."""
    problems = []
    if len(df) != config.STATE_COUNTY_COUNT:
        problems.append(f"{len(df)} rows")
    duplicated = sorted(set(df.loc[df["fips"].duplicated(), "fips"]))
    if duplicated:
        problems.append(f"duplicate {duplicated[:3]}")
    if reference and set(df["fips"]) != reference:
        problems.append(f"missing {sorted(reference - set(df['fips']))[:3]}, extra {sorted(set(df['fips']) - reference)[:3]}")
    return result(f"exactly {config.STATE_COUNTY_COUNT} unique localities matching dim_geography", problems)


def check_numeric(df: pd.DataFrame, columns: Iterable[str]) -> CheckResult:
    """Pass if every non-blank value in the columns is a number written plainly."""
    problems = []
    for col in columns:
        bad = df.loc[(df[col] != "") & ~df[col].str.fullmatch(NUMBER), col]
        if len(bad):
            problems.append(f"{col}: {bad.head(2).tolist()}")
    return result("numeric columns contain only numbers or blanks", problems)


def check_no_negatives(df: pd.DataFrame, columns: Iterable[str]) -> CheckResult:
    """Pass if no value is negative; Census annotation codes must already be blank (rule 4)."""
    problems = [f"{c}: {int((numbers(df, c) < 0).sum())} negative" for c in columns if (numbers(df, c) < 0).any()]
    return result("no negative values or annotation codes", problems)


def check_between(df: pd.DataFrame, columns: Iterable[str], low: float, high: float, label: str) -> CheckResult:
    """Pass if every present value lies within [low, high]."""
    problems = []
    for col in columns:
        values = numbers(df, col)
        outside = values[(values < low) | (values > high)]
        if len(outside):
            problems.append(f"{col}: {outside.head(2).tolist()}")
    return result(label, problems)


def check_not_greater(df: pd.DataFrame, pairs: Iterable[tuple[str, str]], label: str) -> CheckResult:
    """Pass if, row by row, each first column is never greater than the second."""
    problems = []
    for small, big in pairs:
        over = int((numbers(df, small) > numbers(df, big)).sum())
        if over:
            problems.append(f"{small} > {big} in {over} rows")
    return result(label, problems)


def acs_checks(acs: pd.DataFrame) -> list[CheckResult]:
    """Check ACS values: plain numbers, no negatives, valid percents, counts within universes."""
    values = [c for c in acs.columns if c != "fips"]
    pct = [c for c in values if c.endswith("_pct")]
    return [
        check_numeric(acs, values),
        check_no_negatives(acs, values),
        check_between(acs, pct, 0, 100, "percentages are between 0 and 100"),
        check_not_greater(acs, [("uninsured", "insurance_universe"), ("below_poverty", "poverty_universe")],
                          "counts do not exceed their population universe"),
    ]


def places_checks(places: pd.DataFrame) -> list[CheckResult]:
    """Check PLACES values: plain numbers, valid percents, value inside its confidence interval."""
    values = [c for c in places.columns if c != "fips"]
    pct = [c for c in values if not c.endswith("_data_year")]
    pairs = [(f"{n}_ci_low", f"{n}_pct") for n in config.PLACES_MEASURES.values()]
    pairs += [(f"{n}_pct", f"{n}_ci_high") for n in config.PLACES_MEASURES.values()]
    return [
        check_numeric(places, values),
        check_between(places, pct, 0, 100, "prevalence and limits are between 0 and 100"),
        check_not_greater(places, pairs, "ci_low <= value <= ci_high"),
    ]


def dim_checks(dim: pd.DataFrame) -> list[CheckResult]:
    """Check the locality list: county/city split, unique names, RUCC codes and metro status."""
    counts = dim["locality_type"].value_counts().to_dict()
    rucc = numbers(dim, "rucc_code")
    metro = rucc.isin([int(c) for c in config.RUCC_METRO_CODES])
    wrong_status = dim[rucc.notna() & (dim["metro_status"] != metro.map({True: "Metro", False: "Nonmetro"}))]
    return [
        result("county/city split matches Virginia",
               [] if counts == config.STATE_LOCALITY_TYPE_COUNTS else [f"found {counts}"]),
        result("locality names are unique",
               sorted(set(dim.loc[dim["locality_name"].duplicated(), "locality_name"]))),
        check_between(dim, ["rucc_code"], 1, 9, "RUCC codes are 1-9"),
        result("metro_status agrees with rucc_code", wrong_status["fips"].head(3).tolist()),
    ]


def site_checks(sites: pd.DataFrame, reference: set[str]) -> list[CheckResult]:
    """Check sites: unique IDs, supply flag follows the rules, matched FIPS and coordinates in Virginia."""
    flagged = sites[sites["in_supply_measure"] == "True"]
    rule_breaks = [
        f"{field} {sorted(set(flagged[field]) - set(allowed))}"
        for field, allowed in config.HRSA_SUPPLY_RULES.items()
        if set(flagged[field]) - set(allowed)
    ]
    matched = sites["fips"].isin(reference)
    wrong_match = sites[matched != (sites["fips_matched"] == "True")]
    unmatched_counted = flagged[~flagged["fips"].isin(reference)]
    box = config.STATE_BOUNDING_BOX
    lat, lon = numbers(sites, "latitude"), numbers(sites, "longitude")
    outside = sites[matched & ~(lat.between(*box["latitude"]) & lon.between(*box["longitude"]))]
    return [
        result("site_id is unique", sorted(set(sites.loc[sites["site_id"].duplicated(), "site_id"]))[:3]),
        result("supply sites are active, permanent, service-delivery", rule_breaks),
        result("fips_matched agrees with dim_geography", wrong_match["site_id"].head(3).tolist()),
        result("no unmatched site is counted", unmatched_counted["site_id"].head(3).tolist()),
        result("matched sites have coordinates inside Virginia", outside["site_id"].head(3).tolist()),
    ]


def supply_checks(fact: pd.DataFrame, sites: pd.DataFrame) -> list[CheckResult]:
    """Check counts are whole, never blank (rule 5), and agree with the site table."""
    count_cols = ["supply_sites", "active_sites_any_type"]
    not_whole = [c for c in count_cols if not fact[c].str.fullmatch(WHOLE_NUMBER).all()]
    total = int(numbers(fact, "supply_sites").sum())
    flagged = int((sites["in_supply_measure"] == "True").sum())
    return [
        result("site counts are whole numbers, never blank", not_whole),
        check_not_greater(fact, [("supply_sites", "active_sites_any_type")], "supply_sites <= active_sites_any_type"),
        result("supply_sites total equals flagged sites", [] if total == flagged else [f"{total} vs {flagged}"]),
    ]


def run_all(tables: Tables) -> dict[str, list[CheckResult]]:
    """Run every check; tables with the wrong columns get only the column check."""
    results = {name: [check_columns(name, df)] for name, df in tables.items()}
    if not all(r[0].passed for r in results.values()):
        return results
    reference = set(tables["dim_geography"]["fips"])
    for name in config.LOCALITY_TABLES:
        results[name] += [check_fips_text(tables[name]), check_one_row_per_locality(tables[name], reference)]
    sites = tables[config.SITE_TABLE]
    results[config.SITE_TABLE].append(check_fips_text(sites[sites["fips_matched"] == "True"]))
    results["dim_geography"] += dim_checks(tables["dim_geography"])
    results["acs_va"] += acs_checks(tables["acs_va"])
    results["places_va"] += places_checks(tables["places_va"])
    results[config.SITE_TABLE] += site_checks(tables[config.SITE_TABLE], reference)
    results["fact_supply"] += supply_checks(tables["fact_supply"], tables[config.SITE_TABLE])
    return results


def missing_values(tables: Tables) -> list[tuple[str, str, int, int]]:
    """Return (table, column, blanks, rows) for every column that has blanks."""
    return [
        (name, col, int((df[col] == "").sum()), len(df))
        for name, df in tables.items()
        for col in df.columns
        if (df[col] == "").any()
    ]
