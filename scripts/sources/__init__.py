"""One module per raw data source, plus the result type they all return."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fetched:
    """Bytes exactly as received, and the (redacted) URL they came from."""

    content: bytes
    url: str
