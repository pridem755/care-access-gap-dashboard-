"""dim_geography: the 133 Virginia localities, from the boundary file plus RUCC codes."""
from __future__ import annotations

import logging

import pandas as pd

from scripts import config
from scripts.cleaning import CleaningError
from scripts.cleaning.table_rules import as_whole_numbers, require_localities, to_number

logger = logging.getLogger(__name__)

COLUMNS = [
    "fips", "locality_name", "locality_type", "metro_status",
    "rucc_code", "rucc_description", "population_2020", "land_area_sq_mi",
]


def localities_from_boundaries(boundaries: pd.DataFrame) -> pd.DataFrame:
    """Return one row per Virginia county or independent city from the shapefile attributes."""
    va = boundaries[boundaries[config.BOUNDARY_STATE_COLUMN] == config.STATE_FIPS]
    unknown = sorted(set(va["LSAD"]) - set(config.BOUNDARY_LOCALITY_TYPES))
    if unknown:
        raise CleaningError(f"boundaries: unknown LSAD codes {unknown}; add them to BOUNDARY_LOCALITY_TYPES")
    land = to_number(va["ALAND"], "boundaries ALAND")
    return pd.DataFrame({
        "fips": va[config.BOUNDARY_FIPS_COLUMN].str.strip(),
        "locality_name": va["NAMELSAD"].str.strip(),
        "locality_type": va["LSAD"].map(config.BOUNDARY_LOCALITY_TYPES),
        "land_area_sq_mi": (land / config.SQUARE_METERS_PER_SQUARE_MILE).round(2),
    }).sort_values("fips").reset_index(drop=True)


def rucc_by_locality(rucc: pd.DataFrame) -> pd.DataFrame:
    """Turn RUCC's long format (one row per attribute) into one row per Virginia locality."""
    va = rucc[(rucc["State"] == config.STATE_ABBR) & rucc["Attribute"].isin(config.RUCC_FIELDS)]
    va = va.assign(FIPS=va["FIPS"].str.strip(), Value=va["Value"].str.strip())
    if va.duplicated(["FIPS", "Attribute"]).any():
        raise CleaningError("rucc: a locality has the same attribute more than once")
    wide = (
        va.pivot(index="FIPS", columns="Attribute", values="Value")
        .reindex(columns=list(config.RUCC_FIELDS))
        .rename(columns=config.RUCC_FIELDS)
        .rename_axis(index="fips", columns=None)
        .reset_index()
    )
    wide["rucc_code"] = as_whole_numbers(to_number(wide["rucc_code"], "rucc code"))
    wide["population_2020"] = as_whole_numbers(to_number(wide["population_2020"], "rucc population"))
    metro_codes = {int(code) for code in config.RUCC_METRO_CODES}
    wide["metro_status"] = wide["rucc_code"].map(
        lambda code: pd.NA if pd.isna(code) else ("Metro" if code in metro_codes else "Nonmetro")
    ).astype("string")
    return wide


def build(boundaries: pd.DataFrame, rucc: pd.DataFrame) -> pd.DataFrame:
    """Build dim_geography with exactly one row per locality."""
    localities = localities_from_boundaries(boundaries)
    require_localities(localities, "boundaries", localities["fips"])
    dim = localities.merge(rucc_by_locality(rucc), on="fips", how="left", validate="one_to_one")
    unmatched = int(dim["rucc_code"].isna().sum())
    if unmatched:
        logger.warning("dim_geography: %d localities have no RUCC code (left missing)", unmatched)
    require_localities(dim, "dim_geography", localities["fips"])
    return dim[COLUMNS]
