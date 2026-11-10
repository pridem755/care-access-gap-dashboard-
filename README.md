# Care Access Gap Dashboard

A Power BI dashboard showing gaps in access to care, built from public data with a reproducible Python pipeline.

## Repository layout

```
data/raw/         files exactly as downloaded, never edited
data/processed/   cleaned CSVs that Power BI reads
scripts/          download_data.py -> clean_data.py -> validate_data.py
tests/            pytest tests for the pipeline
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

```powershell
python scripts/download_data.py
python scripts/clean_data.py
python scripts/validate_data.py
pytest
```

Then open `powerbi/*.pbip` in Power BI Desktop and refresh.

## Working rules

See [CONTRIBUTING.md](CONTRIBUTING.md).
