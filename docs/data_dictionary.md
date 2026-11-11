# Data dictionary

This document describes the six tables in `data/processed/`. They are produced by
`python -m scripts.clean_data` and checked by `python -m scripts.validate_data`. If a column is added
or renamed in the code, this document must be updated too; one of the tests checks that every column
is listed here.

## General notes

The Type column gives the type to set for each column in Power Query. Every `fips` column must be
changed to Text by hand, because Power BI would otherwise read a code such as 51001 as a number.

A blank cell always means the value is missing. It never means zero. The only place where zero is
filled in is the two site counts in `fact_supply`, because a locality with no health center sites
genuinely has zero sites.

All tables are linked by the `fips` column. `dim_geography` has one row per locality, and each of the
other tables connects to it on `fips`. `acs_va`, `places_va` and `fact_supply` also have one row per
locality, while `hrsa_sites_va` and `supply_duplicates` can have several rows for the same locality.

Tables must never be linked by locality name. Virginia has four counties and cities that share a
name: Fairfax (51059 and 51600), Franklin (51067 and 51620), Richmond (51159 and 51760) and Roanoke
(51161 and 51770). Bedford city (51515) became part of Bedford County (51019) in 2013 and is not one
of the 133 localities.

## dim_geography.csv

One row for each of Virginia's 133 localities: 95 counties and 38 independent cities.

| Column | Type | Meaning | Source |
|--------|------|---------|--------|
| `fips` | Text | Five-digit state and county code, always starting with 51. This is the key every other table joins on. | Census boundary file, GEOID |
| `locality_name` | Text | Full name, such as "Richmond city" or "Richmond County". Every name is different. | Census boundary file, NAMELSAD |
| `locality_type` | Text | Either County or City. | Census boundary file, LSAD (code 06 is a county, 25 is a city) |
| `metro_status` | Text | Metro for RUCC codes 1 to 3, Nonmetro for codes 4 to 9, blank if there is no RUCC code. | Calculated from `rucc_code` |
| `rucc_code` | Whole number | USDA Rural-Urban Continuum Code for 2023, from 1 (most urban) to 9 (most rural). | USDA RUCC file |
| `rucc_description` | Text | USDA's description of the RUCC code. | USDA RUCC file |
| `population_2020` | Whole number | 2020 Census population, as used by USDA to assign the code. | USDA RUCC file |
| `land_area_sq_mi` | Decimal number | Land area in square miles, rounded to two decimals. | Census boundary file, ALAND, converted from square meters |

## acs_va.csv

One row per locality, from the American Community Survey 2020-2024 five-year estimates.

| Column | Type | Meaning | Census variable |
|--------|------|---------|-----------------|
| `fips` | Text | Locality code, linking to `dim_geography`. | state and county codes combined |
| `insurance_universe` | Whole number | Civilian population not living in institutions. This is the population the insurance figures describe. | S2701_C01_001E |
| `uninsured` | Whole number | Number of people with no health insurance. | S2701_C04_001E |
| `uninsured_pct` | Decimal number | Percentage of people with no health insurance, as published by the Census Bureau. | S2701_C05_001E |
| `poverty_universe` | Whole number | Population whose poverty status can be determined. This is the population the poverty figures describe. | S1701_C01_001E |
| `below_poverty` | Whole number | Number of people with income below the poverty level. | S1701_C02_001E |
| `below_poverty_pct` | Decimal number | Percentage of people below the poverty level, as published. | S1701_C03_001E |

Each of the six measures above also has two companion columns. The column ending in `_moe` is the
margin of error published by the Census Bureau, at 90 percent confidence, in the same units as the
measure. The column ending in `_cv` is the coefficient of variation, stored as a fraction, so 0.10
means 10 percent. The companion columns are:

| Measure | Margin of error | Coefficient of variation |
|---------|-----------------|--------------------------|
| insurance_universe | `insurance_universe_moe` | `insurance_universe_cv` |
| uninsured | `uninsured_moe` | `uninsured_cv` |
| uninsured_pct | `uninsured_pct_moe` | `uninsured_pct_cv` |
| poverty_universe | `poverty_universe_moe` | `poverty_universe_cv` |
| below_poverty | `below_poverty_moe` | `below_poverty_cv` |
| below_poverty_pct | `below_poverty_pct_moe` | `below_poverty_pct_cv` |

Where the Census Bureau published a special code instead of a number, the cell is blank. The
methodology explains these codes.

## places_va.csv

One row per locality, from the CDC PLACES 2025 release. The values are age-adjusted percentages of
adults aged 18 and over. Crude percentages are downloaded but not used.

| Column | Type | Meaning | PLACES field |
|--------|------|---------|--------------|
| `fips` | Text | Locality code, linking to `dim_geography`. | locationid |
| `diabetes_pct` | Decimal number | Percentage of adults who have been diagnosed with diabetes. | data_value for measure DIABETES |
| `diabetes_ci_low` | Decimal number | Lower confidence limit for the diabetes figure, as published by CDC. | low_confidence_limit |
| `diabetes_ci_high` | Decimal number | Upper confidence limit for the diabetes figure, as published by CDC. | high_confidence_limit |
| `diabetes_data_year` | Whole number | The year the diabetes estimate describes, which is not the same as the release year. | year |
| `high_blood_pressure_pct` | Decimal number | Percentage of adults who have high blood pressure. | data_value for measure BPHIGH |
| `high_blood_pressure_ci_low` | Decimal number | Lower confidence limit for the blood pressure figure. | low_confidence_limit |
| `high_blood_pressure_ci_high` | Decimal number | Upper confidence limit for the blood pressure figure. | high_confidence_limit |
| `high_blood_pressure_data_year` | Whole number | The year the blood pressure estimate describes. | year |

## hrsa_sites_va.csv

One row per health center site in Virginia, from the HRSA list of Health Center Service Delivery and
Look-Alike Sites, with duplicate site IDs removed. The table includes sites that are not counted in
the supply measure, so that it is clear which sites were left out and why. Filter on
`in_supply_measure` to see only the counted sites.

| Column | Type | Meaning | HRSA column |
|--------|------|---------|-------------|
| `site_id` | Text | Unique identifier for the site. | BPHC Assigned Number |
| `site_name` | Text | Name of the site. | Site Name |
| `health_center_name` | Text | Organization that runs the site. | Health Center Name |
| `program_type` | Text | Whether the site belongs to a federally funded health center or a Look-Alike. | Health Center Type |
| `status` | Text | Active, Pending Verification, Terminated or Unknown. | Site Status Description |
| `site_type` | Text | Service Delivery Site, Administrative/Service Delivery Site, or Administrative. | Health Center Type Description |
| `location_type` | Text | Permanent, Seasonal, Mobile Van or Unknown. | Health Center Location Type Description |
| `address` | Text | Street address. | Site Address |
| `city` | Text | City. | Site City |
| `postal_code` | Text | ZIP code, sometimes with the four-digit extension. Keep this as Text. | Site Postal Code |
| `fips` | Text | Code of the locality the site is in, linking to `dim_geography`. | State and County Federal Information Processing Standard Code |
| `latitude` | Decimal number | Latitude in decimal degrees, based on the site address. | Geocoding Artifact Address Primary Y Coordinate |
| `longitude` | Decimal number | Longitude in decimal degrees, based on the site address. | Geocoding Artifact Address Primary X Coordinate |
| `fips_matched` | True/False | True when the site's code is one of the 133 localities. | Calculated |
| `in_supply_measure` | True/False | True when the site meets the supply rule. The methodology gives the rule. | Calculated |
| `duplicate_key` | Text | The locality code, address and site name joined with a vertical bar, after lowercasing and removing periods, commas, apostrophes, # signs and extra spaces. Records with the same key are treated as one clinic. If the address or the name is blank, the key is the locality code and the site ID instead, so the record never matches another. Used only for matching; the address and name columns keep their original text. | Calculated |
| `counted_once` | True/False | True for the one record of each `duplicate_key` that is counted in `fact_supply`, chosen as the lowest `site_id` among the records that meet the supply rule. Always False when `in_supply_measure` is False. | Calculated |

## fact_supply.csv

One row per locality, including localities that have no health center sites.

| Column | Type | Meaning |
|--------|------|---------|
| `fips` | Text | Locality code, linking to `dim_geography`. |
| `supply_sites` | Whole number | Number of distinct active, permanent sites that serve patients, with a clinic listed under more than one site ID counted once. This equals the number of rows in `hrsa_sites_va` where `counted_once` is True. This is the main supply measure. |
| `active_sites_any_type` | Whole number | Number of active site records of any kind, including administrative offices, mobile vans and seasonal sites. Duplicate records are not merged here. Shown for context. |

## supply_duplicates.csv

The site records that were merged in the supply count. It lists every site that meets the supply rule
and shares its `duplicate_key` with at least one other such site, so each group has two or more rows.
The file is written on every run. When there are no duplicates it has only its header row, and the
validation report says "0 duplicate site records".

| Column | Type | Meaning |
|--------|------|---------|
| `duplicate_key` | Text | The shared key, as in `hrsa_sites_va`. |
| `site_id` | Text | Site ID of the record. |
| `site_name` | Text | Name of the site, as HRSA wrote it. |
| `program_type` | Text | Whether the record belongs to a federally funded health center or a Look-Alike. |
| `address` | Text | Street address, as HRSA wrote it. |
| `fips` | Text | Locality code, linking to `dim_geography`. |
| `counted_once` | True/False | True for the record that is counted, False for the records merged into it. |

---

Prepared by Pride Mudondo.
