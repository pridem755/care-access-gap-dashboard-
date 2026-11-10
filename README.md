# Care Access Gap Dashboard

A Power BI dashboard showing gaps in access to care, built from public data with a reproducible Python pipeline.

## Repository layout

```
data/raw/         files exactly as downloaded, never edited
data/processed/   cleaned CSVs that Power BI reads
scripts/          all pipeline code (download, clean, validate); see below
tests/            pytest tests for scripts/
powerbi/          the Power BI Project (.pbip), saved as text so Git can diff it
docs/             requirements, metadata log, data dictionary, methodology, validation report
screenshots/      dashboard images for the README and reports
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Running the pipeline

Run everything from the project root.

```powershell
$env:CENSUS_API_KEY = "your-key"        # free: https://api.census.gov/data/key_signup.html
python -m scripts.download --all        # rebuild data/raw/ and data/raw/download_log.csv
python -m scripts.clean_data           # build the 5 tables in data/processed/
python -m scripts.validate_data        # check data/processed/; updates docs/validation_report.md
python -m pytest -q
```

Raw data files are not stored in Git (the PLACES file alone is over 60 MB). Only
`data/raw/download_log.csv` is committed: it records the URL, row count and SHA-256 of every
file, so `--all` rebuilds the same inputs and the checksums show whether they changed.

Download options: `--source NAME` (repeatable; `acs` runs both ACS tables), `--force`,
`--manual-file SOURCE PATH` for files that must be downloaded by hand.

### Download code in `scripts/`

```
config.py         every source, URL, release year and variable in one place
http_client.py    requests with timeouts, retries and backoff; hides the API key
download_log.py   append-only data/raw/download_log.csv with SHA-256 checksums
checks.py         post-download sanity checks (warn only, never modify files)
sources/          one module per data source, e.g. census_acs.py
download.py       command-line entry point
```

### Cleaning code in `scripts/`

`python -m scripts.clean_data` reads the newest logged raw file for each source, refuses any file
that changed since download or fails its checks, builds every table in memory, and writes them only
if all of them have exactly one row per locality. A failed run leaves `data/processed/` untouched.

```
clean_data.py                     command-line entry point
census_annotations.py             Census annotation codes -> missing values
atomic_write.py                   write through a temporary file (shared with download.py)
cleaning/raw_inputs.py            find, verify and load the newest raw file per source
cleaning/table_rules.py           one row per locality, FIPS as text, strict number parsing
cleaning/build_dim_geography.py   dim_geography.csv  (boundaries + RUCC)
cleaning/build_acs_va.py          acs_va.csv         (estimates, MOEs, CVs)
cleaning/build_places_va.py       places_va.csv      (age-adjusted prevalence)
cleaning/build_hrsa_supply.py     hrsa_sites_va.csv and fact_supply.csv
```

In Power BI, set every `fips` column to **Text** in Power Query; automatic type detection
would otherwise turn it into a number.

Then open `powerbi/*.pbip` in Power BI Desktop and refresh.

## Working rules

See [CONTRIBUTING.md](CONTRIBUTING.md).
