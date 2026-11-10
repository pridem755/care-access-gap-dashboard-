"""Read data/raw/, clean it, and write CSVs to data/processed/ for Power BI."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.drop_duplicates()
    return df


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(RAW_DIR.glob("*.csv")):
        out = PROCESSED_DIR / path.name
        clean(pd.read_csv(path)).to_csv(out, index=False)
        print(f"Cleaned {path.name} -> {out}")


if __name__ == "__main__":
    main()
