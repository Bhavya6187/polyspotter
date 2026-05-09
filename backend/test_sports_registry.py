"""Tests for sport-overlay registry and base contract. No DB or network."""
import pytest
from sports.base import OverlayResponse


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
    with pytest.raises(ValueError):
        OverlayResponse(
            sport="basketball",
            status="invalid",
            last_updated="2026-05-08T12:00:00Z",
            payload={},
        )
