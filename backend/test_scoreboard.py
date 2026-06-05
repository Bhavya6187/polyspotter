from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


def test_scoreboard_aggregates(monkeypatch):
    now = datetime.now(timezone.utc)
    fake_rows = [
        {"market_title": "Padres vs Phillies", "outcome": "San Diego Padres",
         "won": True, "return_pct": (1 - 0.38) / 0.38, "event_slug": "mlb-x",
         "resolved_at": now - timedelta(days=2)},
        {"market_title": "Knicks vs Spurs", "outcome": "Knicks",
         "won": False, "return_pct": -1.0, "event_slug": "nba-y",
         "resolved_at": now - timedelta(days=3)},
    ]
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: fake_rows)
    monkeypatch.setattr(app_module, "_scoreboard_cache", None)

    resp = client.get("/api/scoreboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"]["wins"] == 1
    assert data["window"]["losses"] == 1
    assert data["window"]["hit_rate"] == 0.5
    assert len(data["recent"]) == 2
    assert data["recent"][0]["market_title"] == "Padres vs Phillies"


def test_scoreboard_empty(monkeypatch):
    monkeypatch.setattr(app_module, "_scoreboard_rows", lambda: [])
    monkeypatch.setattr(app_module, "_scoreboard_cache", None)
    resp = client.get("/api/scoreboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"]["wins"] == 0
    assert data["all_time"]["wins"] == 0
    assert data["recent"] == []
