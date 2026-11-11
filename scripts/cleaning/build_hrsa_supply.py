"""hrsa_sites_va (one row per site) and fact_supply (supply-site counts per locality)."""
from __future__ import annotations

import logging
from collections.abc import Sequence

import pandas as pd

from scripts import config
from scripts.cleaning.table_rules import require_localities, to_number

logger = logging.getLogger(__name__)

MATCH_PUNCTUATION = r"[.,'’#]"
DUPLICATE_COLUMNS = ("duplicate_key", "site_id", "site_name", "program_type", "address", "fips", "counted_once")


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
    sites["duplicate_key"] = duplicate_keys(sites)
    counted = sites[in_supply].sort_values("site_id")
    sites["counted_once"] = sites.index.isin(counted.index[~counted["duplicate_key"].duplicated()])
    return sites.sort_values(["fips", "site_id"]).reset_index(drop=True)


def normalize_for_matching(values: pd.Series) -> pd.Series:
    """Lowercase, drop periods, commas, apostrophes and #, and collapse whitespace."""
    cleaned = values.str.lower().str.replace(MATCH_PUNCTUATION, "", regex=True)
    return cleaned.str.split().str.join(" ")


def unmatchable(sites: pd.DataFrame) -> pd.Series:
    """Return True where the normalized address or site name is blank."""
    return (normalize_for_matching(sites["address"]) == "") | (normalize_for_matching(sites["site_name"]) == "")


def duplicate_keys(sites: pd.DataFrame) -> pd.Series:
    """Return fips|address|site_name, or fips|site_id when either part is blank."""
    keys = sites["fips"] + "|" + normalize_for_matching(sites["address"]) + "|" + normalize_for_matching(sites["site_name"])
    return keys.where(~unmatchable(sites), sites["fips"] + "|" + sites["site_id"])


def duplicates_table(sites: pd.DataFrame) -> pd.DataFrame:
    """Return the counted sites that share a duplicate_key with another counted site."""
    counted = sites[sites["in_supply_measure"]]
    shared = counted[counted["duplicate_key"].duplicated(keep=False)]
    return shared[list(DUPLICATE_COLUMNS)].sort_values(["duplicate_key", "site_id"]).reset_index(drop=True)


def duplicate_summary(sites: pd.DataFrame) -> dict[str, int]:
    """Count counted records, distinct counted sites, merged rows, affected localities and unmatchable rows."""
    counted = sites[sites["in_supply_measure"]]
    merged = counted[~counted["counted_once"]]
    return {
        "counted site records": len(counted),
        "distinct counted sites": int(counted["counted_once"].sum()),
        "duplicate site records merged": len(merged),
        "localities affected": merged["fips"].nunique(),
        "records excluded from matching (blank address or name)": int(unmatchable(counted).sum()),
    }


def count_by_locality(sites: pd.DataFrame, localities: Sequence[str], name: str) -> pd.Series:
    """Count sites per locality, with 0 for localities that have none."""
    counts = sites.groupby("fips").size()
    return counts.reindex(list(localities), fill_value=0).astype("int64").rename(name)


def supply_table(sites: pd.DataFrame, localities: Sequence[str]) -> pd.DataFrame:
    """Build fact_supply: every locality, its supply-site count and its count of all active sites."""
    supply = count_by_locality(sites[sites["counted_once"]], localities, "supply_sites")
    active = sites[sites["fips_matched"] & (sites["status"] == "Active")]
    out = pd.concat([supply, count_by_locality(active, localities, "active_sites_any_type")], axis=1)
    out = out.rename_axis("fips").reset_index()
    out["fips"] = out["fips"].astype("string")
    require_localities(out, "fact_supply", localities)
    return out
