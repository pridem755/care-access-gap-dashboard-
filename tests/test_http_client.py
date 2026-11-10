"""Tests for scripts.http_client. No real network calls are made."""
from unittest.mock import MagicMock

import pytest
import requests

from scripts import config, http_client

URL = "https://api.example.gov/data"
SECRET = "supersecretkey123"


def fake_response(
    status: int = 200,
    url: str = URL,
    text: str = "ok",
    history: list | None = None,
    headers: dict | None = None,
) -> MagicMock:
    """Build a stand-in for requests.Response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 400
    response.url = url
    response.text = text
    response.history = history or []
    response.headers = headers or {}
    return response


def session_returning(*outcomes) -> MagicMock:
    """Build a session whose .get() yields each outcome in turn (or raises it)."""
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = list(outcomes)
    return session


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Record backoff delays instead of actually sleeping."""
    delays: list[float] = []
    monkeypatch.setattr(http_client.time, "sleep", delays.append)
    return delays


def test_success_returns_response_without_retry(no_sleep):
    session = session_returning(fake_response(200))
    assert http_client.get(URL, session=session).status_code == 200
    assert session.get.call_count == 1
    assert no_sleep == []


def test_every_request_has_a_timeout():
    session = session_returning(fake_response(200))
    http_client.get(URL, session=session)
    assert session.get.call_args.kwargs["timeout"] == config.TIMEOUT_SECONDS


def test_retries_5xx_then_succeeds_with_exponential_backoff(no_sleep):
    session = session_returning(fake_response(503), fake_response(502), fake_response(200))
    assert http_client.get(URL, session=session).status_code == 200
    assert no_sleep == [2.0, 4.0]


def test_retries_connection_errors(no_sleep):
    session = session_returning(requests.ConnectionError("boom"), fake_response(200))
    assert http_client.get(URL, session=session).status_code == 200
    assert len(no_sleep) == 1


def test_retries_a_connection_dropped_mid_download(no_sleep):
    dropped = requests.exceptions.ChunkedEncodingError("connection broken")
    session = session_returning(dropped, fake_response(200))
    assert http_client.get(URL, session=session).status_code == 200
    assert len(no_sleep) == 1


def test_gives_up_after_three_retries(no_sleep):
    session = session_returning(*[fake_response(500)] * 4)
    with pytest.raises(http_client.DownloadError, match="after 4 attempts"):
        http_client.get(URL, session=session)
    assert session.get.call_count == 4
    assert no_sleep == [2.0, 4.0, 8.0]


def test_429_respects_retry_after_header(no_sleep):
    session = session_returning(
        fake_response(429, headers={"Retry-After": "30"}), fake_response(200)
    )
    http_client.get(URL, session=session)
    assert no_sleep == [30.0]


def test_4xx_fails_immediately_with_server_message(no_sleep):
    session = session_returning(fake_response(400, text="error: unknown variable 'X'"))
    with pytest.raises(http_client.DownloadError, match="HTTP 400.*unknown variable"):
        http_client.get(URL, session=session)
    assert session.get.call_count == 1
    assert no_sleep == []


@pytest.mark.parametrize("page", ["missing_key.html", "invalid_key.html"])
def test_census_key_redirect_raises_api_key_error(page):
    redirected = fake_response(
        200, url=f"https://api.census.gov/data/{page}", history=[fake_response(302)]
    )
    with pytest.raises(http_client.ApiKeyError, match=config.CENSUS_KEY_ENV):
        http_client.get(URL, session=session_returning(redirected))


def test_redact_hides_key_and_keeps_other_params():
    url = f"{URL}?get=NAME,S2701_C01_001E&for=county:*&in=state:51&key={SECRET}"
    redacted = http_client.redact(url)
    assert SECRET not in redacted
    assert "key=***" in redacted
    assert "get=NAME,S2701_C01_001E" in redacted
    assert "for=county:*" in redacted


def test_key_never_appears_in_errors_or_logs(caplog, no_sleep):
    keyed_url = f"{URL}?key={SECRET}"
    session = session_returning(
        fake_response(500, url=keyed_url),
        requests.ConnectionError(f"failed for {keyed_url}"),
        fake_response(500, url=keyed_url),
        fake_response(404, url=keyed_url),
    )
    with caplog.at_level("DEBUG"), pytest.raises(http_client.DownloadError) as excinfo:
        http_client.get(keyed_url, session=session)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in caplog.text


def test_html_response_with_200_is_refused(no_sleep):
    page = fake_response(200, text="<html>maintenance</html>", headers={"Content-Type": "text/html; charset=utf-8"})
    with pytest.raises(http_client.DownloadError, match="web page"):
        http_client.get(URL, session=session_returning(page))


@pytest.mark.parametrize("content_type", ["text/csv; charset=UTF-8", "application/json", "application/zip",
                                          "application/octet-stream", ""])
def test_data_content_types_are_accepted(content_type):
    response = fake_response(200, headers={"Content-Type": content_type} if content_type else {})
    assert http_client.get(URL, session=session_returning(response)) is response
