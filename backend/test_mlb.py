"""Tests for MLB game matching logic. No DB or network required."""

import pytest


def test_parse_team_names_standard():
    from sports.mlb import parse_team_names
    assert parse_team_names("Yankees vs. Red Sox") == ("Yankees", "Red Sox")


def test_parse_team_names_no_dot():
    from sports.mlb import parse_team_names
    assert parse_team_names("Dodgers vs Giants") == ("Dodgers", "Giants")


def test_parse_team_names_v():
    from sports.mlb import parse_team_names
    assert parse_team_names("Cubs v Cardinals") == ("Cubs", "Cardinals")


def test_parse_team_names_strips_league_prefix():
    from sports.mlb import parse_team_names
    assert parse_team_names("MLB: Astros vs. Rangers") == ("Astros", "Rangers")


def test_parse_team_names_strips_betting_suffix():
    from sports.mlb import parse_team_names
    # Spread/ML titles tend to name only one team; this checks we don't
    # blow up on the full-vs form when a suffix appears
    assert parse_team_names("Yankees vs. Red Sox: O/U 8.5") == ("Yankees", "Red Sox")


def test_parse_team_names_no_match():
    from sports.mlb import parse_team_names
    assert parse_team_names("Will Bitcoin hit 100k?") is None


def test_resolve_abbr_basic():
    from sports.mlb import resolve_abbr
    assert resolve_abbr("Yankees") == "NYY"
    assert resolve_abbr("yankees") == "NYY"
    assert resolve_abbr("New York Yankees") == "NYY"
    assert resolve_abbr("NYY") == "NYY"


def test_resolve_abbr_city():
    from sports.mlb import resolve_abbr
    assert resolve_abbr("Boston") == "BOS"
    # Bare "Los Angeles" is ambiguous (Dodgers vs Angels) and should not
    # resolve. Disambiguated forms ("LA Dodgers", "Los Angeles Angels")
    # remain in the alias table and resolve correctly.
    assert resolve_abbr("Los Angeles") is None
    assert resolve_abbr("LA Dodgers") == "LAD"
    assert resolve_abbr("Los Angeles Angels") == "LAA"


def test_resolve_abbr_unknown():
    from sports.mlb import resolve_abbr
    assert resolve_abbr("Brisbane Heat") is None


def test_extract_codes_from_slug_standard():
    from sports.mlb import extract_codes_from_slug
    assert extract_codes_from_slug("mlb-nyy-bos-2026-05-09") == ("NYY", "BOS")


def test_extract_codes_from_slug_invalid():
    from sports.mlb import extract_codes_from_slug
    assert extract_codes_from_slug("nba-lal-bos-2026-04-19") is None
    assert extract_codes_from_slug("") is None
    assert extract_codes_from_slug("mlb-unknown-team-2026-05-09") is None


import json
import pathlib
from unittest.mock import patch

FIXTURE_DIR = pathlib.Path(__file__).parent / "test_fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def test_get_mlb_data_parses_fixture_summary():
    from sports import mlb

    summary = _load_fixture("espn_mlb_summary.json")
    # Build a minimal scoreboard around the same event so _match_espn_game succeeds
    scoreboard = {
        "events": [{
            "id": summary["header"]["id"],
            "competitions": [{
                "competitors": [
                    {"team": {"abbreviation": c["team"]["abbreviation"]}}
                    for c in summary["header"]["competitions"][0]["competitors"]
                ],
            }],
        }],
    }

    home_abbr = next(
        c["team"]["abbreviation"]
        for c in summary["header"]["competitions"][0]["competitors"]
        if c["homeAway"] == "home"
    )
    away_abbr = next(
        c["team"]["abbreviation"]
        for c in summary["header"]["competitions"][0]["competitors"]
        if c["homeAway"] == "away"
    )

    # Title using full team names — pick from the fixture's display names
    home_name = next(
        c["team"]["displayName"]
        for c in summary["header"]["competitions"][0]["competitors"]
        if c["homeAway"] == "home"
    )
    away_name = next(
        c["team"]["displayName"]
        for c in summary["header"]["competitions"][0]["competitors"]
        if c["homeAway"] == "away"
    )
    title = f"{away_name} vs {home_name}"

    with patch.object(mlb, "_fetch_espn_scoreboard", return_value=scoreboard), \
         patch.object(mlb, "_fetch_espn_summary", return_value=summary):
        mlb._game_cache.clear()
        data = mlb.get_mlb_data(title)

    assert data is not None
    assert data.home.abbr == mlb._normalize_espn_abbr(home_abbr)
    assert data.away.abbr == mlb._normalize_espn_abbr(away_abbr)
    assert data.status in {"pre", "live", "final"}


def test_get_mlb_data_returns_none_when_scoreboard_empty():
    from sports import mlb
    with patch.object(mlb, "_fetch_espn_scoreboard", return_value={"events": []}), \
         patch.object(mlb, "_fetch_espn_summary", return_value=None):
        # Clear caches so previous test doesn't leak
        mlb._game_cache.clear()
        assert mlb.get_mlb_data("Yankees vs Red Sox") is None


def test_mlb_overlay_can_handle_when_title_parses():
    from sports.mlb import MLBOverlay
    plugin = MLBOverlay()
    assert plugin.can_handle("Yankees vs Red Sox", ["mlb"]) is True
    assert plugin.can_handle("Will Bitcoin hit 100k?", ["mlb"]) is False


def test_mlb_overlay_registers():
    import sports
    from sports.mlb import MLBOverlay
    # Snapshot real registry, register a fresh overlay (autouse fixture in
    # other test files clears _PLUGINS; here we just verify the class works)
    plugin = MLBOverlay()
    assert plugin.sport_id == "mlb"
    assert "mlb" in plugin.tag_aliases


def test_can_handle_accepts_run_line_title_when_slug_resolves():
    from sports.mlb import MLBOverlay
    plugin = MLBOverlay()
    assert plugin.can_handle(
        "Run Line: Yankees -1.5", ["mlb"], "mlb-nyy-bos-2026-05-09"
    ) is True


def test_can_handle_rejects_unparseable_title_with_unresolvable_slug():
    from sports.mlb import MLBOverlay
    plugin = MLBOverlay()
    assert plugin.can_handle(
        "Run Line: Foo -1.5", ["mlb"], "mlb-zzz-yyy-2026-05-09"
    ) is False
