"""Regression test for the 2026-07 ingest outage: a trailing slash on
POLYBOT_BACKEND_URL produced https://host//api/ingest, which FastAPI 404s,
silently dropping every alert push for days."""

import importlib


def test_backend_url_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("POLYBOT_BACKEND_URL", "https://example.com/")
    import seeder
    importlib.reload(seeder)
    try:
        assert seeder.BACKEND_URL == "https://example.com"
        assert "//api" not in f"{seeder.BACKEND_URL}/api/ingest".replace("https://", "")
    finally:
        monkeypatch.delenv("POLYBOT_BACKEND_URL", raising=False)
        importlib.reload(seeder)
