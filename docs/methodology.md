# Methodology

How the Care Access Gap Dashboard data is obtained, cleaned and checked, what each figure means, and
what it cannot tell you. Column-level definitions are in [data_dictionary.md](data_dictionary.md);
download dates, URLs and checksums are in `data/raw/download_log.csv`.

Items marked **To decide** or **To verify** are open; resolve them before publishing the dashboard.

## 1. Geography

The unit of analysis is the Virginia **locality**: 95 counties and 38 independent cities, 133 in total.
Independent cities are county-equivalents: they are not part of any county, so a city and the county
around it are separate rows with separate figures.

The master list of localities is the Census cartographic boundary file. Every other table is joined to
it by 5-character FIPS code and must contain exactly the same 133 codes. Names are never used for
joins because four county/city pairs share a name (Fairfax, Franklin, Richmond, Roanoke), and some
sources (PLACES) give only the short name, e.g. "Richmond".

## 2. Data sources

| Source | Release / vintage | Period the data describes | What we use |
|--------|-------------------|---------------------------|-------------|
| Census ACS 5-year subject tables S2701, S1701 | 2020-2024 | 60 months, 2020–2024 | Uninsured and poverty counts, percentages, margins of error |
| CDC PLACES, county data (Socrata `swc5-untb`) | 2025 release | 2023 for both measures used | Age-adjusted prevalence of diagnosed diabetes and high blood pressure |
| HRSA Health Center Service Delivery and Look-Alike Sites | Snapshot on the download date | Sites listed on that date | Health center site locations and attributes |
| USDA ERS Rural-Urban Continuum Codes | 2023 | Based on 2020 Census population | RUCC code, description, 2020 population |
| Census cartographic boundary file, counties 1:500,000 | 2024 | 2024 boundaries | The 133 localities, names, county/city type, land area, map shapes |

The boundary vintage (2024) is set to match the ACS end year, so ACS geography and the map agree.

The release year is not the data year: the PLACES 2025 release contains 2023 estimates for the two
measures used. The download step refuses a PLACES dataset whose title does not name the configured
release, so a future release cannot silently replace this one.

## 3. Download

`python -m scripts.download` saves each file exactly as received into `data/raw/` and records the URL,
version, UTC time, row count, size and SHA-256 checksum in `data/raw/download_log.csv`. Raw files are
never edited. If a later download on the same day differs, the earlier file is moved to
`data/raw/superseded/` instead of being overwritten, so every logged checksum still matches a file.

After each download, checks confirm the file is real data (not an HTML error page), parses, and has
what the dashboard needs: for example 133 Virginia localities in ACS, RUCC and the boundary file, and
133 localities for each PLACES measure and value type. PLACES is downloaded in pages of 50,000 rows
and the total is compared with the dataset's row count, because the API otherwise returns only 1,000
rows without warning.

## 4. Cleaning

`python -m scripts.clean_data` builds the five tables in `data/processed/`:

1. **Choose inputs.** For each source, the newest file in the download log is used. It is refused if
   it is missing, its checksum no longer matches the log (it was edited), or it fails its download
   checks.
2. **Read everything as text.** FIPS codes and other identifiers are never converted to numbers, so
   leading characters are never lost. Numbers are parsed column by column: a blank becomes missing,
   and any other non-number stops the run rather than being silently dropped.
3. **Build each table** (see sections 5–8) and left-join it onto the 133-locality list by FIPS.
4. **Check every table** has exactly one row per locality, with FIPS as 5-digit text starting with 51.
5. **Write all or nothing.** Tables are written only if every one passed; a failed run leaves the
   previous files untouched.

`python -m scripts.validate_data` then re-reads the written files as Power BI will and checks them
independently, including consistency between tables (for example, the site counts in `fact_supply`
must add up to the flagged sites in `hrsa_sites_va`). Results go into
[validation_report.md](validation_report.md).

## 5. Insurance and poverty (acs_va)

**Measures.** Uninsured people and percent uninsured among the civilian noninstitutionalized
population (S2701); people below the poverty level and percent below poverty among the population for
whom poverty status is determined (S1701). Percentages are used as published by the Census Bureau,
not recalculated.

**Margins of error.** ACS margins of error are published at 90% confidence. The coefficient of
variation is calculated as

    CV = (MOE / 1.645) / estimate

and stored as a fraction (0.12 = 12%). It is left missing when the estimate is missing or 0.

**Annotation codes.** The Census API returns negative codes instead of numbers when a value is not
available. The documented codes, from the Census page *Notes on ACS Estimate and Annotation Values*
(checked 2026-11-10), are:

| Code | Symbol | Meaning |
|------|--------|---------|
| -999999999 | N | Too few sample cases in the geography |
| -888888888 | (X) | Not applicable or not available |
| -666666666 | - | Estimate could not be computed (too few observations) |
| -555555555 | ***** | MOE not appropriate: the estimate is controlled to an independent population estimate |
| -333333333 | *** | MOE could not be computed (median in an open-ended interval) |
| -222222222 | ** | MOE could not be computed (too few observations) |

None of the ACS measures used can be negative, so **every** negative value, documented or not,
becomes missing; none becomes zero. The download check reports documented codes and fails on
undocumented ones, so an unexpected code is investigated rather than silently removed.
`-777777777` is not listed on the Census page and is therefore treated as undocumented.

**Decision (2026-11-10): `-555555555` in margins of error stays missing.** The Census Bureau says a
controlled estimate "has no sampling error and the margin of error may be treated as zero". We still
store it as missing, not 0, so that every annotation code is handled by one rule (all negatives become
missing) and no value in `acs_va` is invented by the pipeline. Consequences:
- the `_moe` and `_cv` columns are blank for controlled estimates, even though these are the most
  reliable values in the table;
- reliability visuals and tooltips must show a blank CV as "controlled estimate / no CV", not as
  "unreliable" or "unknown";
- the number of blank MOEs per column is listed in [validation_report.md](validation_report.md) after
  each run.

**Reliability (suggested convention, To decide).** A common practice for ACS is CV < 12% reliable,
12–40% use with caution, > 40% unreliable. These thresholds are a convention, not a Census Bureau rule.

## 6. Chronic disease (places_va)

PLACES estimates are **model-based**, not direct survey counts: CDC estimates county prevalence from
Behavioral Risk Factor Surveillance System (BRFSS) survey data combined with population data. Only the
**age-adjusted** values (`AgeAdjPrv`) are used, so localities with older or younger populations can be
compared fairly. Crude prevalence is downloaded but not used.

Confidence limits are carried through as published. A blank value stays missing.

**To verify** on the PLACES methodology page and record here: the confidence level of the published
limits, and the standard population used for age adjustment.

## 7. Health center supply (hrsa_sites_va, fact_supply)

**Sites.** All Virginia rows from the HRSA site list, with duplicate `site_id` values removed (first
row kept; the download check reports how many). Federally Qualified Health Centers and FQHC
Look-Alikes are both included.

**Supply measure.** A site counts toward `supply_sites` only if all of these hold:

| Field | Counted values | Why |
|-------|----------------|-----|
| `status` | Active | Terminated or pending sites do not serve patients today |
| `location_type` | Permanent | Mobile vans and seasonal sites are not a fixed, year-round point of access |
| `site_type` | Service Delivery Site, Administrative/Service Delivery Site | Both see patients; purely Administrative offices do not |

and its FIPS is one of the 133 localities. The rule is set in `config.HRSA_SUPPLY_RULES`.

In the snapshot used during development (2026-11-10) Virginia had 247 sites: 186 met the definition
(157 Service Delivery, 29 Administrative/Service Delivery), 23 were purely Administrative and 38 were
mobile or seasonal. The 186 sites were in 81 localities; the other 52 have a count of 0.

**Counts per locality.** `fact_supply` starts from all 133 localities and fills 0 where there are no
sites (a locality with no sites has zero supply, not unknown supply). `active_sites_any_type` counts
every active site regardless of type, for context.

## 8. Rurality (dim_geography)

The RUCC code (1–9) classifies each locality by metro-area population and, for nonmetro localities,
urban population and adjacency to a metro area. Codes 1–3 are **Metro** and 4–9 **Nonmetro**,
following USDA. Land area is converted from square meters to square miles.

## 9. Dashboard measures

Rates are calculated as DAX measures, not stored in the CSVs, so they stay correct under any filter.
**To decide:** the exact definition of the "care access gap". Candidate measures, each a ratio of two
summed columns so it aggregates correctly across selected localities:

```
Sites per 10,000 uninsured = DIVIDE ( SUM ( fact_supply[supply_sites] ), SUM ( acs_va[uninsured] ) ) * 10000
Uninsured rate             = DIVIDE ( SUM ( acs_va[uninsured] ), SUM ( acs_va[insurance_universe] ) )
Poverty rate               = DIVIDE ( SUM ( acs_va[below_poverty] ), SUM ( acs_va[poverty_universe] ) )
```

Do not average the published percentages (`uninsured_pct`, `below_poverty_pct`) across localities;
that gives every locality equal weight regardless of size. PLACES prevalence cannot be summed or
re-weighted from this data and should be shown per locality only.

## 10. Limitations

- **Different time periods.** ACS covers 2020–2024, PLACES describes 2023, RUCC uses 2020 population,
  and HRSA is a snapshot of the download date. The dashboard combines the latest available of each,
  not one common year.
- **Small-area uncertainty.** Small localities have large ACS margins of error; check the CV before
  ranking them. PLACES values are model estimates with their own uncertainty.
- **Sites, not capacity.** A site count ignores opening hours (HRSA publishes `Operating Hours per
  Week`, which this project does not use yet), number of providers, services offered and patients
  served. One large center and one small clinic each count as 1.
- **HRSA health centers only.** Free clinics, hospital outpatient departments, rural health clinics
  and private practices are not included, so `supply_sites` is a measure of the safety-net health
  center network, not of all primary care.
- **Locality borders.** People cross borders for care, especially between small independent cities and
  the counties around them. A city with no site may be next to one just across the line.
- **Snapshot changes.** HRSA's list changes over time; figures depend on the download date shown in
  `download_log.csv`.
- **Unmatched FIPS.** A site coded to a FIPS that is not one of the 133 (for example the former
  Bedford city, `51515`) is kept in `hrsa_sites_va` but not counted. None occurred in the development
  snapshot.
