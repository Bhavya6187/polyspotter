"""
Basketball game data enrichment for market pages.

Fetches live scores, play-by-play, box scores, odds, win probability,
injuries, and season series from NBA CDN and ESPN APIs.
"""

from __future__ import annotations

import re
import time as _time
from typing import Optional

import requests as _requests

from models import (
    GameData, GameTeam, GameOdds, SpreadInfo, MoneylineInfo,
    WinProbability, GamePlay, BoxScorePlayer, TeamBoxScore,
    GameBoxScore, InjuryEntry, GameSeasonSeries,
)


# ---------------------------------------------------------------------------
# Team alias table — maps names, cities, abbreviations to canonical tricode
# ---------------------------------------------------------------------------

TEAM_ALIASES: dict[str, str] = {
    # Atlanta Hawks
    "hawks": "ATL", "atlanta": "ATL", "atlanta hawks": "ATL", "atl": "ATL",
    # Boston Celtics
    "celtics": "BOS", "boston": "BOS", "boston celtics": "BOS", "bos": "BOS",
    # Brooklyn Nets
    "nets": "BKN", "brooklyn": "BKN", "brooklyn nets": "BKN", "bkn": "BKN",
    # Charlotte Hornets
    "hornets": "CHA", "charlotte": "CHA", "charlotte hornets": "CHA", "cha": "CHA",
    # Chicago Bulls
    "bulls": "CHI", "chicago": "CHI", "chicago bulls": "CHI", "chi": "CHI",
    # Cleveland Cavaliers
    "cavaliers": "CLE", "cavs": "CLE", "cleveland": "CLE", "cleveland cavaliers": "CLE", "cle": "CLE",
    # Dallas Mavericks
    "mavericks": "DAL", "mavs": "DAL", "dallas": "DAL", "dallas mavericks": "DAL", "dal": "DAL",
    # Denver Nuggets
    "nuggets": "DEN", "denver": "DEN", "denver nuggets": "DEN", "den": "DEN",
    # Detroit Pistons
    "pistons": "DET", "detroit": "DET", "detroit pistons": "DET", "det": "DET",
    # Golden State Warriors
    "warriors": "GSW", "golden state": "GSW", "golden state warriors": "GSW", "gsw": "GSW",
    # Houston Rockets
    "rockets": "HOU", "houston": "HOU", "houston rockets": "HOU", "hou": "HOU",
    # Indiana Pacers
    "pacers": "IND", "indiana": "IND", "indiana pacers": "IND", "ind": "IND",
    # LA Clippers
    "clippers": "LAC", "la clippers": "LAC", "los angeles clippers": "LAC", "lac": "LAC",
    # Los Angeles Lakers
    "lakers": "LAL", "la lakers": "LAL", "los angeles lakers": "LAL", "lal": "LAL",
    # Memphis Grizzlies
    "grizzlies": "MEM", "memphis": "MEM", "memphis grizzlies": "MEM", "mem": "MEM",
    # Miami Heat
    "heat": "MIA", "miami": "MIA", "miami heat": "MIA", "mia": "MIA",
    # Milwaukee Bucks
    "bucks": "MIL", "milwaukee": "MIL", "milwaukee bucks": "MIL", "mil": "MIL",
    # Minnesota Timberwolves
    "timberwolves": "MIN", "wolves": "MIN", "minnesota": "MIN", "minnesota timberwolves": "MIN", "min": "MIN",
    # New Orleans Pelicans
    "pelicans": "NOP", "new orleans": "NOP", "new orleans pelicans": "NOP", "nop": "NOP",
    # New York Knicks
    "knicks": "NYK", "new york": "NYK", "new york knicks": "NYK", "nyk": "NYK",
    # Oklahoma City Thunder
    "thunder": "OKC", "oklahoma city": "OKC", "oklahoma city thunder": "OKC", "okc": "OKC",
    # Orlando Magic
    "magic": "ORL", "orlando": "ORL", "orlando magic": "ORL", "orl": "ORL",
    # Philadelphia 76ers
    "76ers": "PHI", "sixers": "PHI", "philadelphia": "PHI", "philadelphia 76ers": "PHI", "phi": "PHI",
    # Phoenix Suns
    "suns": "PHX", "phoenix": "PHX", "phoenix suns": "PHX", "phx": "PHX",
    # Portland Trail Blazers
    "trail blazers": "POR", "blazers": "POR", "portland": "POR", "portland trail blazers": "POR", "por": "POR",
    # Sacramento Kings
    "kings": "SAC", "sacramento": "SAC", "sacramento kings": "SAC", "sac": "SAC",
    # San Antonio Spurs
    "spurs": "SAS", "san antonio": "SAS", "san antonio spurs": "SAS", "sas": "SAS",
    # Toronto Raptors
    "raptors": "TOR", "toronto": "TOR", "toronto raptors": "TOR", "tor": "TOR",
    # Utah Jazz
    "jazz": "UTA", "utah": "UTA", "utah jazz": "UTA", "uta": "UTA",
    # Washington Wizards
    "wizards": "WAS", "washington": "WAS", "washington wizards": "WAS", "was": "WAS",
}

_VS_PATTERN = re.compile(r"^(.+?)\s+(?:vs\.?|v)\s+(.+)$", re.IGNORECASE)


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a market title like 'Clippers vs. Bucks'."""
    m = _VS_PATTERN.match(title.strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def resolve_tricode(name: str) -> str | None:
    """Resolve a team name/city/abbreviation to its canonical tricode."""
    return TEAM_ALIASES.get(name.lower().strip())


# ---------------------------------------------------------------------------
# NBA CDN URLs
# ---------------------------------------------------------------------------

NBA_CDN = "https://cdn.nba.com/static/json/liveData"
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/basketball"

_REQUEST_TIMEOUT = 10


def _parse_game_status(status_code: int) -> str:
    """Convert NBA CDN gameStatus int to our status string."""
    if status_code == 1:
        return "pre"
    if status_code == 2:
        return "live"
    return "final"


def _parse_game_clock(iso_clock: str) -> str:
    """Convert ISO duration like 'PT08M34.00S' to '8:34'."""
    if not iso_clock:
        return ""
    m = re.match(r"PT(\d+)M([\d.]+)S", iso_clock)
    if not m:
        return iso_clock
    minutes = int(m.group(1))
    seconds = int(float(m.group(2)))
    return f"{minutes}:{seconds:02d}"


def _match_game_in_scoreboard(
    scoreboard_data: dict, tricode_a: str, tricode_b: str
) -> dict | None:
    """Find a game matching two tricodes in the NBA CDN scoreboard response."""
    games = scoreboard_data.get("scoreboard", {}).get("games", [])
    pair = {tricode_a, tricode_b}
    for game in games:
        home_tri = game.get("homeTeam", {}).get("teamTricode", "")
        away_tri = game.get("awayTeam", {}).get("teamTricode", "")
        if {home_tri, away_tri} == pair:
            return game
    return None


def _fetch_nba_scoreboard() -> dict | None:
    """Fetch today's NBA scoreboard from NBA CDN."""
    try:
        resp = _requests.get(
            f"{NBA_CDN}/scoreboard/todaysScoreboard_00.json",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_nba_play_by_play(game_id: str) -> dict | None:
    """Fetch play-by-play for a specific game from NBA CDN."""
    try:
        resp = _requests.get(
            f"{NBA_CDN}/playbyplay/playbyplay_{game_id}.json",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_nba_boxscore(game_id: str) -> dict | None:
    """Fetch box score for a specific game from NBA CDN."""
    try:
        resp = _requests.get(
            f"{NBA_CDN}/boxscore/boxscore_{game_id}.json",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None
