"""
Cricket game data enrichment for market pages.

Fetches live scores, ball-by-ball commentary, scorecard, odds,
and match metadata from ESPN Cricket API for IPL matches.
"""

from __future__ import annotations

import re
import time as _time

import requests as _requests

from models import (
    CricketGameData, CricketTeam, CricketInnings, BatsmanEntry,
    BowlerEntry, FoWEntry, BallEvent, CricketOdds, CricketPartnership,
    CricketSquadPlayer, CricketHeadToHead, CricketVenue, CricketToss,
)


# ---------------------------------------------------------------------------
# IPL team alias table
# ---------------------------------------------------------------------------

TEAM_ALIASES: dict[str, str] = {
    # Chennai Super Kings
    "chennai super kings": "CSK", "csk": "CSK", "chennai": "CSK", "super kings": "CSK",
    # Mumbai Indians
    "mumbai indians": "MI", "mi": "MI", "mumbai": "MI",
    # Royal Challengers Bengaluru
    "royal challengers bengaluru": "RCB", "royal challengers bangalore": "RCB",
    "rcb": "RCB", "bengaluru": "RCB", "bangalore": "RCB",
    # Kolkata Knight Riders
    "kolkata knight riders": "KKR", "kkr": "KKR", "kolkata": "KKR",
    # Delhi Capitals
    "delhi capitals": "DC", "dc": "DC", "delhi": "DC",
    # Punjab Kings
    "punjab kings": "PBKS", "pbks": "PBKS", "punjab": "PBKS",
    # Rajasthan Royals
    "rajasthan royals": "RR", "rr": "RR", "rajasthan": "RR",
    # Sunrisers Hyderabad
    "sunrisers hyderabad": "SRH", "srh": "SRH", "hyderabad": "SRH", "sunrisers": "SRH",
    # Gujarat Titans
    "gujarat titans": "GT", "gt": "GT", "gujarat": "GT",
    # Lucknow Super Giants
    "lucknow super giants": "LSG", "lsg": "LSG", "lucknow": "LSG", "super giants": "LSG",
}

# Reverse map: short code -> full team name (for display)
SHORT_TO_FULL: dict[str, str] = {
    "CSK": "Chennai Super Kings",
    "MI": "Mumbai Indians",
    "RCB": "Royal Challengers Bengaluru",
    "KKR": "Kolkata Knight Riders",
    "DC": "Delhi Capitals",
    "PBKS": "Punjab Kings",
    "RR": "Rajasthan Royals",
    "SRH": "Sunrisers Hyderabad",
    "GT": "Gujarat Titans",
    "LSG": "Lucknow Super Giants",
}

_VS_PATTERN = re.compile(r"^(.+?)\s+(?:vs\.?|v)\s+(.+)$", re.IGNORECASE)
_SUFFIX_PATTERN = re.compile(
    r"[:\-–—]?\s*(?:O/U|Over/Under|Spread|ML|Moneyline|\+\d|\-\d)\b.*$",
    re.IGNORECASE,
)
# Strip league name prefixes like "Indian Premier League: " before parsing
_LEAGUE_PREFIX = re.compile(
    r"^(?:Indian Premier League|IPL)\s*[:\-–—]\s*",
    re.IGNORECASE,
)


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a market title like 'Delhi Capitals vs Gujarat Titans'."""
    cleaned = _LEAGUE_PREFIX.sub("", title.strip())
    m = _VS_PATTERN.match(cleaned)
    if not m:
        return None
    name_a = _SUFFIX_PATTERN.sub("", m.group(1)).strip()
    name_b = _SUFFIX_PATTERN.sub("", m.group(2)).strip()
    if not name_a or not name_b:
        return None
    return name_a, name_b


def resolve_short_name(name: str) -> str | None:
    """Resolve a team name/abbreviation to its canonical short code (e.g. 'GT')."""
    return TEAM_ALIASES.get(name.lower().strip())


# ---------------------------------------------------------------------------
# ESPN Cricket API
# ---------------------------------------------------------------------------

ESPN_CRICKET_API = "https://site.api.espn.com/apis/site/v2/sports/cricket"
IPL_LEAGUE_ID = "8048"
_REQUEST_TIMEOUT = 10


def _fetch_espn_scoreboard(date_str: str | None = None) -> dict | None:
    """Fetch IPL scoreboard from ESPN. Optionally for a specific date (YYYYMMDD)."""
    params = {}
    if date_str:
        params["dates"] = date_str
    try:
        resp = _requests.get(
            f"{ESPN_CRICKET_API}/{IPL_LEAGUE_ID}/scoreboard",
            params=params,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_espn_summary(espn_match_id: str) -> dict | None:
    """Fetch match summary from ESPN (odds, squads, venue, toss, h2h)."""
    try:
        resp = _requests.get(
            f"{ESPN_CRICKET_API}/{IPL_LEAGUE_ID}/summary",
            params={"event": espn_match_id},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_espn_playbyplay(espn_match_id: str, page: int = 1) -> dict | None:
    """Fetch ball-by-ball data from ESPN (paginated, 25 per page)."""
    try:
        resp = _requests.get(
            f"{ESPN_CRICKET_API}/{IPL_LEAGUE_ID}/playbyplay",
            params={"event": espn_match_id, "page": page},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


# ESPN abbreviation normalization for IPL teams
_ESPN_ABBR_MAP: dict[str, str] = {
    "CHE": "CSK",
    "MUM": "MI",
    "BLR": "RCB", "RCB": "RCB",
    "KOL": "KKR", "KKR": "KKR",
    "DEL": "DC", "DC": "DC",
    "PUN": "PBKS", "PBKS": "PBKS", "PK": "PBKS",
    "RAJ": "RR", "RR": "RR",
    "HYD": "SRH", "SRH": "SRH",
    "GUJ": "GT", "GT": "GT",
    "LKN": "LSG", "LSG": "LSG",
    "CSK": "CSK", "MI": "MI",
}


def _normalize_espn_abbr(abbr: str) -> str:
    """Normalize ESPN cricket abbreviation to our canonical short code."""
    return _ESPN_ABBR_MAP.get(abbr.upper(), abbr.upper())


def _match_espn_game(scoreboard: dict, code_a: str, code_b: str) -> str | None:
    """Find ESPN match ID matching two team short codes in scoreboard."""
    if not scoreboard:
        return None
    pair = {code_a.upper(), code_b.upper()}
    for event in scoreboard.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])
        abbrs = {_normalize_espn_abbr(c.get("team", {}).get("abbreviation", "")) for c in competitors}
        if pair <= abbrs:
            return event.get("id")
    return None


def _extract_date_from_slug(event_slug: str) -> str | None:
    """Extract YYYYMMDD from event_slug like 'ipl-dc-gt-2026-04-08'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", event_slug)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


# ---------------------------------------------------------------------------
# ESPN data parsers
# ---------------------------------------------------------------------------

def _parse_match_status(status_data: dict) -> str:
    """Parse match status from ESPN competition status."""
    state = status_data.get("type", {}).get("state", "pre")
    if state == "in":
        return "live"
    if state == "post":
        return "final"
    return "pre"


_SCORE_PATTERN = re.compile(r"^\s*(\d+/\d+|\d+)\s*(?:\(([^)]*)\))?")


def _split_score_and_overs(score_str: str) -> tuple[str, str]:
    """Split ESPN cricket score like '209/8 (20 ov, target 211)' into
    ('209/8', '20 ov') or similar. Returns (score, overs_descriptor)."""
    if not score_str:
        return "", ""
    m = _SCORE_PATTERN.match(score_str)
    if not m:
        return score_str.strip(), ""
    score = m.group(1) or ""
    parens = m.group(2) or ""
    # Extract the overs portion from inside the parens (e.g. "20 ov, target 211" -> "20 ov")
    overs = ""
    if parens:
        # First comma-separated chunk is typically the overs
        overs = parens.split(",")[0].strip()
    return score, overs


def _parse_teams_from_header(header: dict) -> tuple[dict | None, dict | None]:
    """Extract home and away team info from ESPN header."""
    comps = header.get("competitions", [{}])
    if not comps:
        return None, None
    home_info = None
    away_info = None
    for comp in comps[0].get("competitors", []):
        team = comp.get("team", {})
        score_raw = comp.get("score", "")
        score, overs = _split_score_and_overs(score_raw)
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        logo = team.get("logos", [{}])[0].get("href") if team.get("logos") else None
        entry = {
            "name": SHORT_TO_FULL.get(abbr, team.get("displayName", "")),
            "short_name": abbr,
            "score": score,
            "overs": overs,
            "logo_url": logo,
        }
        if comp.get("homeAway") == "home":
            home_info = entry
        else:
            away_info = entry
    return home_info, away_info


def _parse_odds(odds_data: list | None) -> CricketOdds | None:
    """Parse Bet 365 odds from ESPN summary 'odds' array.

    ESPN cricket returns odds at the top level of the summary response (not
    under 'pickcenter' like basketball). Each item has the shape:
        {
          "type": "ToWIN",
          "provider": {"name": "Bet 365", ...},
          "awayTeamOdds": {"odds": {"summary": "19/25"}, "team": {...}},
          "homeTeamOdds": {"odds": {"summary": "24/25"}, "team": {...}}
        }
    """
    if not odds_data:
        return None
    pick = None
    for p in odds_data:
        provider_name = p.get("provider", {}).get("name", "")
        if "365" in provider_name or "bet" in provider_name.lower():
            pick = p
            break
    if pick is None and odds_data:
        pick = odds_data[0]
    if not pick:
        return None

    provider = pick.get("provider", {}).get("name", "Unknown")
    home_odds = pick.get("homeTeamOdds", {}).get("odds", {}).get("summary", "")
    away_odds = pick.get("awayTeamOdds", {}).get("odds", {}).get("summary", "")

    if not home_odds and not away_odds:
        return None

    return CricketOdds(
        provider=provider,
        home_odds=home_odds,
        away_odds=away_odds,
    )


def _parse_head_to_head(h2h_data: list | None) -> CricketHeadToHead | None:
    """Parse head-to-head from ESPN headToHeadGames or seasonseries."""
    if not h2h_data:
        return None
    total = len(h2h_data)
    if total == 0:
        return None
    home_wins = 0
    away_wins = 0
    for game in h2h_data:
        comps = game.get("competitions", [{}])
        if not comps:
            continue
        for comp in comps[0].get("competitors", []):
            if comp.get("winner") and comp.get("homeAway") == "home":
                home_wins += 1
            elif comp.get("winner") and comp.get("homeAway") == "away":
                away_wins += 1
    return CricketHeadToHead(home_wins=home_wins, away_wins=away_wins, total=total)


def _parse_venue(game_info: dict | None) -> CricketVenue | None:
    """Parse venue from ESPN gameInfo."""
    if not game_info:
        return None
    venue_data = game_info.get("venue", {})
    name = venue_data.get("fullName", venue_data.get("shortName", ""))
    city = venue_data.get("address", {}).get("city", "")
    if not name:
        return None
    return CricketVenue(name=name, city=city)


def _parse_toss(notes: list | None) -> CricketToss | None:
    """Parse toss info from ESPN summary 'notes' array.

    ESPN cricket returns notes as a list of {text, type} entries. The toss
    entry has type="toss" and text like "Delhi Capitals , elected to field first".
    """
    if not notes:
        return None
    toss_text = ""
    for note in notes:
        if isinstance(note, dict) and note.get("type") == "toss":
            toss_text = note.get("text", "")
            break
    if not toss_text:
        return None
    lower = toss_text.lower()
    winner = toss_text.split(",")[0].strip() if "," in toss_text else toss_text
    decision = ""
    if "bat" in lower:
        decision = "bat"
    elif "field" in lower or "bowl" in lower:
        decision = "field"
    return CricketToss(winner=winner, decision=decision)


def _parse_squads(squads_data: list | None) -> dict[str, list[CricketSquadPlayer]]:
    """Parse squad lists from ESPN summary 'squads' array.

    ESPN cricket returns squads at the top level of the summary response with
    the shape:
        [
          {
            "team": {"abbreviation": "KKR", ...},
            "athletes": [
              {"displayName": "...", "position": {"name": "Top-order batter"}, ...},
              ...
            ]
          },
          ...
        ]
    """
    if not squads_data:
        return {}
    result: dict[str, list[CricketSquadPlayer]] = {}
    for team_block in squads_data:
        team = team_block.get("team", {})
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        players = []
        for athlete in team_block.get("athletes", []):
            if not isinstance(athlete, dict):
                continue
            name = athlete.get("displayName", athlete.get("fullName", ""))
            pos = athlete.get("position", {})
            role = pos.get("name", "") if isinstance(pos, dict) else str(pos)
            if name:
                players.append(CricketSquadPlayer(name=name, role=role))
        if players:
            result[abbr] = players
    return result


def _extract_player_stats(player: dict) -> dict:
    """Flatten ESPN cricket per-player stats from nested linescores structure.

    The structure is:
        player.linescores[].linescores[].statistics.categories[].stats[]
    Each stat has {name, value, displayValue}. We flatten into a single
    {stat_name: displayValue} dict.
    """
    flat: dict[str, str] = {}
    for period_block in player.get("linescores", []):
        for entry in period_block.get("linescores", []):
            stats_block = entry.get("statistics", {})
            for cat in stats_block.get("categories", []):
                for s in cat.get("stats", []):
                    name = s.get("name")
                    if name and name not in flat:
                        flat[name] = s.get("displayValue", "")
    return flat


def _to_int(s: str) -> int:
    try:
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0


def _to_float(s: str) -> float:
    try:
        return float(s) if s else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_innings_from_rosters(rosters: list | None) -> list[CricketInnings]:
    """Parse per-team scorecard from ESPN rosters array (used for cricket).

    Each roster entry contains one team's player list with nested stats.
    We produce one CricketInnings per team containing batting + bowling entries.
    """
    if not rosters:
        return []
    innings_list = []
    for team_block in rosters:
        team = team_block.get("team", {})
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        batting: list[BatsmanEntry] = []
        bowling: list[BowlerEntry] = []

        for player in team_block.get("roster", []):
            athlete = player.get("athlete", {})
            name = athlete.get("displayName", athlete.get("fullName", ""))
            if not name:
                continue
            stats = _extract_player_stats(player)
            if not stats:
                continue

            balls_faced = _to_int(stats.get("ballsFaced", "0"))
            runs_scored = _to_int(stats.get("runs", "0"))

            # Batting: include anyone who faced a ball
            if balls_faced > 0:
                batting.append(BatsmanEntry(
                    name=name,
                    runs=runs_scored,
                    balls=balls_faced,
                    fours=_to_int(stats.get("fours", "0")),
                    sixes=_to_int(stats.get("sixes", "0")),
                    strike_rate=_to_float(stats.get("strikeRate", "0")),
                    how_out="",  # ESPN doesn't expose dismissal text here
                ))

            # Bowling: include anyone who bowled an over
            overs_bowled = stats.get("overs", "0")
            if overs_bowled and overs_bowled != "0":
                bowling.append(BowlerEntry(
                    name=name,
                    overs=str(overs_bowled),
                    maidens=_to_int(stats.get("maidens", "0")),
                    runs=_to_int(stats.get("conceded", "0")),
                    wickets=_to_int(stats.get("wickets", "0")),
                    economy=_to_float(stats.get("economyRate", stats.get("economy", "0"))),
                ))

        if batting or bowling:
            innings_list.append(CricketInnings(
                team=abbr,
                batting=batting,
                bowling=bowling,
            ))

    return innings_list


# ESPN cricket playType IDs (observed from real API responses)
# 1=run, 2=no run, 3=four, 4=six, 9=out/wicket
_BOUNDARY_PLAYTYPE_IDS = {"3", "4"}
_WICKET_PLAYTYPE_IDS = {"9"}


def _parse_single_ball(item: dict) -> BallEvent:
    """Parse a single ball/commentary item from ESPN playbyplay.

    ESPN cricket returns 'over' as a dict: {number, ball, overs, ...} where
    `number` is the 1-indexed over being bowled and `ball` is the delivery
    within it. Conventional cricket display uses the completed-overs form
    like "19.5" = 19 completed overs + 5 balls into the 20th. We store
    `over = number - 1` and `ball_in_over = ball` to match that convention.
    """
    play_type = item.get("playType", {}) or {}
    type_id = str(play_type.get("id", ""))
    type_desc = (play_type.get("description") or "").lower()

    short_text = item.get("shortText", "") or ""
    detail_text = item.get("text", short_text) or short_text
    score_value = item.get("scoreValue", 0)

    batsman_data = item.get("batsman") or {}
    bowler_data = item.get("bowler") or {}
    batsman_name = ""
    bowler_name = ""
    if isinstance(batsman_data, dict):
        athlete = batsman_data.get("athlete") or {}
        batsman_name = athlete.get("displayName", "") if isinstance(athlete, dict) else ""
    if isinstance(bowler_data, dict):
        athlete = bowler_data.get("athlete") or {}
        bowler_name = athlete.get("displayName", "") if isinstance(athlete, dict) else ""

    home_score = item.get("homeScore", "")
    away_score = item.get("awayScore", "")
    score_after = ""
    if home_score or away_score:
        score_after = f"{home_score or 0}-{away_score or 0}"

    over_field = item.get("over")
    over_int = 0
    ball_in_over = 0
    if isinstance(over_field, dict):
        over_number = over_field.get("number", 0) or 0
        ball = over_field.get("ball", 0) or 0
        try:
            over_int = max(0, int(over_number) - 1)
            ball_in_over = int(ball)
        except (ValueError, TypeError):
            pass
    elif over_field is not None:
        # Fallback for an unexpected numeric shape
        try:
            over_float = float(over_field)
            over_int = int(over_float)
            ball_in_over = round((over_float - over_int) * 10)
        except (ValueError, TypeError):
            pass

    dismissal = item.get("dismissal") or {}
    is_wicket = bool(dismissal.get("dismissal")) or type_id in _WICKET_PLAYTYPE_IDS or type_desc == "out"
    is_boundary = type_id in _BOUNDARY_PLAYTYPE_IDS or type_desc in ("four", "six")

    return BallEvent(
        over=over_int,
        ball_in_over=ball_in_over,
        batsman=batsman_name,
        bowler=bowler_name,
        runs=int(score_value) if score_value else 0,
        extras=0,
        is_boundary=is_boundary,
        is_wicket=is_wicket,
        commentary_short=short_text,
        commentary_detail=detail_text,
        score_after=score_after,
    )


def _get_pbp_page_info(pbp_data: dict) -> tuple[int, int]:
    """Return (current_page, total_pages) from the ESPN playbyplay response."""
    commentary = pbp_data.get("commentary") or {}
    page_index = int(commentary.get("pageIndex") or 1)
    page_count = int(commentary.get("pageCount") or 1)
    return page_index, page_count


def _parse_balls_from_playbyplay(pbp_data: dict | None) -> list[BallEvent]:
    """Parse ball-by-ball events from a single ESPN playbyplay page.

    ESPN cricket returns items at pbp['commentary']['items'] in chronological
    order (oldest first within a page). We reverse so callers get newest-first.
    """
    if not pbp_data:
        return []
    commentary = pbp_data.get("commentary") or {}
    items = commentary.get("items", [])
    if not items:
        items = pbp_data.get("items", [])
    parsed = [_parse_single_ball(item) for item in items]
    parsed.reverse()
    return parsed


# ---------------------------------------------------------------------------
# Cache — per-field TTLs, keyed by match_id
# ---------------------------------------------------------------------------

_CACHE_TTL = {
    "score":        15,
    "balls":        15,
    "partnership":  15,
    "innings":      30,
    "odds":         60,
    "squads":       300,
    "toss":         300,
    "venue":        300,
    "head_to_head": 300,
    "scoreboard":   60,
    "summary":      60,
}

_match_cache: dict[str, dict[str, tuple[float, object]]] = {}


def _cache_get(match_id: str, field: str):
    entry = _match_cache.get(match_id, {}).get(field)
    if entry and entry[0] > _time.time():
        return entry[1]
    return None


def _cache_set(match_id: str, field: str, data: object):
    if match_id not in _match_cache:
        _match_cache[match_id] = {}
    ttl = _CACHE_TTL.get(field, 30)
    _match_cache[match_id][field] = (_time.time() + ttl, data)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def get_cricket_data(
    title: str, *, event_slug: str = "",
) -> CricketGameData | None:
    """Main entry point: resolve a market title to live cricket game data."""
    parsed = parse_team_names(title)
    if not parsed:
        return None
    name_a, name_b = parsed

    code_a = resolve_short_name(name_a)
    code_b = resolve_short_name(name_b)
    if not code_a or not code_b:
        return None

    # Try today's scoreboard first, then the slug date
    dates_to_try = [None]
    date_str = _extract_date_from_slug(event_slug) if event_slug else None
    if date_str:
        dates_to_try.append(date_str)

    espn_match_id = None
    for d in dates_to_try:
        cache_key = f"__cricket_sb_{d or 'today'}__"
        sb = _cache_get(cache_key, "scoreboard")
        if sb is None:
            sb = _fetch_espn_scoreboard(d)
            if sb:
                _cache_set(cache_key, "scoreboard", sb)
        if sb:
            espn_match_id = _match_espn_game(sb, code_a, code_b)
            if espn_match_id:
                break

    if not espn_match_id:
        return None

    match_id = f"cricket_{espn_match_id}"

    # Fetch summary (cached)
    summary = _cache_get(match_id, "summary")
    if summary is None:
        summary = _fetch_espn_summary(espn_match_id)
        if summary:
            _cache_set(match_id, "summary", summary)

    if not summary:
        return None

    # Parse header for teams and status
    header = summary.get("header", {})
    comps = header.get("competitions", [{}])
    status_data = comps[0].get("status", {}) if comps else {}
    status = _parse_match_status(status_data)
    status_text = status_data.get("type", {}).get("shortDetail", "")
    match_time = comps[0].get("date") if comps else None

    home_info, away_info = _parse_teams_from_header(header)
    if not home_info or not away_info:
        return None

    home = CricketTeam(**home_info)
    away = CricketTeam(**away_info)

    # Parse match data from summary
    game_info = summary.get("gameInfo", {})
    situation = summary.get("situation", {})

    odds = _cache_get(match_id, "odds")
    if odds is None:
        odds = _parse_odds(summary.get("odds"))
        if odds:
            _cache_set(match_id, "odds", odds)

    toss = _cache_get(match_id, "toss")
    if toss is None:
        toss = _parse_toss(summary.get("notes"))
        if toss:
            _cache_set(match_id, "toss", toss)

    venue = _cache_get(match_id, "venue")
    if venue is None:
        venue = _parse_venue(game_info)
        if venue:
            _cache_set(match_id, "venue", venue)

    head_to_head = _cache_get(match_id, "head_to_head")
    if head_to_head is None:
        h2h_data = summary.get("headToHeadGames") or summary.get("seasonseries")
        head_to_head = _parse_head_to_head(h2h_data)
        if head_to_head:
            _cache_set(match_id, "head_to_head", head_to_head)

    # Squads (ESPN cricket returns squads at top level, not rosters)
    squads_raw = _cache_get(match_id, "squads")
    if squads_raw is None:
        squads_raw = _parse_squads(summary.get("squads"))
        if squads_raw:
            _cache_set(match_id, "squads", squads_raw)

    # Map squad keys to home/away
    squads = {}
    if squads_raw:
        if home.short_name in squads_raw:
            squads["home"] = squads_raw[home.short_name]
        if away.short_name in squads_raw:
            squads["away"] = squads_raw[away.short_name]

    # Innings/scorecard (ESPN cricket stores per-player stats in rosters)
    innings = _cache_get(match_id, "innings")
    if innings is None:
        innings = _parse_innings_from_rosters(summary.get("rosters"))
        if innings:
            _cache_set(match_id, "innings", innings)
    innings = innings or []

    # Ball-by-ball: fetch the LAST TWO pages to get ~50 newest deliveries.
    # ESPN paginates 25 balls per page in chronological order. The final page
    # may only have a few items (overflow), so the previous page is needed
    # to ensure we have a full feed for the UI.
    balls = _cache_get(match_id, "balls")
    if balls is None and status in ("live", "final"):
        first_page = _fetch_espn_playbyplay(espn_match_id, page=1)
        balls = []
        if first_page:
            _, page_count = _get_pbp_page_info(first_page)
            if page_count <= 1:
                balls = _parse_balls_from_playbyplay(first_page)
            else:
                last_page = _fetch_espn_playbyplay(espn_match_id, page=page_count)
                last_balls = _parse_balls_from_playbyplay(last_page)
                # Each ball list is newest-first within its page.
                if page_count >= 2:
                    prev_page = _fetch_espn_playbyplay(espn_match_id, page=page_count - 1)
                    prev_balls = _parse_balls_from_playbyplay(prev_page)
                    balls = last_balls + prev_balls
                else:
                    balls = last_balls
        if balls:
            _cache_set(match_id, "balls", balls)
    balls = balls or []

    # Partnership and run rate from situation
    partnership = None
    run_rate = None
    required_rate = None
    if situation:
        # ESPN situation contains current batting info
        current_batsmen = situation.get("batsmen", [])
        if len(current_batsmen) >= 2:
            b1 = current_batsmen[0].get("athlete", {}).get("displayName", "")
            b2 = current_batsmen[1].get("athlete", {}).get("displayName", "")
            p_runs = situation.get("partnershipRuns", 0)
            p_balls = situation.get("partnershipBalls", 0)
            partnership = CricketPartnership(
                runs=int(p_runs) if p_runs else 0,
                balls=int(p_balls) if p_balls else 0,
                batsman1=b1,
                batsman2=b2,
            )
        # Run rates
        rr = situation.get("currentRunRate")
        if rr:
            try:
                run_rate = round(float(rr), 2)
            except (ValueError, TypeError):
                pass
        rrr = situation.get("requiredRunRate")
        if rrr:
            try:
                required_rate = round(float(rrr), 2)
            except (ValueError, TypeError):
                pass

    return CricketGameData(
        match_id=match_id,
        espn_match_id=espn_match_id,
        status=status,
        match_time=match_time,
        status_text=status_text,
        home=home,
        away=away,
        toss=toss,
        venue=venue,
        odds=odds,
        innings=innings,
        partnership=partnership,
        run_rate=run_rate,
        required_rate=required_rate,
        balls=balls[:50],
        squads=squads,
        head_to_head=head_to_head,
    )


# ---------------------------------------------------------------------------
# Plugin wrapper
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from sports import register
from sports.base import OverlayResponse, SportOverlay


class CricketOverlay(SportOverlay):
    sport_id = "cricket"
    tag_aliases = ("cricket", "ipl", "indian premier league")

    def can_handle(self, title: str, tags: list[str], event_slug: str = "") -> bool:
        return parse_team_names(title) is not None

    def fetch(
        self,
        condition_id: str,
        title: str,
        tags: list[str],
        event_slug: str = "",
    ) -> OverlayResponse | None:
        game_data = get_cricket_data(title, event_slug=event_slug)
        if game_data is None:
            return None
        # get_cricket_data returns a Pydantic CricketGameData model.
        payload = game_data.model_dump()
        status = payload.get("status", "pre")
        return OverlayResponse(
            sport=self.sport_id,
            status=status,
            last_updated=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


register(CricketOverlay())
