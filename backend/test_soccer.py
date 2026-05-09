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
