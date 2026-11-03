import json
from datetime import datetime
from pathlib import Path

import pytest

from finn.times import IST

FIXTURES = Path(__file__).parent / "fixtures"

# When the fixtures were captured; used as "first seen" in tests.
SEEN = datetime(2026, 11, 3, 16, 40, tzinfo=IST)


@pytest.fixture
def fixtures():
    return FIXTURES


@pytest.fixture
def api_items():
    return json.loads((FIXTURES / "api" / "announcements.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class FakeSession:
    """Stands in for requests.Session: replays queued responses per URL."""

    def __init__(self, routes):
        import requests
        self.routes = {url: list(v) for url, v in routes.items()}
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        queue = self.routes.get(url)
        if not queue:
            raise AssertionError(f"unexpected request: {url}")
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(resp, Exception):
            raise resp
        return resp


def robots_response(host):
    manifest = json.loads((FIXTURES / "robots" / "manifest.json").read_text())[host]
    body = (FIXTURES / "robots" / f"{host}.txt").read_bytes()
    return FakeResponse(manifest["status"], body, {"Content-Type": manifest["content_type"]})
