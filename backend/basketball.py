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


# ---------------------------------------------------------------------------
# ESPN API fetching
# ---------------------------------------------------------------------------

def _fetch_espn_scoreboard(league: str = "nba") -> dict | None:
    """Fetch today's scoreboard from ESPN. league: 'nba' or 'mens-college-basketball'."""
    sport = "nba" if league == "nba" else "mens-college-basketball"
    try:
        resp = _requests.get(
            f"{ESPN_API}/{sport}/scoreboard",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _match_espn_game(scoreboard: dict, tricode_a: str, tricode_b: str) -> str | None:
    """Find ESPN game ID matching two team abbreviations."""
    if not scoreboard:
        return None
    pair = {tricode_a.upper(), tricode_b.upper()}
    for event in scoreboard.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])
        abbrs = {c.get("team", {}).get("abbreviation", "").upper() for c in competitors}
        if pair <= abbrs:
            return event.get("id")
    return None


def _fetch_espn_summary(espn_game_id: str, league: str = "nba") -> dict | None:
    """Fetch game summary (odds, win prob, injuries, plays) from ESPN."""
    sport = "nba" if league == "nba" else "mens-college-basketball"
    try:
        resp = _requests.get(
            f"{ESPN_API}/{sport}/summary",
            params={"event": espn_game_id},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# ESPN data parsers
# ---------------------------------------------------------------------------

def _parse_espn_odds(
    pickcenter: list | None, *, away_abbr: str, home_abbr: str
) -> GameOdds | None:
    """Parse DraftKings odds from ESPN pickcenter array."""
    if not pickcenter:
        return None
    pick = None
    for p in pickcenter:
        if p.get("provider", {}).get("name") == "DraftKings":
            pick = p
            break
    if pick is None:
        pick = pickcenter[0]

    details = pick.get("details", "")
    spread_val = pick.get("spread")
    ou = pick.get("overUnder")
    away_ml = pick.get("awayTeamOdds", {}).get("moneyLine")
    home_ml = pick.get("homeTeamOdds", {}).get("moneyLine")

    spread_info = None
    if spread_val is not None and details:
        spread_team = away_abbr if spread_val > 0 else home_abbr
        display = details
        spread_info = SpreadInfo(
            display=display,
            value=-abs(spread_val) if spread_team == away_abbr else abs(spread_val),
            team=spread_team,
        )

    ml_info = None
    if away_ml is not None and home_ml is not None:
        ml_info = MoneylineInfo(
            home=f"+{int(home_ml)}" if home_ml > 0 else str(int(home_ml)),
            away=f"+{int(away_ml)}" if away_ml > 0 else str(int(away_ml)),
        )

    return GameOdds(
        provider=pick.get("provider", {}).get("name", "Unknown"),
        spread=spread_info,
        over_under=float(ou) if ou is not None else None,
        moneyline=ml_info,
    )


def _parse_espn_win_probability(winprob: list | None) -> WinProbability | None:
    """Parse latest win probability from ESPN winprobability array."""
    if not winprob:
        return None
    latest = winprob[-1]
    home_wp = latest.get("homeWinPercentage", 0.5)
    return WinProbability(home=round(home_wp, 4), away=round(1 - home_wp, 4))


def _parse_espn_injuries(injuries_data: list | None) -> list[InjuryEntry]:
    """Parse injuries from ESPN summary injuries array."""
    if not injuries_data:
        return []
    result = []
    for team_block in injuries_data:
        team_abbr = team_block.get("team", {}).get("abbreviation", "")
        for inj in team_block.get("injuries", []):
            athlete = inj.get("athlete", {})
            result.append(InjuryEntry(
                team=team_abbr,
                player=athlete.get("displayName", "Unknown"),
                status=inj.get("status", "Unknown"),
                detail=inj.get("type", {}).get("detail", ""),
            ))
    return result


def _parse_espn_season_series(series_data: list | None) -> GameSeasonSeries | None:
    """Parse season series from ESPN summary."""
    if not series_data:
        return None
    total = len(series_data)
    if total == 0:
        return None
    home_wins = 0
    away_wins = 0
    for game in series_data:
        comps = game.get("competitions", [{}])
        if not comps:
            continue
        for comp in comps[0].get("competitors", []):
            if comp.get("winner") and comp.get("homeAway") == "home":
                home_wins += 1
            elif comp.get("winner") and comp.get("homeAway") == "away":
                away_wins += 1
    return GameSeasonSeries(
        home_wins=home_wins,
        away_wins=away_wins,
        total_games=total,
    )


# ---------------------------------------------------------------------------
# NBA CDN data parsers
# ---------------------------------------------------------------------------

def _parse_player_minutes(iso_minutes: str) -> str:
    """Convert ISO duration like 'PT12M00.00S' to '12:00'."""
    if not iso_minutes:
        return "0:00"
    m = re.match(r"PT(\d+)M([\d.]+)S", iso_minutes)
    if not m:
        return iso_minutes
    mins = int(m.group(1))
    secs = int(float(m.group(2)))
    return f"{mins}:{secs:02d}"


def _parse_nba_plays(pbp_data: dict | None) -> list[GamePlay]:
    """Parse play-by-play from NBA CDN response. Returns newest-first."""
    if not pbp_data:
        return []
    actions = pbp_data.get("game", {}).get("actions", [])
    plays = []
    for a in actions:
        scoring = a.get("isFieldGoal", False) or a.get("actionType") == "freethrow" and "Made" in a.get("description", "")
        plays.append(GamePlay(
            id=a.get("actionNumber", 0),
            clock=_parse_game_clock(a.get("clock", "")),
            period=a.get("period", 0),
            text=a.get("description", ""),
            away_score=int(a.get("scoreAway", 0) or 0),
            home_score=int(a.get("scoreHome", 0) or 0),
            type=a.get("actionType", ""),
            team=a.get("teamTricode", ""),
            scoring=bool(scoring),
        ))
    plays.reverse()
    return plays


def _parse_nba_boxscore(box_data: dict | None) -> GameBoxScore | None:
    """Parse box score from NBA CDN response."""
    if not box_data:
        return None
    game = box_data.get("game", {})

    def parse_team(team_data: dict) -> TeamBoxScore:
        players = []
        for p in team_data.get("players", []):
            stats = p.get("statistics", {})
            if not stats or p.get("status") != "ACTIVE":
                continue
            fgm = stats.get("fieldGoalsMade", 0)
            fga = stats.get("fieldGoalsAttempted", 0)
            tpm = stats.get("threePointersMade", 0)
            tpa = stats.get("threePointersAttempted", 0)
            ftm = stats.get("freeThrowsMade", 0)
            fta = stats.get("freeThrowsAttempted", 0)
            players.append(BoxScorePlayer(
                name=p.get("nameI", p.get("name", "")),
                position=p.get("position", ""),
                starter=str(p.get("starter", "0")) == "1",
                minutes=_parse_player_minutes(stats.get("minutes", "")),
                points=stats.get("points", 0),
                rebounds=stats.get("reboundsTotal", 0),
                assists=stats.get("assists", 0),
                steals=stats.get("steals", 0),
                blocks=stats.get("blocks", 0),
                fg=f"{fgm}-{fga}",
                three_pt=f"{tpm}-{tpa}",
                ft=f"{ftm}-{fta}",
                plus_minus=int(stats.get("plusMinusPoints", 0)),
            ))
        return TeamBoxScore(team=team_data.get("teamTricode", ""), players=players)

    return GameBoxScore(
        home=parse_team(game.get("homeTeam", {})),
        away=parse_team(game.get("awayTeam", {})),
    )
