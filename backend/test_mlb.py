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
