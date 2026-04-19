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
    TeamStats, TeamLeader, LastFiveGame, PreGameTeamData, Predictor,
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
# Strip O/U, spread, moneyline, and other betting suffixes from team names
_SUFFIX_PATTERN = re.compile(
    r"[:\-–—]?\s*(?:O/U|Over/Under|Spread|ML|Moneyline|\+\d|\-\d)\b.*$",
    re.IGNORECASE,
)


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a market title like 'Clippers vs. Bucks'.

    Handles titles with betting suffixes like 'Nuggets: O/U 244.5' or
    'Bucks -3.5' by stripping the suffix before returning.
    """
    m = _VS_PATTERN.match(title.strip())
    if not m:
        return None
    name_a = _SUFFIX_PATTERN.sub("", m.group(1)).strip()
    name_b = _SUFFIX_PATTERN.sub("", m.group(2)).strip()
    if not name_a or not name_b:
        return None
    return name_a, name_b


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

def _fetch_espn_scoreboard(league: str = "nba", date_str: str | None = None) -> dict | None:
    """Fetch scoreboard from ESPN. Optionally for a specific date (YYYYMMDD)."""
    sport = "nba" if league == "nba" else "mens-college-basketball"
    params = {}
    if date_str:
        params["dates"] = date_str
    try:
        resp = _requests.get(
            f"{ESPN_API}/{sport}/scoreboard",
            params=params,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


# ESPN uses different abbreviations than NBA CDN for some teams
_ESPN_TRICODE_MAP = {
    "UTAH": "UTA",
    "WSH": "WAS",
    "SA": "SAS",
    "GS": "GSW",
    "NY": "NYK",
    "NO": "NOP",
    "PHO": "PHX",
}


def _normalize_espn_abbr(abbr: str) -> str:
    """Normalize ESPN abbreviation to NBA CDN tricode."""
    return _ESPN_TRICODE_MAP.get(abbr.upper(), abbr.upper())


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
        abbrs = {_normalize_espn_abbr(c.get("team", {}).get("abbreviation", "")) for c in competitors}
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


def _parse_espn_predictor(predictor_data: dict | None) -> Predictor | None:
    """Parse ESPN matchup predictor into home/away win percentages."""
    if not predictor_data:
        return None
    home = predictor_data.get("homeTeam", {})
    away = predictor_data.get("awayTeam", {})
    home_pct = float(home.get("gameProjection", 50))
    away_pct = float(away.get("gameProjection", 50))
    return Predictor(home_pct=home_pct, away_pct=away_pct)


_STAT_NAME_MAP = {
    "avgPoints": "avg_points",
    "avgPointsAgainst": "avg_points_against",
    "fieldGoalPct": "field_goal_pct",
    "threePointFieldGoalPct": "three_point_pct",
    "avgRebounds": "avg_rebounds",
    "avgAssists": "avg_assists",
    "avgBlocks": "avg_blocks",
    "avgSteals": "avg_steals",
    "streak": "streak",
}


def _parse_espn_team_stats(boxscore_teams: list, tricode: str) -> TeamStats | None:
    """Parse team season stats from ESPN boxscore.teams (pre-game format)."""
    for team_block in boxscore_teams:
        team_abbr = _normalize_espn_abbr(team_block.get("team", {}).get("abbreviation", ""))
        if team_abbr != tricode:
            continue
        stats_list = team_block.get("statistics", [])
        raw = {}
        for s in stats_list:
            name = s.get("name", "")
            val = s.get("displayValue", "")
            if name in _STAT_NAME_MAP:
                raw[_STAT_NAME_MAP[name]] = val
            elif name == "Last Ten Games":
                raw["last_ten"] = val
        if not raw:
            return None
        def _float(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return None
        return TeamStats(
            avg_points=_float(raw.get("avg_points")),
            avg_points_against=_float(raw.get("avg_points_against")),
            field_goal_pct=_float(raw.get("field_goal_pct")),
            three_point_pct=_float(raw.get("three_point_pct")),
            avg_rebounds=_float(raw.get("avg_rebounds")),
            avg_assists=_float(raw.get("avg_assists")),
            avg_blocks=_float(raw.get("avg_blocks")),
            avg_steals=_float(raw.get("avg_steals")),
            streak=raw.get("streak"),
            last_ten=raw.get("last_ten"),
        )
    return None


_LEADER_DISPLAY = {
    "pointsPerGame": "PPG",
    "assistsPerGame": "APG",
    "reboundsPerGame": "RPG",
}


def _parse_espn_leaders(leaders_data: list, tricode: str) -> list[TeamLeader]:
    """Parse team stat leaders from ESPN summary leaders array."""
    result = []
    for team_block in leaders_data:
        team_abbr = _normalize_espn_abbr(team_block.get("team", {}).get("abbreviation", ""))
        if team_abbr != tricode:
            continue
        for cat in team_block.get("leaders", []):
            cat_name = cat.get("name", "")
            for athlete in cat.get("leaders", [])[:1]:
                headshot = None
                links = athlete.get("athlete", {}).get("links", [])
                # ESPN sometimes provides headshot in athlete.headshot.href
                hs = athlete.get("athlete", {}).get("headshot", {})
                if hs:
                    headshot = hs.get("href")
                result.append(TeamLeader(
                    category=cat_name,
                    display_category=_LEADER_DISPLAY.get(cat_name, cat_name),
                    player=athlete.get("athlete", {}).get("displayName", ""),
                    value=athlete.get("displayValue", ""),
                    headshot=headshot,
                ))
    return result


def _parse_espn_last_five(last_five_data: list, tricode: str) -> list[LastFiveGame]:
    """Parse last five games from ESPN summary lastFiveGames array."""
    result = []
    for team_block in last_five_data:
        team_abbr = _normalize_espn_abbr(team_block.get("team", {}).get("abbreviation", ""))
        if team_abbr != tricode:
            continue
        for evt in team_block.get("events", []):
            opp_abbr = _normalize_espn_abbr(evt.get("opponent", {}).get("abbreviation", ""))
            result.append(LastFiveGame(
                opponent=opp_abbr,
                at_vs=evt.get("atVs", ""),
                result=evt.get("gameResult", ""),
                score=evt.get("score", ""),
            ))
    return result


def _parse_espn_team_records(header: dict, tricode: str) -> tuple[str | None, str | None]:
    """Extract home/away record from ESPN header competitors."""
    comps = header.get("competitions", [{}])
    if not comps:
        return None, None
    for comp in comps[0].get("competitors", []):
        team_abbr = _normalize_espn_abbr(comp.get("team", {}).get("abbreviation", ""))
        if team_abbr != tricode:
            continue
        records = comp.get("record", [])
        home_rec = None
        away_rec = None
        for r in records:
            if r.get("type") == "home":
                home_rec = r.get("summary")
            elif r.get("type") in ("road", "away"):
                away_rec = r.get("summary")
        return home_rec, away_rec
    return None, None


def _extract_date_from_slug(event_slug: str) -> str | None:
    """Extract YYYYMMDD from event_slug like 'nba-min-det-2026-04-02'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", event_slug)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


_SLUG_TRICODE_PATTERN = re.compile(
    r"^(?:nba|ncaa)-([a-z0-9]{2,6})-([a-z0-9]{2,6})-\d{4}-\d{2}-\d{2}$"
)


def extract_tricodes_from_slug(event_slug: str) -> tuple[str, str] | None:
    """Extract two team tricodes from an event_slug like 'nba-phx-okc-2026-04-19'.

    Used as a fallback when parsing team names from the market title fails —
    for spread/moneyline/over-under markets whose title names only one team
    (e.g. 'Spread: Thunder (-15.5)'). Returns uppercase tricodes or None if
    either token doesn't resolve to a known team.
    """
    if not event_slug:
        return None
    m = _SLUG_TRICODE_PATTERN.match(event_slug)
    if not m:
        return None
    tri_a = resolve_tricode(m.group(1))
    tri_b = resolve_tricode(m.group(2))
    if not tri_a or not tri_b:
        return None
    return tri_a, tri_b


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

# ---------------------------------------------------------------------------
# Cache — per-field TTLs, keyed by game_id
# ---------------------------------------------------------------------------

_CACHE_TTL = {
    "score":          15,
    "plays":          15,
    "box_score":      30,
    "odds":           60,
    "win_probability": 60,
    "predictor":      600,
    "injuries":       300,
    "season_series":  600,
    "home_pregame":   600,
    "away_pregame":   600,
    "espn":           60,
}

_game_cache: dict[str, dict[str, tuple[float, object]]] = {}


def _cache_get(game_id: str, field: str):
    entry = _game_cache.get(game_id, {}).get(field)
    if entry and entry[0] > _time.time():
        return entry[1]
    return None


def _cache_set(game_id: str, field: str, data: object):
    if game_id not in _game_cache:
        _game_cache[game_id] = {}
    ttl = _CACHE_TTL.get(field, 30)
    _game_cache[game_id][field] = (_time.time() + ttl, data)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def get_basketball_data(
    title: str, tags: list[str], *, league: str = "nba",
    event_slug: str = "",
) -> GameData | None:
    """Main entry point: resolve a market title to live basketball game data.

    For games not on today's NBA CDN scoreboard (upcoming games), falls back
    to the ESPN API using the date extracted from *event_slug*.
    """
    tri_a: str | None = None
    tri_b: str | None = None

    parsed = parse_team_names(title)
    if parsed:
        tri_a = resolve_tricode(parsed[0])
        tri_b = resolve_tricode(parsed[1])

    # Fallback: spread/moneyline/over-under titles name only one team
    # (e.g. "Spread: Thunder (-15.5)"). The event_slug carries both tricodes.
    if (not tri_a or not tri_b) and event_slug:
        from_slug = extract_tricodes_from_slug(event_slug)
        if from_slug:
            tri_a, tri_b = from_slug

    if not tri_a or not tri_b:
        return None

    # --- Try NBA CDN scoreboard first (today's games) ----------------------
    scoreboard = _cache_get("__scoreboard__", "nba")
    if scoreboard is None:
        scoreboard = _fetch_nba_scoreboard()
        if scoreboard:
            _cache_set("__scoreboard__", "nba", scoreboard)

    nba_game = None
    if scoreboard:
        nba_game = _match_game_in_scoreboard(scoreboard, tri_a, tri_b)

    # --- If found on today's scoreboard, use NBA CDN path ------------------
    if nba_game:
        return _build_game_data_nba(nba_game, tri_a, tri_b, league)

    # --- Not on today's scoreboard — try ESPN for the game date ------------
    date_str = _extract_date_from_slug(event_slug) if event_slug else None
    return _build_game_data_espn_only(tri_a, tri_b, league, date_str)


def _build_game_data_nba(
    nba_game: dict, tri_a: str, tri_b: str, league: str,
) -> GameData:
    """Build GameData from an NBA CDN scoreboard game (today's games)."""
    game_id = nba_game["gameId"]
    home_team = nba_game["homeTeam"]
    away_team = nba_game["awayTeam"]
    status = _parse_game_status(nba_game.get("gameStatus", 1))
    clock = _parse_game_clock(nba_game.get("gameClock", ""))
    period = nba_game.get("period", 0)

    period_label = ""
    if period > 0 and period <= 4:
        period_label = f"Q{period}"
    elif period > 4:
        period_label = f"OT{period - 4}"

    game_time = nba_game.get("gameTimeUTC")

    home = GameTeam(
        tricode=home_team.get("teamTricode", ""),
        name=home_team.get("teamName", ""),
        city=home_team.get("teamCity", ""),
        score=home_team.get("score", 0),
        record=f"{home_team.get('wins', 0)}-{home_team.get('losses', 0)}",
        quarter_scores=[int(p.get("score", 0)) for p in home_team.get("periods", [])],
    )
    away = GameTeam(
        tricode=away_team.get("teamTricode", ""),
        name=away_team.get("teamName", ""),
        city=away_team.get("teamCity", ""),
        score=away_team.get("score", 0),
        record=f"{away_team.get('wins', 0)}-{away_team.get('losses', 0)}",
        quarter_scores=[int(p.get("score", 0)) for p in away_team.get("periods", [])],
    )

    plays = []
    if status in ("live", "final"):
        plays = _cache_get(game_id, "plays")
        if plays is None:
            pbp_data = _fetch_nba_play_by_play(game_id)
            plays = _parse_nba_plays(pbp_data)
            _cache_set(game_id, "plays", plays)

    box_score = None
    if status in ("live", "final"):
        box_score = _cache_get(game_id, "box_score")
        if box_score is None:
            box_data = _fetch_nba_boxscore(game_id)
            box_score = _parse_nba_boxscore(box_data)
            if box_score:
                _cache_set(game_id, "box_score", box_score)

    espn_game_id = None
    odds = _cache_get(game_id, "odds")
    win_prob = _cache_get(game_id, "win_probability")
    injuries = _cache_get(game_id, "injuries")
    season_series = _cache_get(game_id, "season_series")
    predictor = _cache_get(game_id, "predictor")
    home_pregame = _cache_get(game_id, "home_pregame")
    away_pregame = _cache_get(game_id, "away_pregame")
    venue = None
    broadcast = None

    needs_espn = (
        odds is None or win_prob is None or injuries is None
        or season_series is None or predictor is None
        or (status == "pre" and home_pregame is None)
    )
    if needs_espn:
        espn_scoreboard = _fetch_espn_scoreboard(league)
        espn_game_id = _match_espn_game(espn_scoreboard, tri_a, tri_b)
        if espn_game_id:
            summary = _fetch_espn_summary(espn_game_id, league)
            if summary:
                odds, win_prob, injuries, season_series, predictor, \
                    home_pregame, away_pregame, venue, broadcast = \
                    _extract_espn_fields(
                        summary, game_id, home.tricode, away.tricode,
                        odds, win_prob, injuries, season_series,
                        predictor, home_pregame, away_pregame,
                    )

    return GameData(
        game_id=game_id,
        espn_game_id=espn_game_id,
        league=league,
        status=status,
        clock=clock,
        period=period,
        period_label=period_label,
        game_time=game_time,
        home=home,
        away=away,
        odds=odds,
        win_probability=win_prob,
        predictor=predictor,
        plays=plays[:50],
        box_score=box_score,
        injuries=injuries or [],
        season_series=season_series,
        home_pregame=home_pregame,
        away_pregame=away_pregame,
        venue=venue,
        broadcast=broadcast,
    )


def _build_game_data_espn_only(
    tri_a: str, tri_b: str, league: str, date_str: str | None,
) -> GameData | None:
    """Build GameData purely from ESPN (for future games not on NBA CDN)."""
    # Try today first, then the slug date
    dates_to_try = [None]  # None = today's ESPN scoreboard
    if date_str:
        dates_to_try.append(date_str)

    espn_game_id = None
    for d in dates_to_try:
        cache_key = f"__espn_sb_{d or 'today'}__"
        espn_sb = _cache_get(cache_key, "espn")
        if espn_sb is None:
            espn_sb = _fetch_espn_scoreboard(league, d)
            if espn_sb:
                _cache_set(cache_key, "espn", espn_sb)
        if espn_sb:
            espn_game_id = _match_espn_game(espn_sb, tri_a, tri_b)
            if espn_game_id:
                break

    if not espn_game_id:
        return None

    summary = _fetch_espn_summary(espn_game_id, league)
    if not summary:
        return None

    # Extract teams from header
    header = summary.get("header", {})
    comps = header.get("competitions", [{}])
    if not comps:
        return None

    home_info = None
    away_info = None
    for comp in comps[0].get("competitors", []):
        team = comp.get("team", {})
        tri = _normalize_espn_abbr(team.get("abbreviation", ""))
        records = comp.get("record", [])
        total_rec = None
        for r in records:
            if r.get("type") == "total":
                total_rec = r.get("summary")
        entry = {
            "tricode": tri,
            "name": team.get("shortDisplayName", team.get("displayName", "")),
            "city": team.get("location", ""),
            "record": total_rec,
        }
        if comp.get("homeAway") == "home":
            home_info = entry
        else:
            away_info = entry

    if not home_info or not away_info:
        return None

    game_id = f"espn_{espn_game_id}"
    game_time = comps[0].get("date")

    home = GameTeam(
        tricode=home_info["tricode"],
        name=home_info["name"],
        city=home_info["city"],
        score=0,
        record=home_info["record"],
    )
    away = GameTeam(
        tricode=away_info["tricode"],
        name=away_info["name"],
        city=away_info["city"],
        score=0,
        record=away_info["record"],
    )

    # Parse all available pre-game data from ESPN summary
    odds = _parse_espn_odds(
        summary.get("pickcenter"),
        away_abbr=away.tricode, home_abbr=home.tricode,
    )
    injuries = _parse_espn_injuries(summary.get("injuries"))
    season_series = _parse_espn_season_series(summary.get("seasonseries"))
    predictor = _parse_espn_predictor(summary.get("predictor"))

    # Team stats from boxscore.teams (pre-game format = season averages)
    box_teams = summary.get("boxscore", {}).get("teams", [])
    leaders_data = summary.get("leaders", [])
    last_five_data = summary.get("lastFiveGames", [])

    home_rec_h, home_rec_a = _parse_espn_team_records(header, home.tricode)
    away_rec_h, away_rec_a = _parse_espn_team_records(header, away.tricode)

    home_pregame = PreGameTeamData(
        stats=_parse_espn_team_stats(box_teams, home.tricode),
        leaders=_parse_espn_leaders(leaders_data, home.tricode),
        last_five=_parse_espn_last_five(last_five_data, home.tricode),
        record_home=home_rec_h,
        record_away=home_rec_a,
    )
    away_pregame = PreGameTeamData(
        stats=_parse_espn_team_stats(box_teams, away.tricode),
        leaders=_parse_espn_leaders(leaders_data, away.tricode),
        last_five=_parse_espn_last_five(last_five_data, away.tricode),
        record_home=away_rec_h,
        record_away=away_rec_a,
    )

    venue = None
    broadcast = None
    game_info = summary.get("gameInfo", {})
    venue_info = game_info.get("venue", {})
    if venue_info:
        venue = venue_info.get("fullName")

    broadcasts_data = summary.get("broadcasts", [])
    if broadcasts_data:
        first = broadcasts_data[0] if isinstance(broadcasts_data[0], dict) else {}
        names = first.get("names", [])
        broadcast = names[0] if names else None

    return GameData(
        game_id=game_id,
        espn_game_id=espn_game_id,
        league=league,
        status="pre",
        clock="",
        period=0,
        period_label="",
        game_time=game_time,
        home=home,
        away=away,
        odds=odds,
        win_probability=None,
        predictor=predictor,
        plays=[],
        box_score=None,
        injuries=injuries or [],
        season_series=season_series,
        home_pregame=home_pregame,
        away_pregame=away_pregame,
        venue=venue,
        broadcast=broadcast,
    )


def _extract_espn_fields(
    summary: dict, game_id: str,
    home_tri: str, away_tri: str,
    odds, win_prob, injuries, season_series,
    predictor, home_pregame, away_pregame,
):
    """Extract and cache all ESPN fields from a summary response."""
    venue = None
    broadcast = None

    if odds is None:
        odds = _parse_espn_odds(
            summary.get("pickcenter"),
            away_abbr=away_tri, home_abbr=home_tri,
        )
        if odds:
            _cache_set(game_id, "odds", odds)

    if win_prob is None:
        win_prob = _parse_espn_win_probability(summary.get("winprobability"))
        if win_prob:
            _cache_set(game_id, "win_probability", win_prob)

    if injuries is None:
        injuries = _parse_espn_injuries(summary.get("injuries"))
        _cache_set(game_id, "injuries", injuries)

    if season_series is None:
        season_series = _parse_espn_season_series(summary.get("seasonseries"))
        if season_series:
            _cache_set(game_id, "season_series", season_series)

    if predictor is None:
        predictor = _parse_espn_predictor(summary.get("predictor"))
        if predictor:
            _cache_set(game_id, "predictor", predictor)

    if home_pregame is None:
        header = summary.get("header", {})
        box_teams = summary.get("boxscore", {}).get("teams", [])
        leaders_data = summary.get("leaders", [])
        last_five_data = summary.get("lastFiveGames", [])
        h_rec_h, h_rec_a = _parse_espn_team_records(header, home_tri)
        a_rec_h, a_rec_a = _parse_espn_team_records(header, away_tri)
        home_pregame = PreGameTeamData(
            stats=_parse_espn_team_stats(box_teams, home_tri),
            leaders=_parse_espn_leaders(leaders_data, home_tri),
            last_five=_parse_espn_last_five(last_five_data, home_tri),
            record_home=h_rec_h, record_away=h_rec_a,
        )
        away_pregame = PreGameTeamData(
            stats=_parse_espn_team_stats(box_teams, away_tri),
            leaders=_parse_espn_leaders(leaders_data, away_tri),
            last_five=_parse_espn_last_five(last_five_data, away_tri),
            record_home=a_rec_h, record_away=a_rec_a,
        )
        _cache_set(game_id, "home_pregame", home_pregame)
        _cache_set(game_id, "away_pregame", away_pregame)

    header = summary.get("header", {})
    comps = header.get("competitions", [{}])
    if comps:
        venue_info = comps[0].get("venue", {})
        venue = venue_info.get("fullName")
        broadcasts = comps[0].get("broadcasts", [])
        if broadcasts:
            names = broadcasts[0].get("names", [])
            broadcast = names[0] if names else None

    return odds, win_prob, injuries, season_series, predictor, \
        home_pregame, away_pregame, venue, broadcast
