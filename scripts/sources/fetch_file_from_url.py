"""Fetch a source published as one file at a fixed URL, exactly as the server sends it."""
from __future__ import annotations

import requests

from scripts import config, http_client
from scripts.sources import Fetched


def fetch(source: config.Source, session: requests.Session | None = None) -> Fetched:
    """Download the file exactly as published."""
    if not source.url:
        raise http_client.DownloadError(f"{source.name} has no URL configured; use --manual-file")
    response = http_client.get(source.url, session=session)
    return Fetched(content=response.content, url=http_client.redact(response.url))
