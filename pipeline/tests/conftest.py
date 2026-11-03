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


def build_data_dir(d):
    """A data/ tree made from the real 2-3 Nov 2026 slice in fixtures/brief (what `finn collect` would leave)."""
    import shutil
    b = FIXTURES / "brief"
    raw = d / "raw" / "nse_api" / "announcements"
    raw.mkdir(parents=True)
    for line in (b / "announcements.jsonl").read_text(encoding="utf-8").splitlines():
        day = json.loads(line)["published"][:10]
        with (raw / f"{day}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    cache = d / "cache"
    (cache / "nse").mkdir(parents=True)
    shutil.copy(b / "EQUITY_L.csv", cache / "nse" / "EQUITY_L.csv")
    for src, dst in [("bhavcopy", "bhavcopy"), ("xbrl", "xbrl"), ("pdf_text", "pdf_text"),
                     ("corporate_actions", "nse_api/corporate_actions"),
                     ("integrated_filings", "nse_api/integrated_filings")]:
        shutil.copytree(b / src, cache / dst)
    return d


def robots_response(host):
    manifest = json.loads((FIXTURES / "robots" / "manifest.json").read_text())[host]
    body = (FIXTURES / "robots" / f"{host}.txt").read_bytes()
    return FakeResponse(manifest["status"], body, {"Content-Type": manifest["content_type"]})
