"""Tests for sport-overlay registry and base contract. No DB or network."""
import pytest
from pydantic import ValidationError
from sports.base import OverlayResponse


@pytest.fixture(autouse=True)
def _clean_registry():
    import sports
    sports._PLUGINS.clear()
    yield
    sports._PLUGINS.clear()


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
    from sports import register, SportOverlay

    class _Bad(SportOverlay):
        tag_aliases = ("nba",)
        def can_handle(self, title, tags): return True
        def fetch(self, condition_id, title, tags, event_slug=""): return None

    with pytest.raises(TypeError, match="sport_id"):
        register(_Bad())


def test_register_rejects_plugin_missing_tag_aliases():
    from sports import register, SportOverlay

    class _Bad(SportOverlay):
        sport_id = "stub"
        def can_handle(self, title, tags): return True
        def fetch(self, condition_id, title, tags, event_slug=""): return None

    with pytest.raises(TypeError, match="tag_aliases"):
        register(_Bad())


from sports import register, resolve_for_tags, all_plugins, SportOverlay


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
    assert resolve_for_tags(["NBA"]) is a  # case-insensitive
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
