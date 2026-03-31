"""Tests for basketball game matching logic. No DB or network required."""

import pytest


def test_parse_team_names_standard():
    from basketball import parse_team_names
    assert parse_team_names("Clippers vs. Bucks") == ("Clippers", "Bucks")


def test_parse_team_names_vs_no_dot():
    from basketball import parse_team_names
    assert parse_team_names("Clippers vs Bucks") == ("Clippers", "Bucks")


def test_parse_team_names_v():
    from basketball import parse_team_names
    assert parse_team_names("Lakers v Celtics") == ("Lakers", "Celtics")


def test_parse_team_names_no_match():
    from basketball import parse_team_names
    assert parse_team_names("Will Bitcoin hit 100k?") is None


def test_resolve_tricode_basic():
    from basketball import resolve_tricode
    assert resolve_tricode("Clippers") == "LAC"
    assert resolve_tricode("bucks") == "MIL"
    assert resolve_tricode("LA Clippers") == "LAC"


def test_resolve_tricode_abbreviation():
    from basketball import resolve_tricode
    assert resolve_tricode("LAC") == "LAC"
    assert resolve_tricode("MIL") == "MIL"
    assert resolve_tricode("GSW") == "GSW"


def test_resolve_tricode_city():
    from basketball import resolve_tricode
    assert resolve_tricode("Milwaukee") == "MIL"
    assert resolve_tricode("Boston") == "BOS"
    assert resolve_tricode("Golden State") == "GSW"


def test_resolve_tricode_unknown():
    from basketball import resolve_tricode
    assert resolve_tricode("Unknown Team XYZ") is None


def test_resolve_tricode_76ers():
    from basketball import resolve_tricode
    assert resolve_tricode("76ers") == "PHI"
    assert resolve_tricode("Sixers") == "PHI"
    assert resolve_tricode("Philadelphia") == "PHI"


def test_match_game_from_scoreboard():
    from basketball import _match_game_in_scoreboard

    mock_scoreboard = {
        "scoreboard": {
            "games": [
                {
                    "gameId": "0022501082",
                    "gameStatus": 2,
                    "gameStatusText": "Q2 8:34",
                    "period": 2,
                    "gameClock": "PT08M34.00S",
                    "homeTeam": {
                        "teamId": 17, "teamTricode": "MIL", "teamName": "Bucks",
                        "teamCity": "Milwaukee", "wins": 35, "losses": 35, "score": 25,
                        "periods": [{"period": 1, "score": "25"}],
                    },
                    "awayTeam": {
                        "teamId": 13, "teamTricode": "LAC", "teamName": "Clippers",
                        "teamCity": "LA", "wins": 42, "losses": 28, "score": 29,
                        "periods": [{"period": 1, "score": "29"}],
                    },
                    "gameLeaders": {},
                },
                {
                    "gameId": "0022501083",
                    "gameStatus": 1,
                    "gameStatusText": "5:00 pm ET",
                    "period": 0,
                    "gameClock": "",
                    "homeTeam": {
                        "teamId": 11, "teamTricode": "IND", "teamName": "Pacers",
                        "teamCity": "Indiana", "wins": 40, "losses": 30, "score": 0,
                        "periods": [],
                    },
                    "awayTeam": {
                        "teamId": 14, "teamTricode": "MIA", "teamName": "Heat",
                        "teamCity": "Miami", "wins": 38, "losses": 32, "score": 0,
                        "periods": [],
                    },
                    "gameLeaders": {},
                },
            ]
        }
    }

    game = _match_game_in_scoreboard(mock_scoreboard, "LAC", "MIL")
    assert game is not None
    assert game["gameId"] == "0022501082"

    game = _match_game_in_scoreboard(mock_scoreboard, "MIA", "IND")
    assert game is not None
    assert game["gameId"] == "0022501083"

    game = _match_game_in_scoreboard(mock_scoreboard, "LAL", "BOS")
    assert game is None


def test_parse_nba_game_status():
    from basketball import _parse_game_status
    assert _parse_game_status(1) == "pre"
    assert _parse_game_status(2) == "live"
    assert _parse_game_status(3) == "final"


def test_parse_game_clock():
    from basketball import _parse_game_clock
    assert _parse_game_clock("PT08M34.00S") == "8:34"
    assert _parse_game_clock("PT00M05.00S") == "0:05"
    assert _parse_game_clock("") == ""
    assert _parse_game_clock("PT11M55.00S") == "11:55"
