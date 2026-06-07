from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)

_SAMPLE_CONTENT = {
    "subject": "PolySpotter Daily — 2026-06-06",
    "intro": "Two markets resolve today.",
    "sections": [
        {
            "key": "resolving_today",
            "title": "Resolving Today",
            "items": [
                {
                    "event_slug": "some-event",
                    "headline": "Sharps piling into YES",
                    "leaning": "Yes @ 0.62",
                    "blurb": "Big informed flow late.",
                    "url": "https://polyspotter.com/event/some-event",
                }
            ],
        }
    ],
}


def test_list_digests(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_digest_index_rows",
        lambda: [{"digest_date": "2026-06-06", "subject": "PolySpotter Daily — 2026-06-06"}],
    )
    resp = client.get("/api/digests")
    assert resp.status_code == 200
    assert resp.json() == [
        {"digest_date": "2026-06-06", "subject": "PolySpotter Daily — 2026-06-06"}
    ]


def test_get_digest_found(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_digest_by_date",
        lambda d: {
            "digest_date": "2026-06-06",
            "subject": _SAMPLE_CONTENT["subject"],
            "intro": _SAMPLE_CONTENT["intro"],
            "content_json": _SAMPLE_CONTENT,
        },
    )
    resp = client.get("/api/digest/2026-06-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == _SAMPLE_CONTENT["subject"]
    assert body["content_json"]["sections"][0]["items"][0]["leaning"] == "Yes @ 0.62"


def test_get_digest_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_digest_by_date", lambda d: None)
    resp = client.get("/api/digest/2099-01-01")
    assert resp.status_code == 404
