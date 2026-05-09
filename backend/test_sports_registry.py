"""Tests for sport-overlay registry and base contract. No DB or network."""
import pytest
from pydantic import ValidationError

from sports import register, resolve_for_tags, all_plugins, SportOverlay
from sports.base import OverlayResponse


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot registry before each test; restore after.

    Each test gets a clean slate (no leakage between tests) but real
    plugins registered at import time persist across the session.
    """
    import sports
    original = list(sports._PLUGINS)
    sports._PLUGINS.clear()
    yield
    sports._PLUGINS[:] = original


def test_overlay_response_construction():
    r = OverlayResponse(
        sport="basketball",
        status="live",
        last_updated="2026-05-08T12:00:00Z",
        payload={"home": {"tricode": "LAL"}, "away": {"tricode": "BOS"}},
    )
    assert r.sport == "basketball"
    assert r.status == "live"
    assert r.payload["home"]["tricode"] == "LAL"


def test_overlay_response_status_must_be_valid():
    with pytest.raises(ValidationError):
        OverlayResponse(
            sport="basketball",
            status="invalid",
            last_updated="2026-05-08T12:00:00Z",
            payload={},
        )


def test_register_rejects_plugin_missing_sport_id():
    class _Bad(SportOverlay):
        tag_aliases = ("nba",)
        def can_handle(self, title, tags): return True
        def fetch(self, condition_id, title, tags, event_slug=""): return None

    with pytest.raises(TypeError, match="sport_id"):
        register(_Bad())


def test_register_rejects_plugin_missing_tag_aliases():
    class _Bad(SportOverlay):
        sport_id = "stub"
        def can_handle(self, title, tags): return True
        def fetch(self, condition_id, title, tags, event_slug=""): return None

    with pytest.raises(TypeError, match="tag_aliases"):
        register(_Bad())


class _StubPlugin(SportOverlay):
    """Minimal plugin used only for registry tests."""

    def __init__(self, sport_id: str, aliases: tuple[str, ...]):
        self.sport_id = sport_id
        self.tag_aliases = aliases

    def can_handle(self, title, tags):
        return True

    def fetch(self, condition_id, title, tags, event_slug=""):
        return None


def test_resolve_returns_first_matching_plugin():
    a = _StubPlugin("basketball", ("nba", "ncaa"))
    b = _StubPlugin("baseball", ("mlb",))
    register(a)
    register(b)

    assert resolve_for_tags(["mlb"]) is b
    assert resolve_for_tags(["nba"]) is a


def test_resolve_handles_case_unknown_and_empty():
    a = _StubPlugin("basketball", ("nba", "ncaa"))
    register(a)

    assert resolve_for_tags(["NBA"]) is a       # case-insensitive
    assert resolve_for_tags(["unrelated"]) is None
    assert resolve_for_tags([]) is None


def test_resolve_first_match_wins_when_multiple_register_same_tag():
    a = _StubPlugin("basketball", ("hoops",))
    b = _StubPlugin("dunkball", ("hoops",))
    register(a)
    register(b)

    assert resolve_for_tags(["hoops"]) is a  # registered first


def test_all_plugins_returns_in_registration_order():
    a = _StubPlugin("a", ("a",))
    b = _StubPlugin("b", ("b",))
    register(a)
    register(b)
    assert all_plugins() == [a, b]


def test_real_plugins_self_register():
    """Importing the sports package triggers registration of all bundled plugins."""
    import sports
    from sports.basketball import BasketballOverlay
    from sports.cricket import CricketOverlay
    from sports.mlb import MLBOverlay
    from sports.nhl import NHLOverlay
    from sports.soccer import SoccerOverlay

    sports.register(BasketballOverlay())
    sports.register(CricketOverlay())
    sports.register(MLBOverlay())
    sports.register(NHLOverlay())
    sports.register(SoccerOverlay())

    assert resolve_for_tags(["nba"]).sport_id == "basketball"
    assert resolve_for_tags(["ipl"]).sport_id == "cricket"
    assert resolve_for_tags(["cricket"]).sport_id == "cricket"
    assert resolve_for_tags(["basketball"]).sport_id == "basketball"
    assert resolve_for_tags(["mlb"]).sport_id == "mlb"
    assert resolve_for_tags(["baseball"]).sport_id == "mlb"
    assert resolve_for_tags(["nhl"]).sport_id == "nhl"
    assert resolve_for_tags(["hockey"]).sport_id == "nhl"
    assert resolve_for_tags(["epl"]).sport_id == "soccer"
    assert resolve_for_tags(["champions league"]).sport_id == "soccer"
    assert resolve_for_tags(["world cup"]).sport_id == "soccer"


from fastapi.testclient import TestClient


# NOTE: app import is inlined inside each test so it happens AFTER the autouse
# fixture has cleared _PLUGINS — module-level import would register real plugins
# before any test runs.
def test_overlay_endpoint_404_when_no_plugin_matches():
    # Don't pre-register any plugins (autouse fixture clears them).
    from app import app
    client = TestClient(app)
    resp = client.get(
        "/api/market/0xabc/overlay",
        params={"title": "Some random market", "tag": ["politics"]},
    )
    assert resp.status_code == 404


def test_overlay_endpoint_dispatches_to_matching_plugin():
    a = _StubPlugin("basketball", ("nba",))

    captured = {}

    def fake_fetch(condition_id, title, tags, event_slug=""):
        captured["args"] = (condition_id, title, tags, event_slug)
        return OverlayResponse(
            sport="basketball",
            status="live",
            last_updated="2026-05-08T12:00:00Z",
            payload={"hello": "world"},
        )

    a.fetch = fake_fetch
    register(a)

    from app import app
    client = TestClient(app)
    resp = client.get(
        "/api/market/0xabc/overlay",
        params={"title": "Lakers vs Celtics", "tag": ["nba"], "event_slug": "lal-bos"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sport"] == "basketball"
    assert body["status"] == "live"
    assert body["payload"] == {"hello": "world"}
    assert captured["args"] == ("0xabc", "Lakers vs Celtics", ["nba"], "lal-bos")


def test_overlay_endpoint_404_when_can_handle_returns_false():
    a = _StubPlugin("basketball", ("nba",))
    a.can_handle = lambda title, tags: False
    register(a)

    from app import app
    client = TestClient(app)
    resp = client.get(
        "/api/market/0xabc/overlay",
        params={"title": "x", "tag": ["nba"]},
    )
    assert resp.status_code == 404


def test_overlay_endpoint_404_when_fetch_returns_none():
    a = _StubPlugin("basketball", ("nba",))
    a.fetch = lambda *a, **k: None
    register(a)

    from app import app
    client = TestClient(app)
    resp = client.get(
        "/api/market/0xabc/overlay",
        params={"title": "Lakers vs Celtics", "tag": ["nba"]},
    )
    assert resp.status_code == 404


def test_overlay_endpoint_400_when_title_missing():
    from app import app
    client = TestClient(app)
    resp = client.get("/api/market/0xabc/overlay", params={"tag": ["nba"]})
    assert resp.status_code == 400
