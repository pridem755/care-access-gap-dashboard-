"""acs_va: insurance and poverty estimates, margins of error and CVs for each locality."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from scripts import config
from scripts.census_annotations import clean_census_values
from scripts.cleaning import CleaningError
from scripts.cleaning.table_rules import as_whole_numbers, require_localities


def coefficient_of_variation(estimate: pd.Series, moe: pd.Series) -> pd.Series:
    """Return CV = (MOE / 1.645) / estimate; missing when either is missing or the estimate is 0."""
    return ((moe / config.MOE_Z_SCORE) / estimate.where(estimate > 0)).round(4)


def acs_table(raw: pd.DataFrame, variables: dict[str, str]) -> pd.DataFrame:
    """Return fips plus <name>, <name>_moe and <name>_cv for each requested variable."""
    moe_codes = [code[:-1] + "M" for code in variables]
    values = clean_census_values(raw, [*variables, *moe_codes])
    table = pd.DataFrame({"fips": raw["state"].str.strip() + raw["county"].str.strip()})
    for code, name in variables.items():
        estimate, moe = values[code], values[code[:-1] + "M"]
        table[name] = as_whole_numbers(estimate)
        table[f"{name}_moe"] = as_whole_numbers(moe)
        table[f"{name}_cv"] = coefficient_of_variation(estimate, moe)
    return table


def build(s2701: pd.DataFrame, s1701: pd.DataFrame, localities: Sequence[str]) -> pd.DataFrame:
    """Build acs_va by joining both ACS tables onto the locality list by FIPS."""
    out = pd.DataFrame({"fips": list(localities)})
    for label, raw, variables in (
        ("acs S2701", s2701, config.ACS_S2701_VARIABLES),
        ("acs S1701", s1701, config.ACS_S1701_VARIABLES),
    ):
        table = acs_table(raw, variables)
        require_localities(table, label, localities)
        out = out.merge(table, on="fips", how="left", validate="one_to_one")
    numbers = out.drop(columns="fips")
    if (numbers < 0).any().any():
        raise CleaningError("acs_va: negative values remain after removing Census annotation codes")
    require_localities(out, "acs_va", localities)
    return out
