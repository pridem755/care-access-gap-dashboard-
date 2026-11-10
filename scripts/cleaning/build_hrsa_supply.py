"""hrsa_sites_va (one row per site) and fact_supply (supply-site counts per locality)."""
from __future__ import annotations

import logging
from collections.abc import Sequence

import pandas as pd

from scripts import config
from scripts.cleaning.table_rules import require_localities, to_number

logger = logging.getLogger(__name__)


def sites_table(hrsa: pd.DataFrame, localities: Sequence[str]) -> pd.DataFrame:
    """Return Virginia sites with clean names, unique IDs and an in_supply_measure flag."""
    va = hrsa[hrsa[config.HRSA_COLUMNS["state"]].str.strip() == config.STATE_ABBR]
    sites = va[list(config.HRSA_SITE_FIELDS)].rename(columns=config.HRSA_SITE_FIELDS)
    sites = sites.apply(lambda column: column.str.strip())
    duplicates = int(sites["site_id"].duplicated().sum())
    if duplicates:
        logger.warning("hrsa_sites_va: removed %d rows with a duplicate site_id", duplicates)
        sites = sites.drop_duplicates("site_id", keep="first")
    sites["latitude"] = to_number(sites["latitude"], "hrsa latitude")
    sites["longitude"] = to_number(sites["longitude"], "hrsa longitude")
    sites["fips_matched"] = sites["fips"].isin(set(localities))
    unmatched = int((~sites["fips_matched"]).sum())
    if unmatched:
        logger.warning("hrsa_sites_va: %d sites have a FIPS outside the 133 localities; not counted", unmatched)
    in_supply = sites["fips_matched"].copy()
    for field, allowed in config.HRSA_SUPPLY_RULES.items():
        in_supply &= sites[field].isin(allowed)
    sites["in_supply_measure"] = in_supply
    return sites.sort_values(["fips", "site_id"]).reset_index(drop=True)


def count_by_locality(sites: pd.DataFrame, localities: Sequence[str], name: str) -> pd.Series:
    """Count sites per locality, with 0 for localities that have none."""
    counts = sites.groupby("fips").size()
    return counts.reindex(list(localities), fill_value=0).astype("int64").rename(name)


def supply_table(sites: pd.DataFrame, localities: Sequence[str]) -> pd.DataFrame:
    """Build fact_supply: every locality, its supply-site count and its count of all active sites."""
    supply = count_by_locality(sites[sites["in_supply_measure"]], localities, "supply_sites")
    active = sites[sites["fips_matched"] & (sites["status"] == "Active")]
    out = pd.concat([supply, count_by_locality(active, localities, "active_sites_any_type")], axis=1)
    out = out.rename_axis("fips").reset_index()
    out["fips"] = out["fips"].astype("string")
    require_localities(out, "fact_supply", localities)
    return out
