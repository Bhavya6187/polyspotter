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
