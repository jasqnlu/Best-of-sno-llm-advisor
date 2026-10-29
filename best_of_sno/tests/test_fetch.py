"""Tests for fetch_feed: polite network fetch (Task 3)."""

import requests

from best_of_sno.scraper import fetch_feed


class _Resp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _OkSession:
    def __init__(self):
        self.sent_headers = None
        self.call_count = 0

    def get(self, url, headers=None, timeout=None):
        self.call_count += 1
        self.sent_headers = headers
        return _Resp(b"<rss/>")


class _FlakySession:
    """Raises a connection error twice, then succeeds."""

    def __init__(self):
        self.call_count = 0

    def get(self, url, headers=None, timeout=None):
        self.call_count += 1
        if self.call_count < 3:
            raise requests.exceptions.ConnectionError("boom")
        return _Resp(b"ok")


def test_sends_user_agent_and_returns_bytes():
    session = _OkSession()
    out = fetch_feed("https://bestofsno.com/feed/", session=session)
    assert out == b"<rss/>"
    assert "BestOfSNO-research-scraper" in session.sent_headers["User-Agent"]


def test_retries_then_succeeds():
    session = _FlakySession()
    out = fetch_feed("https://bestofsno.com/feed/", session=session, backoff=0)
    assert session.call_count == 3
    assert out == b"ok"
