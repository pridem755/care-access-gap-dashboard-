"""Download source files into data/raw/ exactly as published. Never edit them afterwards."""
from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# name -> URL. Record each one in docs/metadata_log.md as well.
SOURCES: dict[str, str] = {}


def download(name: str, url: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / name
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.write_bytes(response.content)
    print(f"Saved {dest} ({len(response.content):,} bytes)")
    return dest


def main() -> None:
    if not SOURCES:
        print("No sources configured yet. Add them to SOURCES in download_data.py.")
    for name, url in SOURCES.items():
        download(name, url)


if __name__ == "__main__":
    main()
