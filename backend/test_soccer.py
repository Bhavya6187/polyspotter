"""Tests for soccer game matching and league dispatch. No DB or network."""

import pytest


def test_parse_team_names_standard():
    from sports.soccer import parse_team_names
    assert parse_team_names("Arsenal vs Manchester City") == ("Arsenal", "Manchester City")


def test_parse_team_names_strips_competition_prefix():
    from sports.soccer import parse_team_names
    assert parse_team_names("Premier League: Arsenal vs Liverpool") == ("Arsenal", "Liverpool")
    assert parse_team_names("Champions League: Real Madrid vs Bayern Munich") == ("Real Madrid", "Bayern Munich")
    assert parse_team_names("World Cup: Brazil vs Argentina") == ("Brazil", "Argentina")


def test_parse_team_names_strips_betting_suffix():
    from sports.soccer import parse_team_names
    assert parse_team_names("Arsenal vs Liverpool: O/U 2.5") == ("Arsenal", "Liverpool")


def test_parse_team_names_no_match():
    from sports.soccer import parse_team_names
    assert parse_team_names("Will SOL hit 300?") is None


def test_resolve_epl_abbr():
    from sports.soccer import resolve_epl_abbr
    assert resolve_epl_abbr("Arsenal") == "ARS"
    assert resolve_epl_abbr("arsenal") == "ARS"
    assert resolve_epl_abbr("Manchester City") == "MCI"
    assert resolve_epl_abbr("Man City") == "MCI"
    assert resolve_epl_abbr("Liverpool") == "LIV"


def test_resolve_epl_abbr_unknown():
    from sports.soccer import resolve_epl_abbr
    # Real Madrid is La Liga, not in our hard-coded EPL table — None
    assert resolve_epl_abbr("Real Madrid") is None


def test_resolve_league_epl():
    from sports.soccer import resolve_league
    assert resolve_league(["epl", "soccer"]) == "eng.1"
    assert resolve_league(["English Premier League"]) == "eng.1"
    assert resolve_league(["premier league"]) == "eng.1"


def test_resolve_league_ucl():
    from sports.soccer import resolve_league
    assert resolve_league(["UCL", "soccer"]) == "uefa.champions"
    assert resolve_league(["champions league"]) == "uefa.champions"
    assert resolve_league(["uefa champions league"]) == "uefa.champions"


def test_resolve_league_world_cup():
    from sports.soccer import resolve_league
    assert resolve_league(["World Cup"]) == "fifa.world"
    assert resolve_league(["FIFA World Cup", "Soccer"]) == "fifa.world"


def test_resolve_league_none():
    from sports.soccer import resolve_league
    assert resolve_league(["la liga"]) is None
    assert resolve_league([]) is None


def test_extract_codes_from_slug_epl():
    from sports.soccer import extract_codes_from_slug
    assert extract_codes_from_slug("epl-ars-mci-2026-04-19") == ("ARS", "MCI")


def test_extract_codes_from_slug_unknown_league_returns_none():
    from sports.soccer import extract_codes_from_slug
    # UCL/WC slugs use opponents that aren't in our EPL table — fallback should return None;
    # plugin will rely on title-based match instead
    assert extract_codes_from_slug("ucl-rma-bay-2026-04-09") is None


def test_extract_codes_from_slug_invalid():
    from sports.soccer import extract_codes_from_slug
    assert extract_codes_from_slug("nba-lal-bos-2026-04-19") is None
    assert extract_codes_from_slug("") is None


import json
import pathlib
from unittest.mock import patch

FIXTURE_DIR = pathlib.Path(__file__).parent / "test_fixtures"


def _load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_get_soccer_data_parses_epl_fixture():
    from sports import soccer
    summary = _load("espn_soccer_epl_summary.json")
    competitors = summary["header"]["competitions"][0]["competitors"]
    home_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
    away_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
    home_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "home")
    away_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "away")

    scoreboard = {"events": [{
        "id": summary["header"]["id"],
        "competitions": [{"competitors": [
            {"team": {"abbreviation": home_abbr, "displayName": home_name}},
            {"team": {"abbreviation": away_abbr, "displayName": away_name}},
        ]}],
    }]}

    with patch.object(soccer, "_fetch_espn_scoreboard", return_value=scoreboard), \
         patch.object(soccer, "_fetch_espn_summary", return_value=summary):
        soccer._match_cache.clear()
        data = soccer.get_soccer_data(f"{away_name} vs {home_name}", tags=["epl"])

    assert data is not None
    assert data.competition == "EPL"
    assert data.league_id == "eng.1"
    assert data.status in {"pre", "live", "final"}


def test_get_soccer_data_parses_ucl_fixture_via_name_match():
    """UCL/WC don't have a hard-coded alias table; team-resolution happens
    against ESPN's displayName/abbreviation in the scoreboard."""
    from sports import soccer
    summary = _load("espn_soccer_ucl_summary.json")
    competitors = summary["header"]["competitions"][0]["competitors"]
    home_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
    away_name = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
    home_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "home")
    away_abbr = next(c["team"]["abbreviation"] for c in competitors if c["homeAway"] == "away")

    scoreboard = {"events": [{
        "id": summary["header"]["id"],
        "competitions": [{"competitors": [
            {"team": {"abbreviation": home_abbr, "displayName": home_name}},
            {"team": {"abbreviation": away_abbr, "displayName": away_name}},
        ]}],
    }]}

    with patch.object(soccer, "_fetch_espn_scoreboard", return_value=scoreboard), \
         patch.object(soccer, "_fetch_espn_summary", return_value=summary):
        soccer._match_cache.clear()
        data = soccer.get_soccer_data(f"{away_name} vs {home_name}", tags=["ucl"])

    assert data is not None
    assert data.competition == "UCL"
    assert data.league_id == "uefa.champions"


def test_get_soccer_data_returns_none_when_league_tag_missing():
    from sports import soccer
    soccer._match_cache.clear()
    assert soccer.get_soccer_data("Arsenal vs Liverpool", tags=["la liga"]) is None


def test_soccer_overlay_can_handle():
    from sports.soccer import SoccerOverlay
    plugin = SoccerOverlay()
    assert plugin.can_handle("Arsenal vs Liverpool", ["epl"]) is True
    assert plugin.can_handle("random", ["epl"]) is False


def test_soccer_overlay_metadata():
    from sports.soccer import SoccerOverlay
    p = SoccerOverlay()
    assert p.sport_id == "soccer"
    assert "epl" in p.tag_aliases
    assert "ucl" in p.tag_aliases
    assert "world cup" in p.tag_aliases


def test_can_handle_accepts_handicap_title_when_epl_slug_resolves():
    from sports.soccer import SoccerOverlay
    plugin = SoccerOverlay()
    assert plugin.can_handle(
        "Handicap: Arsenal (-1.5)", ["epl"], "epl-ars-mci-2026-04-19"
    ) is True


def test_can_handle_rejects_handicap_title_with_unresolvable_slug():
    from sports.soccer import SoccerOverlay
    plugin = SoccerOverlay()
    assert plugin.can_handle(
        "Handicap: Foo (-1.5)", ["epl"], "epl-zzz-yyy-2026-04-19"
    ) is False
