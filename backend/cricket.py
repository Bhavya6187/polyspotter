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
