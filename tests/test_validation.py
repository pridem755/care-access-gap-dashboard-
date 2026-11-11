"""Tests for the validation step: a valid set of processed files, then one broken rule per test."""
import pandas as pd
import pytest

from scripts import config, validate_data
from scripts.validation import markdown_report

RICHMOND_COUNTY, RICHMOND_CITY = "51159", "51760"
LOCALITIES = [f"51{i:03d}" for i in range(1, 132)] + [RICHMOND_COUNTY, RICHMOND_CITY]
SITE_FIELDS = list(config.HRSA_SITE_FIELDS.values())


def valid_tables():
    """Return a consistent set of processed tables that passes every check."""
    types = ["County"] * 95 + ["City"] * 38
    dim = pd.DataFrame({
        "fips": LOCALITIES, "locality_name": [f"Place {f} {t}" for f, t in zip(LOCALITIES, types)],
        "locality_type": types, "metro_status": "Metro", "rucc_code": "1",
        "rucc_description": "Metro", "population_2020": "1000", "land_area_sq_mi": "10.5",
    })
    acs = pd.DataFrame({"fips": LOCALITIES})
    for name in [*config.ACS_S2701_VARIABLES.values(), *config.ACS_S1701_VARIABLES.values()]:
        acs[name] = "10.0" if name.endswith("_pct") else ("1000" if name.endswith("universe") else "100")
        acs[f"{name}_moe"], acs[f"{name}_cv"] = "10", "0.0608"
    places = pd.DataFrame({"fips": LOCALITIES})
    for name in config.PLACES_MEASURES.values():
        places[f"{name}_pct"], places[f"{name}_ci_low"], places[f"{name}_ci_high"] = "10.0", "8.0", "12.0"
        places[f"{name}_data_year"] = "2023"
    sites = pd.DataFrame([
        {**dict.fromkeys(SITE_FIELDS, ""), "site_id": sid, "fips": fips, "status": status,
         "site_type": "Service Delivery Site", "location_type": "Permanent",
         "latitude": "37.54", "longitude": "-77.43", "fips_matched": matched, "in_supply_measure": supply,
         "duplicate_key": f"{fips}|{sid}", "counted_once": supply}
        for sid, fips, status, matched, supply in [
            ("A", RICHMOND_CITY, "Active", "True", "True"),
            ("B", RICHMOND_CITY, "Active", "True", "True"),
            ("C", RICHMOND_COUNTY, "Terminated", "True", "False"),
            ("D", "51515", "Active", "False", "False"),
        ]
    ])
    fact = pd.DataFrame({"fips": LOCALITIES, "supply_sites": "0", "active_sites_any_type": "0"})
    fact.loc[fact["fips"] == RICHMOND_CITY, ["supply_sites", "active_sites_any_type"]] = "2"
    duplicates = pd.DataFrame(columns=["duplicate_key", "site_id", "site_name", "program_type", "address", "fips",
                                       "counted_once"])
    return {"dim_geography": dim, "acs_va": acs, "places_va": places, "hrsa_sites_va": sites, "fact_supply": fact,
            "supply_duplicates": duplicates}


def write(tables, folder):
    folder.mkdir(exist_ok=True)
    for name, df in tables.items():
        df.to_csv(folder / f"{name}.csv", index=False)
    return folder


def failures(tmp_path, tables):
    """Write the tables, run validation, and return the names of failed checks."""
    results, _, _ = validate_data.validate(write(tables, tmp_path / "processed"))
    return {(table, r.name) for table, rs in results.items() for r in rs if not r.passed}


def broken(table, column, row, value):
    tables = valid_tables()
    tables[table].loc[row, column] = value
    return tables


def test_valid_tables_pass(tmp_path):
    assert failures(tmp_path, valid_tables()) == set()


def test_empty_folder_fails(tmp_path):
    (tmp_path / "processed").mkdir()
    results, _, _ = validate_data.validate(tmp_path / "processed")
    assert not results["files"][0].passed


def test_missing_one_table_fails(tmp_path):
    folder = write(valid_tables(), tmp_path / "processed")
    (folder / "places_va.csv").unlink()
    assert validate_data.main(["--no-report"], folder) == 1


@pytest.mark.parametrize("value", ["51001.0", "1001", " 51001", "24001"])
def test_fips_not_written_as_5_digit_text_fails(tmp_path, value):
    assert ("acs_va", "fips is 5-character text starting with 51") in failures(tmp_path, broken("acs_va", "fips", 0, value))


def test_duplicate_locality_fails(tmp_path):
    tables = broken("places_va", "fips", 1, LOCALITIES[0])
    assert ("places_va", "exactly 133 unique localities matching dim_geography") in failures(tmp_path, tables)


def test_table_with_a_locality_not_in_dim_fails(tmp_path):
    tables = valid_tables()
    tables["fact_supply"].loc[0, "fips"] = "51999"
    assert ("fact_supply", "exactly 133 unique localities matching dim_geography") in failures(tmp_path, tables)


@pytest.mark.parametrize("value", ["-666666666", "-1"])
def test_negative_or_annotation_code_fails(tmp_path, value):
    assert ("acs_va", "no negative values or annotation codes") in failures(tmp_path, broken("acs_va", "uninsured", 3, value))


def test_text_in_a_numeric_column_fails(tmp_path):
    assert ("acs_va", "numeric columns contain only numbers or blanks") in failures(
        tmp_path, broken("acs_va", "uninsured_pct", 0, "N/A"))


def test_count_above_its_universe_fails(tmp_path):
    assert ("acs_va", "counts do not exceed their population universe") in failures(
        tmp_path, broken("acs_va", "uninsured", 0, "5000"))


def test_percentage_above_100_fails(tmp_path):
    assert ("places_va", "prevalence and limits are between 0 and 100") in failures(
        tmp_path, broken("places_va", "diabetes_pct", 0, "101"))


def test_value_outside_confidence_interval_fails(tmp_path):
    assert ("places_va", "ci_low <= value <= ci_high") in failures(tmp_path, broken("places_va", "diabetes_pct", 0, "7.5"))


def test_blank_site_count_fails(tmp_path):
    assert ("fact_supply", "site counts are whole numbers, never blank") in failures(
        tmp_path, broken("fact_supply", "supply_sites", 5, ""))


def test_supply_total_must_match_counted_once_sites(tmp_path):
    assert ("fact_supply", "supply_sites total equals counted_once sites") in failures(
        tmp_path, broken("fact_supply", "supply_sites", 0, "1"))


def test_terminated_site_counted_in_supply_fails(tmp_path):
    tables = broken("hrsa_sites_va", "status", 0, "Terminated")
    assert ("hrsa_sites_va", "supply sites are active, permanent, service-delivery") in failures(tmp_path, tables)


def test_duplicate_site_id_fails(tmp_path):
    assert ("hrsa_sites_va", "site_id is unique") in failures(tmp_path, broken("hrsa_sites_va", "site_id", 1, "A"))


def test_site_outside_virginia_fails(tmp_path):
    assert ("hrsa_sites_va", "matched sites have coordinates inside Virginia") in failures(
        tmp_path, broken("hrsa_sites_va", "latitude", 0, "40.7"))


def test_unmatched_site_counted_fails(tmp_path):
    tables = broken("hrsa_sites_va", "in_supply_measure", 3, "True")
    tables["fact_supply"].loc[tables["fact_supply"]["fips"] == RICHMOND_CITY, "supply_sites"] = "2"
    assert ("hrsa_sites_va", "no unmatched site is counted") in failures(tmp_path, tables)


def test_wrong_county_city_split_fails(tmp_path):
    assert ("dim_geography", "county/city split matches Virginia") in failures(
        tmp_path, broken("dim_geography", "locality_type", 0, "City"))


def test_metro_status_must_follow_rucc(tmp_path):
    assert ("dim_geography", "metro_status agrees with rucc_code") in failures(
        tmp_path, broken("dim_geography", "rucc_code", 0, "7"))


def test_missing_or_extra_column_fails(tmp_path):
    tables = valid_tables()
    tables["acs_va"] = tables["acs_va"].drop(columns="uninsured_cv").assign(note="x")
    results, _, _ = validate_data.validate(write(tables, tmp_path / "processed"))
    detail = results["acs_va"][0].detail
    assert not results["acs_va"][0].passed and "uninsured_cv" in detail and "note" in detail


def test_report_section_is_replaced_and_manual_notes_kept(tmp_path):
    folder = write(valid_tables(), tmp_path / "processed")
    report = tmp_path / "validation_report.md"
    report.write_text("# Validation report\n\n| Date | Check |\n|---|---|\n| today | my manual check |\n")
    assert validate_data.main([], folder, report) == 0
    assert validate_data.main([], folder, report) == 0
    text = report.read_text()
    assert text.count(markdown_report.START) == 1 and "my manual check" in text
    assert "**Result: PASS**" in text


def test_failed_run_is_recorded_in_the_report(tmp_path):
    folder = write(broken("acs_va", "uninsured", 0, "-1"), tmp_path / "processed")
    report = tmp_path / "validation_report.md"
    assert validate_data.main([], folder, report) == 1
    assert "**Result: FAIL**" in report.read_text() and "| acs_va | no negative values" in report.read_text()


def test_blanks_are_listed_as_missing_values(tmp_path):
    folder = write(broken("acs_va", "uninsured_moe", 0, ""), tmp_path / "processed")
    _, missing, _ = validate_data.validate(folder)
    assert ("acs_va", "uninsured_moe", 1, 133) in missing


def merged_tables(listed=True):
    """Return valid tables where sites A and B share a key and only A is counted."""
    tables = valid_tables()
    sites = tables["hrsa_sites_va"]
    sites.loc[sites["site_id"] == "B", ["duplicate_key", "counted_once"]] = [f"{RICHMOND_CITY}|A", "False"]
    sites.loc[sites["site_id"] == "A", "duplicate_key"] = f"{RICHMOND_CITY}|A"
    tables["fact_supply"].loc[tables["fact_supply"]["fips"] == RICHMOND_CITY, "supply_sites"] = "1"
    if listed:
        rows = sites[sites["site_id"].isin(["A", "B"])]
        tables["supply_duplicates"] = rows[tables["supply_duplicates"].columns.tolist()]
    return tables


def test_a_merged_duplicate_passes(tmp_path):
    assert failures(tmp_path, merged_tables()) == set()


def test_duplicates_file_missing_a_merged_pair_fails(tmp_path):
    assert ("supply_duplicates", "lists exactly the supply sites sharing a duplicate_key") in failures(
        tmp_path, merged_tables(listed=False))


def test_counted_once_on_a_site_outside_the_supply_measure_fails(tmp_path):
    assert ("hrsa_sites_va", "counted_once is True only for supply sites") in failures(
        tmp_path, broken("hrsa_sites_va", "counted_once", 2, "True"))


def test_a_duplicate_key_counted_twice_fails(tmp_path):
    tables = broken("hrsa_sites_va", "duplicate_key", 1, f"{RICHMOND_CITY}|A")
    found = failures(tmp_path, tables)
    assert ("hrsa_sites_va", "each duplicate_key is counted at most once") in found
    assert ("fact_supply", "supply_sites equals distinct duplicate_key per locality") in found


def test_supply_sites_moved_to_another_locality_fails_even_when_the_total_matches(tmp_path):
    tables = valid_tables()
    fact = tables["fact_supply"]
    fact.loc[fact["fips"] == RICHMOND_CITY, "supply_sites"] = "1"
    fact.loc[fact["fips"] == RICHMOND_COUNTY, ["supply_sites", "active_sites_any_type"]] = "1"
    found = failures(tmp_path, tables)
    assert ("fact_supply", "supply_sites total equals counted_once sites") not in found
    assert ("fact_supply", "supply_sites equals distinct duplicate_key per locality") in found
    assert ("fact_supply", "supply_sites <= supply site records per locality") in found


def test_report_says_zero_duplicates_when_there_are_none(tmp_path):
    report = tmp_path / "validation_report.md"
    assert validate_data.main([], write(valid_tables(), tmp_path / "processed"), report) == 0
    assert "0 duplicate site records." in report.read_text()


def test_report_lists_merged_duplicates(tmp_path):
    report = tmp_path / "validation_report.md"
    assert validate_data.main([], write(merged_tables(), tmp_path / "processed"), report) == 0
    text = report.read_text()
    assert "| duplicate site records merged | 1 |" in text and "0 duplicate site records." not in text
