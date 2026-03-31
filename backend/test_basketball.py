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


def test_parse_espn_odds():
    from basketball import _parse_espn_odds

    mock_pickcenter = [
        {
            "provider": {"name": "DraftKings", "id": "100"},
            "details": "LAC -17.5",
            "spread": 17.5,
            "overUnder": 219.5,
            "awayTeamOdds": {"moneyLine": -1350},
            "homeTeamOdds": {"moneyLine": 800},
        }
    ]
    odds = _parse_espn_odds(mock_pickcenter, away_abbr="LAC", home_abbr="MIL")
    assert odds is not None
    assert odds.provider == "DraftKings"
    assert odds.spread.display == "LAC -17.5"
    assert odds.spread.value == -17.5
    assert odds.over_under == 219.5
    assert odds.moneyline.away == "-1350"
    assert odds.moneyline.home == "+800"


def test_parse_espn_odds_empty():
    from basketball import _parse_espn_odds
    assert _parse_espn_odds([], away_abbr="LAC", home_abbr="MIL") is None
    assert _parse_espn_odds(None, away_abbr="LAC", home_abbr="MIL") is None


def test_parse_espn_win_probability():
    from basketball import _parse_espn_win_probability

    mock_winprob = [
        {"homeWinPercentage": 0.32, "playId": 1},
        {"homeWinPercentage": 0.28, "playId": 2},
    ]
    wp = _parse_espn_win_probability(mock_winprob)
    assert wp is not None
    assert wp.home == 0.28
    assert wp.away == 0.72


def test_parse_espn_injuries():
    from basketball import _parse_espn_injuries

    mock_injuries = [
        {
            "team": {"abbreviation": "MIL"},
            "injuries": [
                {
                    "athlete": {"displayName": "K. Middleton"},
                    "status": "Out",
                    "type": {"detail": "Ankle"},
                },
            ],
        },
        {
            "team": {"abbreviation": "LAC"},
            "injuries": [],
        },
    ]
    injuries = _parse_espn_injuries(mock_injuries)
    assert len(injuries) == 1
    assert injuries[0].team == "MIL"
    assert injuries[0].player == "K. Middleton"
    assert injuries[0].status == "Out"
    assert injuries[0].detail == "Ankle"


def test_parse_nba_plays():
    from basketball import _parse_nba_plays

    mock_pbp = {
        "game": {
            "actions": [
                {
                    "actionNumber": 1, "clock": "PT11M55.00S", "period": 1,
                    "description": "Jump Ball", "actionType": "jumpball",
                    "teamTricode": "", "scoreHome": "0", "scoreAway": "0",
                    "isFieldGoal": False,
                },
                {
                    "actionNumber": 2, "clock": "PT11M30.00S", "period": 1,
                    "description": "J. Harden 3PT Made (3 PTS)",
                    "actionType": "3pt", "subType": "Jump Shot",
                    "teamTricode": "LAC", "scoreHome": "0", "scoreAway": "3",
                    "isFieldGoal": True,
                },
            ]
        }
    }
    plays = _parse_nba_plays(mock_pbp)
    assert len(plays) == 2
    assert plays[0].id == 2
    assert plays[0].type == "3pt"
    assert plays[0].team == "LAC"
    assert plays[0].scoring is True
    assert plays[0].away_score == 3
    assert plays[1].id == 1


def test_parse_nba_boxscore():
    from basketball import _parse_nba_boxscore

    mock_box = {
        "game": {
            "homeTeam": {
                "teamTricode": "MIL",
                "players": [
                    {
                        "name": "G. Antetokounmpo",
                        "nameI": "G. Antetokounmpo",
                        "position": "F",
                        "starter": "1",
                        "oncourt": "1",
                        "status": "ACTIVE",
                        "statistics": {
                            "minutes": "PT12M00.00S",
                            "points": 8, "reboundsTotal": 4, "assists": 2,
                            "steals": 1, "blocks": 0,
                            "fieldGoalsMade": 3, "fieldGoalsAttempted": 6,
                            "threePointersMade": 0, "threePointersAttempted": 1,
                            "freeThrowsMade": 2, "freeThrowsAttempted": 2,
                            "plusMinusPoints": -3.0,
                        },
                    }
                ],
            },
            "awayTeam": {
                "teamTricode": "LAC",
                "players": [],
            },
        }
    }
    box = _parse_nba_boxscore(mock_box)
    assert box.home.team == "MIL"
    assert len(box.home.players) == 1
    p = box.home.players[0]
    assert p.name == "G. Antetokounmpo"
    assert p.points == 8
    assert p.rebounds == 4
    assert p.fg == "3-6"
    assert p.starter is True
    assert p.plus_minus == -3
    assert box.away.team == "LAC"
