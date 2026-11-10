"""places_va: age-adjusted PLACES prevalence for each locality, one column group per measure."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from scripts import config
from scripts.cleaning import CleaningError
from scripts.cleaning.table_rules import as_whole_numbers, require_localities, to_number


def virginia_rows(places: pd.DataFrame) -> pd.DataFrame:
    """Return Virginia rows for the dashboard measures and value type only."""
    rows = places[
        (places["stateabbr"] == config.STATE_ABBR)
        & places["measureid"].isin(config.PLACES_MEASURES)
        & (places["datavaluetypeid"] == config.PLACES_DASHBOARD_VALUE_TYPE)
    ]
    rows = rows.assign(fips=rows["locationid"].str.strip())
    if rows.duplicated(["fips", "measureid"]).any():
        raise CleaningError("places: a locality has more than one value for the same measure")
    return rows


def measure_columns(rows: pd.DataFrame, measure: str, name: str) -> pd.DataFrame:
    """Return fips plus value, confidence limits and data year for one measure."""
    m = rows[rows["measureid"] == measure]
    return pd.DataFrame({
        "fips": m["fips"],
        f"{name}_pct": to_number(m["data_value"], f"places {measure} value"),
        f"{name}_ci_low": to_number(m["low_confidence_limit"], f"places {measure} low limit"),
        f"{name}_ci_high": to_number(m["high_confidence_limit"], f"places {measure} high limit"),
        f"{name}_data_year": as_whole_numbers(to_number(m["year"], f"places {measure} year")),
    })


def build(places: pd.DataFrame, localities: Sequence[str]) -> pd.DataFrame:
    """Build places_va by joining each measure onto the locality list by FIPS."""
    rows = virginia_rows(places)
    out = pd.DataFrame({"fips": list(localities)})
    for measure, name in config.PLACES_MEASURES.items():
        table = measure_columns(rows, measure, name)
        require_localities(table, f"places {measure}", localities)
        out = out.merge(table, on="fips", how="left", validate="one_to_one")
    require_localities(out, "places_va", localities)
    return out
