"""Tests for the cleaning step: one test per project rule, plus an end-to-end run."""
import csv
import io
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scripts import clean_data, config, download_log
from scripts.cleaning import CleaningError, raw_inputs
from scripts.cleaning import build_acs_va, build_dim_geography, build_hrsa_supply, build_places_va
from scripts.cleaning.table_rules import as_whole_numbers, require_localities, to_number
from scripts.sources import census_acs

RICHMOND_COUNTY, RICHMOND_CITY = "51159", "51760"
LOCALITIES = [f"51{i:03d}" for i in range(1, 132)] + [RICHMOND_COUNTY, RICHMOND_CITY]
TODAY = date(2026, 11, 10)
H = config.HRSA_SITE_FIELDS


def frame(rows):
    return pd.DataFrame(rows).astype("string")


# ---------- table rules ----------

def test_require_localities_accepts_a_complete_text_table():
    require_localities(pd.DataFrame({"fips": LOCALITIES}), "t", LOCALITIES)


@pytest.mark.parametrize("fips, message", [
    (LOCALITIES[:-1], "1 localities missing"),
    (LOCALITIES[:-1] + [LOCALITIES[0]], "duplicate FIPS"),
    (LOCALITIES[:-1] + ["24001"], "malformed FIPS"),
])
def test_require_localities_rejects_incomplete_tables(fips, message):
    with pytest.raises(CleaningError, match=message):
        require_localities(pd.DataFrame({"fips": fips}), "t", LOCALITIES)


def test_require_localities_rejects_numeric_fips():
    with pytest.raises(CleaningError, match="not text"):
        require_localities(pd.DataFrame({"fips": [int(f) for f in LOCALITIES]}), "t", LOCALITIES)


def test_to_number_keeps_blanks_missing_and_rejects_text():
    assert to_number(pd.Series([" 12.5 ", "", None]), "x").tolist()[0] == 12.5
    assert to_number(pd.Series([""]), "x").isna().all()
    with pytest.raises(CleaningError, match="not numbers"):
        to_number(pd.Series(["12", "N/A"]), "x")


def test_as_whole_numbers_only_converts_whole_values():
    assert as_whole_numbers(pd.Series([1.0, np.nan])).dtype == "Int64"
    assert as_whole_numbers(pd.Series([1.5])).dtype == float


# ---------- dim_geography ----------

def boundaries_frame(lsad="06"):
    rows = [{"STATEFP": "51", "GEOID": f, "NAMELSAD": f"Place {f} County", "LSAD": lsad, "ALAND": "2589988.110336"}
            for f in LOCALITIES]
    rows[LOCALITIES.index(RICHMOND_COUNTY)]["NAMELSAD"] = "Richmond County"
    rows[-1].update(NAMELSAD="Richmond city", LSAD="25")
    rows.append({"STATEFP": "24", "GEOID": "24001", "NAMELSAD": "Allegany County", "LSAD": "06", "ALAND": "1"})
    return frame(rows)


def rucc_frame(codes=None, skip=()):
    rows = []
    for i, f in enumerate(LOCALITIES):
        if f in skip:
            continue
        code = (codes or {}).get(f, str(i % 9 + 1))
        rows += [
            {"FIPS": f, "State": "VA", "County_Name": "X", "Attribute": "Population_2020", "Value": "1000"},
            {"FIPS": f, "State": "VA", "County_Name": "X", "Attribute": config.RUCC_ATTRIBUTE, "Value": code},
            {"FIPS": f, "State": "VA", "County_Name": "X", "Attribute": "Description", "Value": "desc"},
        ]
    return frame(rows)


def test_dim_has_133_localities_and_keeps_same_name_pairs_apart():
    dim = build_dim_geography.build(boundaries_frame(), rucc_frame())
    assert len(dim) == 133 and dim["fips"].is_unique
    pair = dim.set_index("fips").loc[[RICHMOND_COUNTY, RICHMOND_CITY]]
    assert pair["locality_name"].tolist() == ["Richmond County", "Richmond city"]
    assert pair["locality_type"].tolist() == ["County", "City"]
    assert dim["land_area_sq_mi"].iloc[0] == 1.0


def test_dim_metro_status_follows_rucc_codes_and_missing_stays_missing():
    dim = build_dim_geography.build(
        boundaries_frame(), rucc_frame(codes={"51001": "3", "51002": "4"}, skip={"51003"})
    ).set_index("fips")
    assert dim.loc["51001", "metro_status"] == "Metro"
    assert dim.loc["51002", "metro_status"] == "Nonmetro"
    assert pd.isna(dim.loc["51003", "metro_status"]) and pd.isna(dim.loc["51003", "rucc_code"])


def test_dim_rejects_unknown_locality_type_codes():
    with pytest.raises(CleaningError, match="unknown LSAD"):
        build_dim_geography.build(boundaries_frame(lsad="99"), rucc_frame())


# ---------- acs_va ----------

def acs_frame(source_name, overrides=None, drop=()):
    source = config.SOURCES[source_name]
    header = census_acs.requested_columns(source)
    rows = []
    for f in LOCALITIES:
        if f in drop:
            continue
        values = {c: "1000" if c.endswith("E") else "164.5" for c in header[2:-2]}
        values.update((overrides or {}).get(f, {}))
        rows.append({"NAME": f"Place {f}", "GEO_ID": f"0500000US{f}", **values, "state": f[:2], "county": f[2:]})
    return frame(rows)


def build_acs(**s2701):
    return build_acs_va.build(acs_frame("acs_s2701", **s2701), acs_frame("acs_s1701"), LOCALITIES).set_index("fips")


def test_acs_annotation_codes_become_missing_never_zero():
    acs = build_acs(overrides={"51001": {"S2701_C04_001E": "-666666666", "S2701_C04_001M": "-555555555.0"}})
    assert pd.isna(acs.loc["51001", "uninsured"]) and pd.isna(acs.loc["51001", "uninsured_moe"])
    assert pd.isna(acs.loc["51001", "uninsured_cv"])
    assert acs.loc["51002", "uninsured"] == 1000


def test_acs_cv_formula_and_zero_estimate():
    acs = build_acs(overrides={"51002": {"S2701_C04_001E": "0"}})
    assert acs.loc["51001", "uninsured_cv"] == pytest.approx(0.1)
    assert pd.isna(acs.loc["51002", "uninsured_cv"])


def test_acs_counts_are_whole_numbers_and_fips_is_text():
    out = build_acs_va.build(acs_frame("acs_s2701"), acs_frame("acs_s1701"), LOCALITIES)
    assert out["uninsured"].dtype == "Int64"
    assert pd.api.types.is_string_dtype(out["fips"]) and out["fips"].iloc[0] == "51001"
    assert len(out) == 133


def test_acs_missing_locality_stops_cleaning():
    with pytest.raises(CleaningError, match="acs S2701: 1 localities missing"):
        build_acs(drop={"51005"})


# ---------- places_va ----------

def places_frame(age_adjusted="10.0", crude="99.0", drop=(), extra=()):
    rows = []
    for f in LOCALITIES:
        for measure in config.PLACES_MEASURES:
            for value_type, value in (("CrdPrv", crude), ("AgeAdjPrv", age_adjusted)):
                if (f, measure, value_type) in drop:
                    continue
                rows.append({"year": "2023", "stateabbr": "VA", "locationname": "Richmond", "locationid": f,
                             "measureid": measure, "datavaluetypeid": value_type, "data_value": value,
                             "low_confidence_limit": "8.0", "high_confidence_limit": "12.0"})
    rows.append({**rows[0], "stateabbr": "US", "locationid": "59"})
    rows.extend(extra)
    return frame(rows)


def test_places_uses_age_adjusted_values_only():
    out = build_places_va.build(places_frame(), LOCALITIES)
    assert (out["diabetes_pct"] == 10.0).all() and (out["high_blood_pressure_pct"] == 10.0).all()
    assert len(out) == 133


def test_places_suppressed_value_stays_missing():
    out = build_places_va.build(places_frame(age_adjusted=""), LOCALITIES)
    assert out["diabetes_pct"].isna().all()


def test_places_duplicate_value_stops_cleaning():
    duplicate = places_frame().iloc[1].to_dict()
    with pytest.raises(CleaningError, match="more than one value"):
        build_places_va.build(places_frame(extra=[duplicate]), LOCALITIES)


def test_places_missing_locality_stops_cleaning():
    with pytest.raises(CleaningError, match="1 localities missing"):
        build_places_va.build(places_frame(drop={("51007", "BPHIGH", "AgeAdjPrv")}), LOCALITIES)


# ---------- hrsa_sites_va and fact_supply ----------

def site(site_id, fips, status="Active", site_type="Service Delivery Site", location_type="Permanent", state="VA"):
    row = {raw: "" for raw in set(H) | set(config.HRSA_COLUMNS.values())}
    row.update({
        "BPHC Assigned Number": site_id, "Site Name": f" Clinic {site_id} ", "Site State Abbreviation": state,
        "State and County Federal Information Processing Standard Code": fips,
        "Site Status Description": status, "Health Center Type Description": site_type,
        "Health Center Location Type Description": location_type,
        "Geocoding Artifact Address Primary Y Coordinate": "37.5",
        "Geocoding Artifact Address Primary X Coordinate": "-77.4",
    })
    return row


HRSA_ROWS = [
    site("A", RICHMOND_CITY),
    site("A", RICHMOND_CITY),
    site("B", RICHMOND_CITY, site_type="Administrative/Service Delivery Site"),
    site("C", RICHMOND_CITY, site_type="Administrative"),
    site("D", RICHMOND_CITY, location_type="Mobile Van"),
    site("E", RICHMOND_CITY, status="Terminated"),
    site("F", RICHMOND_COUNTY),
    site("G", "51515"),
    site("H", "24001", state="MD"),
]


def build_hrsa():
    sites = build_hrsa_supply.sites_table(frame(HRSA_ROWS), LOCALITIES)
    return sites, build_hrsa_supply.supply_table(sites, LOCALITIES).set_index("fips")


def test_hrsa_sites_are_virginia_only_deduplicated_and_trimmed():
    sites, _ = build_hrsa()
    assert sorted(sites["site_id"]) == list("ABCDEFG")
    assert sites.set_index("site_id").loc["A", "site_name"] == "Clinic A"


def test_supply_counts_only_active_permanent_service_delivery_sites():
    sites, _ = build_hrsa()
    assert sorted(sites.loc[sites["in_supply_measure"], "site_id"]) == ["A", "B", "F"]


def test_supply_joins_by_fips_and_fills_zero_for_localities_without_sites():
    _, fact = build_hrsa()
    assert len(fact) == 133
    assert fact.loc[RICHMOND_CITY, "supply_sites"] == 2
    assert fact.loc[RICHMOND_COUNTY, "supply_sites"] == 1
    assert fact.loc["51001", "supply_sites"] == 0
    assert fact["supply_sites"].dtype == "int64" and not fact["supply_sites"].isna().any()


def test_site_with_fips_outside_the_133_is_kept_but_not_counted(caplog):
    sites, fact = build_hrsa()
    g = sites.set_index("site_id").loc["G"]
    assert not g["fips_matched"] and not g["in_supply_measure"]
    assert "51515" not in fact.index
    assert "outside the 133 localities" in caplog.text


# ---------- raw inputs and the full run ----------

def csv_bytes(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


@pytest.fixture
def raw_folder(tmp_path, make_shapefile_zip):
    """Write a valid raw file for every source and log them like real downloads."""
    raw, log = tmp_path / "raw", tmp_path / "raw" / "download_log.csv"
    raw.mkdir()
    for name in ("acs_s2701", "acs_s1701"):
        df = acs_frame(name)
        (raw / config.SOURCES[name].filename(TODAY)).write_text(json.dumps([list(df.columns), *df.values.tolist()]))
    (raw / config.SOURCES["places"].filename(TODAY)).write_bytes(csv_bytes(places_frame().to_dict("records")))
    (raw / config.SOURCES["rucc"].filename(TODAY)).write_bytes(csv_bytes(rucc_frame().to_dict("records")))
    (raw / config.SOURCES["hrsa"].filename(TODAY)).write_bytes(csv_bytes(HRSA_ROWS))
    b = boundaries_frame()
    make_shapefile_zip(raw / config.SOURCES["boundaries"].filename(TODAY),
                       [("STATEFP", 2), ("GEOID", 5), ("NAMELSAD", 30), ("LSAD", 2), ("ALAND", 16)],
                       b[["STATEFP", "GEOID", "NAMELSAD", "LSAD", "ALAND"]].values.tolist())
    for source in config.SOURCES.values():
        path = raw / source.filename(TODAY)
        download_log.append(download_log.build_entry(source, path, source.url, None), log)
    return raw, log


def test_missing_download_explains_how_to_fix(tmp_path):
    with pytest.raises(CleaningError, match="python -m scripts.download --source rucc"):
        raw_inputs.load_input("rucc", tmp_path, tmp_path / "download_log.csv")


def test_edited_raw_file_is_refused(raw_folder):
    raw, log = raw_folder
    path = raw / config.SOURCES["rucc"].filename(TODAY)
    path.write_bytes(path.read_bytes() + b"51999,VA,X,RUCC_2023,1\n")
    with pytest.raises(CleaningError, match="changed after it was downloaded"):
        raw_inputs.load_input("rucc", raw, log)


def test_raw_file_failing_its_checks_is_refused(raw_folder):
    raw, log = raw_folder
    path = raw / config.SOURCES["rucc"].filename(TODAY)
    path.write_bytes(csv_bytes(rucc_frame(skip={"51004"}).to_dict("records")))
    download_log.append(download_log.build_entry(config.SOURCES["rucc"], path, "u", None), log)
    with pytest.raises(CleaningError, match="fails its download checks"):
        raw_inputs.load_input("rucc", raw, log)


def test_full_run_writes_five_tables_with_text_fips(raw_folder, tmp_path):
    raw, log = raw_folder
    out = tmp_path / "processed"
    assert clean_data.main([], raw, log, out) == 0
    written = sorted(p.name for p in out.iterdir())
    assert written == ["acs_va.csv", "dim_geography.csv", "fact_supply.csv", "hrsa_sites_va.csv", "places_va.csv"]
    for name in ("dim_geography", "acs_va", "places_va", "fact_supply"):
        table = pd.read_csv(out / f"{name}.csv", dtype={"fips": str})
        assert len(table) == 133 and table["fips"].is_unique and table["fips"].str.fullmatch(r"51\d{3}").all()
    assert raw.joinpath(config.SOURCES["rucc"].filename(TODAY)).exists()
    assert not list(out.glob("*.part"))


def test_failed_run_changes_nothing(raw_folder, tmp_path):
    raw, log = raw_folder
    out = tmp_path / "processed"
    clean_data.main([], raw, log, out)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    bad = raw / config.SOURCES["places"].filename(TODAY)
    bad.write_bytes(csv_bytes(places_frame(drop={("51009", "DIABETES", "AgeAdjPrv")}).to_dict("records")))
    download_log.append(download_log.build_entry(config.SOURCES["places"], bad, "u", None), log)
    assert clean_data.main([], raw, log, out) == 1
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
