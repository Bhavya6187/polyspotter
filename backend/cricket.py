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


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a market title like 'Delhi Capitals vs Gujarat Titans'."""
    m = _VS_PATTERN.match(title.strip())
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
        return "complete"
    return "pre"


def _parse_teams_from_header(header: dict) -> tuple[dict | None, dict | None]:
    """Extract home and away team info from ESPN header."""
    comps = header.get("competitions", [{}])
    if not comps:
        return None, None
    home_info = None
    away_info = None
    for comp in comps[0].get("competitors", []):
        team = comp.get("team", {})
        score_str = comp.get("score", "")
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        logo = team.get("logos", [{}])[0].get("href") if team.get("logos") else None
        entry = {
            "name": SHORT_TO_FULL.get(abbr, team.get("displayName", "")),
            "short_name": abbr,
            "score": score_str,
            "logo_url": logo,
        }
        if comp.get("homeAway") == "home":
            home_info = entry
        else:
            away_info = entry
    return home_info, away_info


def _parse_odds(pickcenter: list | None) -> CricketOdds | None:
    """Parse Bet 365 odds from ESPN pickcenter array."""
    if not pickcenter:
        return None
    pick = None
    for p in pickcenter:
        provider_name = p.get("provider", {}).get("name", "")
        if "365" in provider_name or "bet" in provider_name.lower():
            pick = p
            break
    if pick is None and pickcenter:
        pick = pickcenter[0]
    if not pick:
        return None

    provider = pick.get("provider", {}).get("name", "Unknown")
    home_odds = pick.get("homeTeamOdds", {}).get("summary", "")
    away_odds = pick.get("awayTeamOdds", {}).get("summary", "")

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


def _parse_toss(game_info: dict | None) -> CricketToss | None:
    """Parse toss info from ESPN gameInfo or situation."""
    if not game_info:
        return None
    # ESPN puts toss info in various places; check situation.note or header.gameNote
    toss_text = game_info.get("tpiNote", "") or game_info.get("note", "")
    if not toss_text:
        return None
    # Typical format: "Gujarat Titans, elected to field first"
    lower = toss_text.lower()
    winner = toss_text.split(",")[0].strip() if "," in toss_text else toss_text
    decision = ""
    if "bat" in lower:
        decision = "bat"
    elif "field" in lower or "bowl" in lower:
        decision = "field"
    return CricketToss(winner=winner, decision=decision)


def _parse_squads(rosters: list | None) -> dict[str, list[CricketSquadPlayer]]:
    """Parse squad lists from ESPN rosters/squads array."""
    if not rosters:
        return {}
    result: dict[str, list[CricketSquadPlayer]] = {}
    for team_block in rosters:
        team = team_block.get("team", {})
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        players = []
        for roster_group in team_block.get("roster", []):
            for player in roster_group.get("roster", roster_group.get("athletes", [])):
                # Handle different ESPN response shapes
                if isinstance(player, dict):
                    athlete = player.get("athlete", player)
                    name = athlete.get("displayName", athlete.get("fullName", ""))
                    pos = athlete.get("position", {})
                    role = pos.get("name", "") if isinstance(pos, dict) else str(pos)
                    if name:
                        players.append(CricketSquadPlayer(name=name, role=role))
        if players:
            result[abbr] = players
    return result


def _parse_innings_from_summary(summary: dict) -> list[CricketInnings]:
    """Parse scorecard/innings from ESPN summary rosters or boxscore."""
    innings_list = []
    # ESPN cricket puts scorecard data in the rosters or boxscore section
    # The structure varies; we'll parse what's available
    boxscore = summary.get("boxscore", {})
    teams = boxscore.get("teams", [])
    for team_block in teams:
        team = team_block.get("team", {})
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        stats = team_block.get("statistics", [])

        batting = []
        bowling = []

        for stat_group in stats:
            stat_type = stat_group.get("type", "")
            athletes = stat_group.get("athletes", [])
            labels = stat_group.get("labels", [])

            if stat_type == "batting" or "batting" in stat_group.get("name", "").lower():
                for athlete in athletes:
                    a = athlete.get("athlete", {})
                    stat_vals = athlete.get("stats", [])
                    name = a.get("displayName", "")
                    if not name or not stat_vals:
                        continue
                    # Map by label positions
                    label_map = {l: i for i, l in enumerate(labels)}
                    def _get(label, default=0):
                        idx = label_map.get(label)
                        if idx is not None and idx < len(stat_vals):
                            try:
                                return int(stat_vals[idx]) if isinstance(default, int) else float(stat_vals[idx])
                            except (ValueError, TypeError):
                                return default
                        return default
                    batting.append(BatsmanEntry(
                        name=name,
                        runs=_get("R"),
                        balls=_get("B"),
                        fours=_get("4s"),
                        sixes=_get("6s"),
                        strike_rate=_get("SR", 0.0),
                        how_out=athlete.get("description", ""),
                    ))

            elif stat_type == "bowling" or "bowling" in stat_group.get("name", "").lower():
                for athlete in athletes:
                    a = athlete.get("athlete", {})
                    stat_vals = athlete.get("stats", [])
                    name = a.get("displayName", "")
                    if not name or not stat_vals:
                        continue
                    label_map = {l: i for i, l in enumerate(labels)}
                    def _get(label, default=0):
                        idx = label_map.get(label)
                        if idx is not None and idx < len(stat_vals):
                            try:
                                return int(stat_vals[idx]) if isinstance(default, int) else float(stat_vals[idx])
                            except (ValueError, TypeError):
                                return default
                        return default
                    bowling.append(BowlerEntry(
                        name=name,
                        overs=str(stat_vals[label_map["O"]]) if "O" in label_map and label_map["O"] < len(stat_vals) else "0",
                        maidens=_get("M"),
                        runs=_get("R"),
                        wickets=_get("W"),
                        economy=_get("ECON", 0.0),
                    ))

        if batting or bowling:
            # Try to get score from header
            innings_list.append(CricketInnings(
                team=abbr,
                batting=batting,
                bowling=bowling,
            ))

    return innings_list


def _parse_balls_from_playbyplay(pbp_data: dict | None) -> list[BallEvent]:
    """Parse ball-by-ball events from ESPN playbyplay response. Returns newest-first."""
    if not pbp_data:
        return []
    items = pbp_data.get("items", [])
    balls = []
    for item in items:
        play_type = item.get("playType", {})
        type_id = play_type.get("id", "") if isinstance(play_type, dict) else ""
        short_text = item.get("shortText", "")
        detail_text = item.get("text", short_text)
        over_num = item.get("over", 0)
        ball_num = item.get("ball", item.get("ballInOver", 0))
        score_value = item.get("scoreValue", 0)

        # Determine batsman and bowler
        batsman_data = item.get("batsman", {})
        bowler_data = item.get("bowler", {})
        batsman_name = ""
        bowler_name = ""
        if isinstance(batsman_data, dict):
            athlete = batsman_data.get("athlete", {})
            batsman_name = athlete.get("displayName", "") if isinstance(athlete, dict) else ""
        if isinstance(bowler_data, dict):
            athlete = bowler_data.get("athlete", {})
            bowler_name = athlete.get("displayName", "") if isinstance(athlete, dict) else ""

        home_score = item.get("homeScore", "")
        away_score = item.get("awayScore", "")
        score_after = f"{away_score}/{home_score}" if home_score or away_score else ""

        is_wicket = "wicket" in short_text.lower() or str(type_id) in ("4",)  # ESPN wicket type
        is_boundary = any(w in short_text.upper() for w in ("FOUR", "SIX", "4 runs", "6 runs"))

        balls.append(BallEvent(
            over=int(over_num) if over_num else 0,
            ball_in_over=int(ball_num) if ball_num else 0,
            batsman=batsman_name,
            bowler=bowler_name,
            runs=int(score_value) if score_value else 0,
            extras=0,
            is_boundary=is_boundary,
            is_wicket=is_wicket,
            commentary_short=short_text,
            commentary_detail=detail_text,
            score_after=score_after,
        ))

    balls.reverse()
    return balls
