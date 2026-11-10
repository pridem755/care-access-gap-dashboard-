# Data dictionary

The five tables in `data/processed/`, as written by `python -m scripts.clean_data` and checked by
`python -m scripts.validate_data`. Column names here must match the code; `tests/test_docs.py` fails
if a column is added or renamed without updating this file.

**Types** are the Power BI types to set in Power Query. Every `fips` column must be set to **Text**
by hand: automatic type detection would turn `51001` into the number 51001 and break relationships.

A blank cell always means *missing*, never zero. The only columns where 0 is filled in are the two
site counts in `fact_supply` (a locality with no sites has 0 sites).

## Model

```
                    dim_geography (1 row per locality, key: fips)
                   /        |          |              \
            acs_va     places_va    fact_supply     hrsa_sites_va
           (1 : 1)      (1 : 1)       (1 : 1)       (1 : many)
```

All relationships are on `fips`, single direction from `dim_geography`. Never relate tables on a
locality name: Virginia has four county/city pairs with the same name — Fairfax (`51059` / `51600`),
Franklin (`51067` / `51620`), Richmond (`51159` / `51760`) and Roanoke (`51161` / `51770`). Bedford
city (`51515`) merged into Bedford County (`51019`) in 2013 and is no longer one of the 133.

## dim_geography.csv

One row for each of Virginia's 133 localities (95 counties, 38 independent cities).

| Column | Type | Description | Source | Values / units |
|--------|------|-------------|--------|----------------|
| `fips` | Text | State + county FIPS code; primary key | Boundary file `GEOID` | 5 digits, starts with `51` |
| `locality_name` | Text | Full name, unique, e.g. "Richmond city", "Richmond County" | Boundary file `NAMELSAD` | |
| `locality_type` | Text | County or independent city | Boundary file `LSAD` (`06` → County, `25` → City) | `County`, `City` |
| `metro_status` | Text | Metropolitan status derived from the RUCC code | `rucc_code` 1–3 → Metro, 4–9 → Nonmetro | `Metro`, `Nonmetro`, blank if no RUCC code |
| `rucc_code` | Whole number | Rural-Urban Continuum Code 2023 | RUCC `Attribute = RUCC_2023` | 1 (most urban) to 9 (most rural) |
| `rucc_description` | Text | USDA wording for the RUCC code | RUCC `Attribute = Description` | |
| `population_2020` | Whole number | 2020 Census population used by USDA to assign the code | RUCC `Attribute = Population_2020` | people |
| `land_area_sq_mi` | Decimal number | Land area | Boundary file `ALAND` (m²) ÷ 2,589,988.11 | square miles, 2 decimals |

## acs_va.csv

One row per locality. American Community Survey 2020–2024 5-year estimates. Every estimate has a
margin of error (`_moe`, 90% confidence) and a coefficient of variation (`_cv`).

| Column | Type | Description | ACS variable | Units |
|--------|------|-------------|--------------|-------|
| `fips` | Text | Foreign key to `dim_geography` | `state` + `county` | |
| `insurance_universe` | Whole number | Civilian noninstitutionalized population (the base for insurance figures) | `S2701_C01_001E` | people |
| `uninsured` | Whole number | People with no health insurance coverage | `S2701_C04_001E` | people |
| `uninsured_pct` | Decimal number | Percent uninsured, as published by the Census Bureau | `S2701_C05_001E` | percent (0–100) |
| `poverty_universe` | Whole number | Population for whom poverty status is determined | `S1701_C01_001E` | people |
| `below_poverty` | Whole number | People with income below the poverty level | `S1701_C02_001E` | people |
| `below_poverty_pct` | Decimal number | Percent below the poverty level, as published | `S1701_C03_001E` | percent (0–100) |
| `<measure>_moe` | Whole or decimal number | Margin of error for the estimate, 90% confidence | same code ending in `M` | same units as the estimate |
| `<measure>_cv` | Decimal number | Coefficient of variation = (MOE ÷ 1.645) ÷ estimate | calculated | fraction (0.10 = 10%) |

`<measure>` is each of the six measures above, giving these 12 columns: `insurance_universe_moe`,
`insurance_universe_cv`, `uninsured_moe`, `uninsured_cv`, `uninsured_pct_moe`, `uninsured_pct_cv`,
`poverty_universe_moe`, `poverty_universe_cv`, `below_poverty_moe`, `below_poverty_cv`,
`below_poverty_pct_moe`, `below_poverty_pct_cv`.

Census annotation codes (e.g. `-666666666`) are blank here. See the methodology for which codes exist
and why `-555555555` is blank rather than 0.

## places_va.csv

One row per locality. CDC PLACES 2025 release, county data, **age-adjusted** prevalence among adults
(`datavaluetypeid = AgeAdjPrv`). Crude prevalence is downloaded but not used.

| Column | Type | Description | PLACES field | Units |
|--------|------|-------------|--------------|-------|
| `fips` | Text | Foreign key to `dim_geography` | `locationid` | |
| `diabetes_pct` | Decimal number | Age-adjusted prevalence of diagnosed diabetes, adults 18+ | `data_value` where `measureid = DIABETES` | percent (0–100) |
| `diabetes_ci_low` | Decimal number | Lower confidence limit, as published by CDC | `low_confidence_limit` | percent |
| `diabetes_ci_high` | Decimal number | Upper confidence limit, as published by CDC | `high_confidence_limit` | percent |
| `diabetes_data_year` | Whole number | Year the estimate describes (not the release year) | `year` | e.g. 2023 |
| `high_blood_pressure_pct` | Decimal number | Age-adjusted prevalence of high blood pressure, adults 18+ | `data_value` where `measureid = BPHIGH` | percent (0–100) |
| `high_blood_pressure_ci_low` | Decimal number | Lower confidence limit, as published by CDC | `low_confidence_limit` | percent |
| `high_blood_pressure_ci_high` | Decimal number | Upper confidence limit, as published by CDC | `high_confidence_limit` | percent |
| `high_blood_pressure_data_year` | Whole number | Year the estimate describes | `year` | e.g. 2023 |

## hrsa_sites_va.csv

One row per HRSA health center site in Virginia (Health Center Service Delivery and Look-Alike Sites),
after removing duplicate site IDs. Includes sites that are **not** counted in the supply measure, so
the filter is transparent; use `in_supply_measure` to filter.

| Column | Type | Description | HRSA column | Values |
|--------|------|-------------|-------------|--------|
| `site_id` | Text | Unique site identifier; primary key | `BPHC Assigned Number` | e.g. `BPS-H80-004326` |
| `site_name` | Text | Site name | `Site Name` | |
| `health_center_name` | Text | Organization operating the site | `Health Center Name` | |
| `program_type` | Text | Grant-funded health center or Look-Alike | `Health Center Type` | `Federally Qualified Health Center (FQHC)`, `Federally Qualified Health Center (FQHC) Look-Alike` |
| `status` | Text | Site status | `Site Status Description` | `Active`, `Pending Verification`, `Terminated`, `Unknown` |
| `site_type` | Text | What the site does | `Health Center Type Description` | `Service Delivery Site`, `Administrative/Service Delivery Site`, `Administrative` |
| `location_type` | Text | Kind of location | `Health Center Location Type Description` | `Permanent`, `Seasonal`, `Mobile Van`, `Unknown` |
| `address` | Text | Street address | `Site Address` | |
| `city` | Text | City | `Site City` | |
| `postal_code` | Text | ZIP code, sometimes ZIP+4 | `Site Postal Code` | keep as Text |
| `fips` | Text | County FIPS of the site; foreign key to `dim_geography` | `State and County Federal Information Processing Standard Code` | 5 digits |
| `latitude` | Decimal number | Latitude geocoded from the site address | `Geocoding Artifact Address Primary Y Coordinate` | decimal degrees |
| `longitude` | Decimal number | Longitude geocoded from the site address | `Geocoding Artifact Address Primary X Coordinate` | decimal degrees, negative |
| `fips_matched` | True/False | The site's FIPS is one of the 133 localities | calculated | |
| `in_supply_measure` | True/False | The site counts toward `fact_supply[supply_sites]` | calculated (see methodology) | |

## fact_supply.csv

One row per locality, including localities with no sites (count 0).

| Column | Type | Description | Calculation | Units |
|--------|------|-------------|-------------|-------|
| `fips` | Text | Foreign key to `dim_geography` | | |
| `supply_sites` | Whole number | Sites in the supply measure: active, permanent, service-delivery | count of `hrsa_sites_va` rows with `in_supply_measure = True` | sites, ≥ 0 |
| `active_sites_any_type` | Whole number | All active sites, any site or location type (context) | count of rows with `status = Active` and `fips_matched = True` | sites, ≥ 0 |
