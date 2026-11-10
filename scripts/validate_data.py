"""Check the processed CSVs before Power BI reads them. Exits non-zero on failure."""
import sys
from pathlib import Path

import pandas as pd

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def validate(df: pd.DataFrame) -> list[str]:
    problems = []
    if df.empty:
        problems.append("table is empty")
    if df.duplicated().any():
        problems.append(f"{int(df.duplicated().sum())} duplicate rows")
    return problems


def main() -> int:
    failed = False
    for path in sorted(PROCESSED_DIR.glob("*.csv")):
        problems = validate(pd.read_csv(path))
        status = "FAIL" if problems else "PASS"
        print(f"[{status}] {path.name}" + (": " + "; ".join(problems) if problems else ""))
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
