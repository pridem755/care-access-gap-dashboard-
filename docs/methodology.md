# Methodology

This document explains where the dashboard's data comes from, how it is prepared, what each figure
means and where its limits are. The individual columns are described in the
[data dictionary](data_dictionary.md). The exact files used, with their download dates and checksums,
are listed in `data/raw/download_log.csv`. A few questions are still open; they are listed in the
last section.

## Geography

The dashboard reports on Virginia's 133 localities: 95 counties and 38 independent cities. In
Virginia, an independent city is not part of any county, so a city and the county that surrounds it
are reported separately.

The list of localities comes from the Census Bureau's boundary file. Every other table is matched to
that list using the five-digit FIPS code, and each table must contain exactly the same 133 codes.
Locality names are never used for matching, because four county and city pairs share a name
(Fairfax, Franklin, Richmond and Roanoke), and some sources, such as PLACES, give only the short name
"Richmond" without saying which one.

## Data sources

| Source | Version used | Period the data describes |
|--------|--------------|---------------------------|
| Census Bureau American Community Survey, five-year estimates, tables S2701 (health insurance) and S1701 (poverty) | 2020-2024 | The five years from 2020 to 2024 |
| CDC PLACES county data | 2025 release | 2023 for both measures used |
| HRSA Health Center Service Delivery and Look-Alike Sites | The list as it stood on the download date | Sites open on that date |
| USDA Rural-Urban Continuum Codes | 2023 | Based on 2020 Census population |
| Census Bureau county boundary file, 1:500,000 scale | 2024 | 2024 boundaries |

The boundary file year is set to match the last year of the ACS estimates, so the map and the Census
figures use the same boundaries.

The release year of a dataset is not always the year its data describes. The PLACES 2025 release, for
example, contains estimates for 2023. The download step checks that the PLACES dataset it fetches is
the 2025 release, so a newer release cannot replace it without anyone noticing.

## Downloading

`python -m scripts.download` saves each file exactly as the website provides it. Raw files are never
edited. For every download, the pipeline records the address it came from, the version, the time, the
number of rows, the file size and a checksum. If a file is downloaded again on the same day and its
contents have changed, the earlier copy is moved to `data/raw/superseded/` rather than being
overwritten.

After each download, a set of checks confirms that the file contains data rather than an error page
and that it holds what the dashboard needs. For example, the Census, USDA and boundary files must
each cover all 133 localities, and PLACES must have a figure for every locality for both measures.
PLACES is downloaded in batches of 50,000 rows, and the total is compared with the size of the
dataset, because the CDC website otherwise returns only the first 1,000 rows without any warning.

## Cleaning

`python -m scripts.clean_data` turns the raw files into the six tables in `data/processed/`. It
works in five steps.

First, it picks the most recent download of each source and makes sure the file is still there,
has not been changed since it was downloaded and still passes its download checks. If any of this
fails, cleaning stops.

Second, it reads every file as text. Codes such as FIPS are never converted to numbers, so nothing is
lost from them. Numbers are then converted one column at a time. A blank cell becomes a missing value,
and anything else that is not a number stops the run, so that a problem in the data cannot be quietly
dropped.

Third, it builds each table, as described in the sections below, and matches it to the list of 133
localities by FIPS code.

Fourth, it checks that every table has exactly one row for each locality.

Finally, it writes all six tables, but only if every one of them passed. If anything failed, the
files already in `data/processed/` are left as they were, so the folder never holds a mix of old and
new results.

`python -m scripts.validate_data` then reads the finished files again, the way Power BI will, and
checks them separately from the cleaning code. It also checks that the tables agree with each other,
for example that the site counts in `fact_supply` match the sites marked `counted_once` in
`hrsa_sites_va`, both in total and for each locality. The results are written to the [validation report](validation_report.md).

## Health insurance and poverty

The insurance figures come from table S2701 and describe the civilian population that does not live
in institutions. The poverty figures come from table S1701 and describe the people whose poverty
status can be determined, which excludes, for example, people living in college dormitories. The
percentages are used exactly as the Census Bureau published them rather than being recalculated.

Every ACS figure comes with a margin of error at 90 percent confidence. From it, the cleaning step
calculates the coefficient of variation, which shows how precise an estimate is. It is the margin of
error divided by 1.645, then divided by the estimate. It is stored as a fraction, so 0.12 means
12 percent, and it is left blank when the estimate is missing or zero.

### Special Census codes

When a figure is not available, the Census Bureau publishes a special negative code instead of a
number. The Census page "Notes on ACS Estimate and Annotation Values", checked on 10 November 2026,
lists these six:

| Code | Meaning |
|------|---------|
| -999999999 | Too few sample cases in the area to show an estimate |
| -888888888 | Not applicable or not available |
| -666666666 | The estimate could not be calculated because there were too few observations |
| -555555555 | A margin of error is not appropriate because the estimate is controlled to an independent population figure |
| -333333333 | The margin of error could not be calculated because the median falls in an open-ended range |
| -222222222 | The margin of error could not be calculated because there were too few observations |

None of the figures used in this project can legitimately be negative, so every negative value is
treated as missing, whether or not it appears on the list. No code is ever turned into zero. The
download checks report how many of the listed codes appear, and fail if an unlisted negative code
shows up, so that anything unexpected is looked into. The code -777777777 does not appear on the
Census page, so it would be treated as unlisted.

### Decision on -555555555

This decision was made on 10 November 2026. The Census Bureau explains that an estimate marked
-555555555 has no sampling error, and that its margin of error can be treated as zero. This project
still records it as missing rather than zero. That keeps a single, simple rule for every special code
and means the pipeline never invents a value.

As a result, the margin of error and the coefficient of variation are blank for these estimates, even
though they are among the most reliable figures in the table. In the dashboard, a blank coefficient of
variation should be explained as "controlled estimate, no margin of error", not shown as unreliable or
unknown. The validation report lists how many margins of error are blank after each run.

## Chronic disease

The diabetes and high blood pressure figures come from CDC PLACES. They are estimates produced by a
statistical model, not direct counts. CDC combines survey data from the Behavioral Risk Factor
Surveillance System with population data to estimate the share of adults in each county with each
condition.

The dashboard uses the age-adjusted figures (PLACES value type AgeAdjPrv). Age adjustment removes the
effect of some localities simply having older or younger populations, so that localities can be
compared fairly. The crude figures are downloaded but not used. The confidence limits are kept as CDC
published them, and a blank value stays blank.

## Health center supply

The site list is every Virginia row in the HRSA file, with any repeated site ID removed. Both
federally funded health centers and Look-Alikes are included, because both see patients.

A site counts toward the supply measure only if all of the following are true. Its status is Active,
because sites that are closed or still being verified do not serve patients today. Its location type
is Permanent, because mobile vans and seasonal sites are not a fixed, year-round place to get care.
Its site type is either Service Delivery Site or Administrative/Service Delivery Site, because both
see patients, while purely administrative offices do not. Finally, its FIPS code must be one of the
133 localities. These rules are set in `scripts/config.py` and can be changed there.

HRSA sometimes lists the same clinic more than once under different site IDs. This happens, for
example, while a Look-Alike health center becomes federally funded, when its old record and its new
record can both appear for a time. These records are legitimate, but they describe one clinic. So among
the sites that meet the rules above, each combination of locality, address and site name is counted
once. Before comparing, the address and name are lowercased, periods, commas, apostrophes and # signs
are removed, and repeated spaces are reduced to one. Nothing else is changed: street names are not
abbreviated and suite numbers are kept. The record with the lowest site ID is the one counted, so the
result is the same on every run.

The name is part of the match on purpose. A medical center and a dental center in the same building
are different services, and both count. If a record's address or name is blank, it is never matched
with another record, because two blanks only show that information is missing. The validation report
says how many records were left out of matching for this reason.

No rows are removed from the site table. The records that were merged are listed in
`data/processed/supply_duplicates.csv` and in the validation report after every run.

In the list downloaded on 10 November 2026, Virginia had 247 sites. Of these, 186 met the definition:
157 service delivery sites and 29 combined administrative and service delivery sites. The other 61
were left out, 23 because they were purely administrative and 38 because they were mobile or
seasonal. Two clinics in Lynchburg were each listed twice, under an old Look-Alike ID and a new
federally funded ID, so the 186 records describe 184 distinct sites. These were spread across 81
localities, and the remaining 52 localities had none.

The supply table starts from all 133 localities and fills in zero where there are no sites, because
having no site means zero supply rather than unknown supply. It also gives a count of all active site
records of any kind, for context, without merging duplicates.

## Rural and urban classification

The USDA Rural-Urban Continuum Code describes each locality on a scale from 1 to 9, based on the size
of the metropolitan area it belongs to or, for places outside metropolitan areas, on the size of its
urban population and whether it is next to a metropolitan area. Following USDA, codes 1 to 3 are
treated as metropolitan and codes 4 to 9 as nonmetropolitan. Land area is converted from square meters
to square miles.

## Dashboard measures

Rates are calculated in Power BI rather than stored in the files, so they stay correct when the
report is filtered to a group of localities. Each rate should be the sum of one column divided by the
sum of another, not an average of percentages, because an average would give a small locality the
same weight as a large one. For example:

```
Sites per 10,000 uninsured = DIVIDE ( SUM ( fact_supply[supply_sites] ), SUM ( acs_va[uninsured] ) ) * 10000
Uninsured rate = DIVIDE ( SUM ( acs_va[uninsured] ), SUM ( acs_va[insurance_universe] ) )
Poverty rate = DIVIDE ( SUM ( acs_va[below_poverty] ), SUM ( acs_va[poverty_universe] ) )
```

The PLACES percentages cannot be combined across localities with the data available, so they should
only be shown for one locality at a time.

## Limitations

The sources describe different periods. The Census figures cover 2020 to 2024, the PLACES figures
describe 2023, the rural and urban codes rely on 2020 population, and the health center list is a
snapshot of the day it was downloaded. The dashboard combines the latest available version of each
rather than one common year.

Estimates for small localities are less precise. Their Census margins of error can be large, so the
coefficient of variation should be checked before ranking them. The PLACES figures are model
estimates and carry their own uncertainty.

A site count does not measure capacity. It does not reflect opening hours, the number of staff,
the services offered or the number of patients seen, so a large health center and a small clinic each
count as one. HRSA does publish weekly opening hours, which this project does not yet use.

Only HRSA health centers are counted. Free clinics, hospital outpatient departments, rural health
clinics and private practices are not included, so the supply measure describes the community health
center network rather than all primary care.

People often cross locality lines for care, especially between small independent cities and the
counties around them. A city with no site of its own may have one just across its border.

The HRSA list changes over time, so the figures depend on the download date recorded in
`data/raw/download_log.csv`.

A site whose FIPS code is not one of the 133 localities, such as the former Bedford city (51515), is
kept in the site table but not counted. This did not happen in the November 2026 download.

## Open questions

Three questions still need an answer before the dashboard is published.

First, what thresholds should be used to call an estimate reliable? A common practice for ACS data is
to treat a coefficient of variation below 12 percent as reliable, between 12 and 40 percent as usable
with caution, and above 40 percent as unreliable, but this is a convention rather than a Census rule.

Second, how exactly should the "care access gap" be defined? The measures listed above are
candidates, and the choice is an analytical decision for the project.

Third, the PLACES methodology page should be checked to confirm the confidence level of the published
limits and the standard population used for age adjustment, and both should be recorded here.

---

Prepared by Pride Mudondo.
