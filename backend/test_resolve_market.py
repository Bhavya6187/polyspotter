"""
/api/market/resolve/{partial_id}: disambiguate colliding short IDs.

Market URLs carry only 5 hex chars of the condition_id. Across the 49.5k
markets in the sitemap 1,139 prefixes are shared by 2,300 markets, and the
endpoint returned `LIKE prefix% LIMIT 1` -- an arbitrary one -- so e.g. the
Newcastle vs Hull page rendered an ITF tennis market and set its canonical to
the tennis slug. The frontend now passes the title part of the slug and the
backend prefers the candidate whose slugified title matches.
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

import app as app_module
from app import app, _title_slug

client = TestClient(app)

CANDIDATES = [
    {"condition_id": "0x518fd" + "a" * 59, "market_title": "ITF M15 Maanshan 8 Men: Osminkin vs Komagata"},
    {"condition_id": "0x518fd" + "b" * 59, "market_title": "Newcastle United FC vs Hull City AFC: O/U 2.5"},
]


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, sql, params=None):
        self.params = params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def _install(monkeypatch, rows):
    cur = _Cursor(rows)

    @contextmanager
    def fake():
        yield _Conn(cur)

    monkeypatch.setattr(app_module, "db", fake)
    return cur


def test_title_slug_matches_frontend_marketslug():
    # mirrors frontend/src/lib/slugify.js: lower, non-alnum runs -> '-', trim, 80 chars
    assert _title_slug("Newcastle United FC vs Hull City AFC: O/U 2.5") == "newcastle-united-fc-vs-hull-city-afc-o-u-2-5"
    assert _title_slug("  --Hello!!  ") == "hello"
    assert len(_title_slug("x" * 200)) == 80


def test_slug_selects_the_matching_candidate(monkeypatch):
    _install(monkeypatch, CANDIDATES)
    resp = client.get("/api/market/resolve/0x518fd", params={"slug": "newcastle-united-fc-vs-hull-city-afc-o-u-2-5"})
    assert resp.status_code == 200
    assert resp.json()["condition_id"] == CANDIDATES[1]["condition_id"]


def test_without_slug_falls_back_to_first_candidate(monkeypatch):
    _install(monkeypatch, CANDIDATES)
    resp = client.get("/api/market/resolve/0x518fd")
    assert resp.status_code == 200
    assert resp.json()["condition_id"] == CANDIDATES[0]["condition_id"]


def test_unmatched_slug_falls_back_to_first_candidate(monkeypatch):
    _install(monkeypatch, CANDIDATES)
    resp = client.get("/api/market/resolve/0x518fd", params={"slug": "something-else"})
    assert resp.status_code == 200
    assert resp.json()["condition_id"] == CANDIDATES[0]["condition_id"]


def test_no_candidates_is_404(monkeypatch):
    _install(monkeypatch, [])
    assert client.get("/api/market/resolve/0x518fd").status_code == 404


def test_non_hex_prefix_is_rejected_without_touching_the_db(monkeypatch):
    cur = _install(monkeypatch, CANDIDATES)
    assert client.get("/api/market/resolve/%25").status_code == 404
    assert client.get("/api/market/resolve/0x_").status_code == 404
    assert client.get("/api/market/resolve/0").status_code == 404
    assert cur.params is None
