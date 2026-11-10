"""Shared HTTP helper: timeouts, retries with backoff, and safe error messages."""
from __future__ import annotations

import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from scripts import config

logger = logging.getLogger(__name__)

SECRET_PARAMS = frozenset({"key"})
RETRYABLE_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
CENSUS_KEY_PAGES = {
    "missing_key.html": "no Census API key was sent",
    "invalid_key.html": "the Census API key was rejected",
}


class DownloadError(Exception):
    """A request failed and will not succeed by retrying."""


class ApiKeyError(DownloadError):
    """The Census API refused the request because of the API key."""


def redact(url: str) -> str:
    """Return the URL with secret query parameters replaced by ***."""
    parts = urlsplit(url)
    query = [
        (k, "***" if k.lower() in SECRET_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query, safe=",:*'()$")))


def build_session() -> requests.Session:
    """Create a session that identifies the project in its User-Agent."""
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    return session


def backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    """Return seconds to wait before retry number `attempt` (1-based)."""
    delay = config.BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
    if retry_after and retry_after.isdigit():
        delay = max(delay, float(retry_after))
    return delay


def is_retryable(status: int) -> bool:
    """Return True for statuses that may succeed on a later attempt."""
    return status == 429 or status >= 500


def check_census_key_redirect(response: requests.Response) -> None:
    """Raise ApiKeyError if the Census API redirected to a key error page."""
    page = urlsplit(response.url).path.rsplit("/", 1)[-1]
    if response.history and page in CENSUS_KEY_PAGES:
        raise ApiKeyError(
            f"Census API: {CENSUS_KEY_PAGES[page]}. Set the {config.CENSUS_KEY_ENV} "
            "environment variable (free key: https://api.census.gov/data/key_signup.html)."
        )


def check_not_html(response: requests.Response) -> None:
    """Raise DownloadError if a successful response is a web page instead of data."""
    content_type = response.headers.get("Content-Type", "").lower()
    if content_type.startswith("text/html"):
        raise DownloadError(
            f"{redact(response.url)} returned a web page ({content_type}) instead of data; "
            "the site may be down or blocking automated downloads."
        )


def client_error(response: requests.Response) -> DownloadError:
    """Build a readable error for a 4xx response."""
    body = response.text.strip().replace("\n", " ")[:300]
    return DownloadError(
        f"HTTP {response.status_code} from {redact(response.url)}. "
        f"This usually means a wrong URL, variable code or parameter. Server said: {body!r}"
    )


def get(
    url: str,
    params: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """GET a URL with timeouts and up to MAX_RETRIES retries; return a 2xx response."""
    session = session or build_session()
    attempts = config.MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, timeout=config.TIMEOUT_SECONDS)
        except RETRYABLE_ERRORS as exc:
            problem, retry_after = type(exc).__name__, None
        else:
            check_census_key_redirect(response)
            if response.ok:
                check_not_html(response)
                logger.debug("GET %s -> %s", redact(response.url), response.status_code)
                return response
            if not is_retryable(response.status_code):
                raise client_error(response)
            problem = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")
        if attempt == attempts:
            break
        delay = backoff_delay(attempt, retry_after)
        logger.warning(
            "%s from %s; retry %d/%d in %.0fs",
            problem, redact(url), attempt, config.MAX_RETRIES, delay,
        )
        time.sleep(delay)
    raise DownloadError(f"Giving up on {redact(url)} after {attempts} attempts ({problem}).")
