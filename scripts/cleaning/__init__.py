"""Turn checked raw files into the cleaned tables Power BI loads, one module per table."""
from __future__ import annotations


class CleaningError(Exception):
    """Cleaning cannot produce correct output; nothing should be written."""
