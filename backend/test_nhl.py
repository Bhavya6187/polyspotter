"""Tests for NHL game matching logic. No DB or network required."""

import pytest


def test_parse_team_names_standard():
    from sports.nhl import parse_team_names
    assert parse_team_names("Maple Leafs vs. Bruins") == ("Maple Leafs", "Bruins")


def test_parse_team_names_strips_league_prefix():
    from sports.nhl import parse_team_names
    assert parse_team_names("NHL: Rangers vs Islanders") == ("Rangers", "Islanders")


def test_parse_team_names_strips_betting_suffix():
    from sports.nhl import parse_team_names
    assert parse_team_names("Bruins vs. Rangers: O/U 6.5") == ("Bruins", "Rangers")


def test_parse_team_names_no_match():
    from sports.nhl import parse_team_names
    assert parse_team_names("Will ETH hit 5k?") is None


def test_resolve_abbr_basic():
    from sports.nhl import resolve_abbr
    assert resolve_abbr("Bruins") == "BOS"
    assert resolve_abbr("boston") == "BOS"
    assert resolve_abbr("Boston Bruins") == "BOS"
    assert resolve_abbr("BOS") == "BOS"


def test_resolve_abbr_maple_leafs():
    from sports.nhl import resolve_abbr
    assert resolve_abbr("Maple Leafs") == "TOR"
    assert resolve_abbr("Leafs") == "TOR"
    assert resolve_abbr("Toronto") == "TOR"


def test_resolve_abbr_unknown():
    from sports.nhl import resolve_abbr
    assert resolve_abbr("Brisbane Heat") is None


def test_extract_codes_from_slug_standard():
    from sports.nhl import extract_codes_from_slug
    assert extract_codes_from_slug("nhl-bos-tor-2026-04-15") == ("BOS", "TOR")


def test_extract_codes_from_slug_invalid():
    from sports.nhl import extract_codes_from_slug
    assert extract_codes_from_slug("nba-lal-bos-2026-04-19") is None
    assert extract_codes_from_slug("") is None


import json
import pathlib
from unittest.mock import patch

FIXTURE_DIR = pathlib.Path(__file__).parent / "test_fixtures"


def _load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_get_nhl_data_parses_fixture_summary():
    from sports import nhl
    summary = _load("espn_nhl_summary.json")

    competitors = summary["header"]["competitions"][0]["competitors"]
    home_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "home")
    away_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "away")
    home_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
    away_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")

    scoreboard = {"events": [{
        "id": summary["header"]["id"],
        "competitions": [{"competitors": [{"team": {"abbreviation": c["team"]["abbreviation"]}} for c in competitors]}],
    }]}

    with patch.object(nhl, "_fetch_espn_scoreboard", return_value=scoreboard), \
         patch.object(nhl, "_fetch_espn_summary", return_value=summary):
        nhl._game_cache.clear()
        data = nhl.get_nhl_data(f"{away_name} vs {home_name}")

    assert data is not None
    assert data.home.abbr == nhl._normalize_espn_abbr(home_abbr)
    assert data.away.abbr == nhl._normalize_espn_abbr(away_abbr)
    assert data.status in {"pre", "live", "final"}


def test_nhl_overlay_can_handle():
    from sports.nhl import NHLOverlay
    plugin = NHLOverlay()
    assert plugin.can_handle("Bruins vs Rangers", ["nhl"]) is True
    assert plugin.can_handle("random", ["nhl"]) is False


def test_nhl_overlay_metadata():
    from sports.nhl import NHLOverlay
    p = NHLOverlay()
    assert p.sport_id == "nhl"
    assert "nhl" in p.tag_aliases


def test_can_handle_accepts_puck_line_title_when_slug_resolves():
    from sports.nhl import NHLOverlay
    plugin = NHLOverlay()
    assert plugin.can_handle(
        "Puck Line: Bruins (-1.5)", ["nhl"], "nhl-bos-tor-2026-04-15"
    ) is True


def test_can_handle_rejects_unparseable_title_with_unresolvable_slug():
    from sports.nhl import NHLOverlay
    plugin = NHLOverlay()
    assert plugin.can_handle(
        "Puck Line: Foo (-1.5)", ["nhl"], "nhl-zzz-yyy-2026-04-15"
    ) is False
