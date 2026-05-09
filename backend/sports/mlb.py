"""MLB game data enrichment for market pages.

Fetches scores, linescore, scoring plays, box, odds, probable pitchers,
and head-to-head from the ESPN Baseball API.
"""

from __future__ import annotations

import re
import time as _time

import requests as _requests

from models import (
    MLBGameData, MLBTeam, MLBCount, MLBRunners, MLBLinescoreInning,
    MLBScoringPlay, MLBBoxBatter, MLBBoxPitcher, MLBTeamBox,
    MLBOdds, MLBVenue, MLBWeather, MLBProbablePitcher, MLBHeadToHead,
)


# ---------------------------------------------------------------------------
# Team alias table — maps name/city/abbr to canonical 2-3 letter abbr
# (matches ESPN's MLB abbreviation set).
# ---------------------------------------------------------------------------

TEAM_ALIASES: dict[str, str] = {
    # AL East
    "yankees": "NYY", "new york yankees": "NYY", "ny yankees": "NYY", "nyy": "NYY",
    "red sox": "BOS", "boston": "BOS", "boston red sox": "BOS", "bos": "BOS",
    "blue jays": "TOR", "toronto": "TOR", "toronto blue jays": "TOR", "tor": "TOR",
    "rays": "TB", "tampa bay": "TB", "tampa bay rays": "TB", "tb": "TB", "tbr": "TB",
    "orioles": "BAL", "baltimore": "BAL", "baltimore orioles": "BAL", "bal": "BAL",
    # AL Central
    "white sox": "CWS", "chicago white sox": "CWS", "cws": "CWS", "chw": "CWS",
    "guardians": "CLE", "cleveland": "CLE", "cleveland guardians": "CLE", "cle": "CLE",
    "tigers": "DET", "detroit": "DET", "detroit tigers": "DET", "det": "DET",
    "twins": "MIN", "minnesota": "MIN", "minnesota twins": "MIN", "min": "MIN",
    "royals": "KC", "kansas city": "KC", "kansas city royals": "KC", "kc": "KC", "kcr": "KC",
    # AL West
    "astros": "HOU", "houston": "HOU", "houston astros": "HOU", "hou": "HOU",
    "rangers": "TEX", "texas": "TEX", "texas rangers": "TEX", "tex": "TEX",
    "mariners": "SEA", "seattle": "SEA", "seattle mariners": "SEA", "sea": "SEA",
    "athletics": "ATH", "oakland athletics": "ATH", "oakland": "ATH", "ath": "ATH", "oak": "ATH",
    "angels": "LAA", "la angels": "LAA", "los angeles angels": "LAA", "laa": "LAA",
    # NL East
    "mets": "NYM", "new york mets": "NYM", "ny mets": "NYM", "nym": "NYM",
    "phillies": "PHI", "philadelphia": "PHI", "philadelphia phillies": "PHI", "phi": "PHI",
    "braves": "ATL", "atlanta": "ATL", "atlanta braves": "ATL", "atl": "ATL",
    "marlins": "MIA", "miami": "MIA", "miami marlins": "MIA", "mia": "MIA",
    "nationals": "WSH", "washington": "WSH", "washington nationals": "WSH", "wsh": "WSH", "was": "WSH",
    # NL Central
    "cubs": "CHC", "chicago cubs": "CHC", "chc": "CHC",
    "cardinals": "STL", "st. louis": "STL", "st louis": "STL", "st. louis cardinals": "STL", "stl": "STL",
    "brewers": "MIL", "milwaukee": "MIL", "milwaukee brewers": "MIL", "mil": "MIL",
    "reds": "CIN", "cincinnati": "CIN", "cincinnati reds": "CIN", "cin": "CIN",
    "pirates": "PIT", "pittsburgh": "PIT", "pittsburgh pirates": "PIT", "pit": "PIT",
    # NL West
    "dodgers": "LAD", "la dodgers": "LAD", "los angeles dodgers": "LAD", "lad": "LAD",
    "padres": "SD", "san diego": "SD", "san diego padres": "SD", "sd": "SD", "sdp": "SD",
    "giants": "SF", "san francisco": "SF", "san francisco giants": "SF", "sf": "SF", "sfg": "SF",
    "diamondbacks": "ARI", "arizona": "ARI", "arizona diamondbacks": "ARI", "dbacks": "ARI", "ari": "ARI",
    "rockies": "COL", "colorado": "COL", "colorado rockies": "COL", "col": "COL",
}


# ---------------------------------------------------------------------------
# Title and slug parsing
# ---------------------------------------------------------------------------

_VS_PATTERN = re.compile(r"^(.+?)\s+(?:vs\.?|v)\s+(.+)$", re.IGNORECASE)
_SUFFIX_PATTERN = re.compile(
    r"[:\-–—]?\s*(?:O/U|Over/Under|Spread|ML|Moneyline|Run\s*Line|\+\d|\-\d)\b.*$",
    re.IGNORECASE,
)
_LEAGUE_PREFIX = re.compile(
    r"^(?:MLB|Major League Baseball|World Series)\s*[:\-–—]\s*",
    re.IGNORECASE,
)


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a market title like 'Yankees vs. Red Sox'."""
    cleaned = _LEAGUE_PREFIX.sub("", title.strip())
    m = _VS_PATTERN.match(cleaned)
    if not m:
        return None
    name_a = _SUFFIX_PATTERN.sub("", m.group(1)).strip()
    name_b = _SUFFIX_PATTERN.sub("", m.group(2)).strip()
    if not name_a or not name_b:
        return None
    return name_a, name_b


def resolve_abbr(name: str) -> str | None:
    """Resolve a team name/city/abbreviation to its canonical abbr."""
    return TEAM_ALIASES.get(name.lower().strip())


_SLUG_PATTERN = re.compile(
    r"^mlb-([a-z0-9]{2,5})-([a-z0-9]{2,5})-\d{4}-\d{2}-\d{2}$"
)


def extract_codes_from_slug(event_slug: str) -> tuple[str, str] | None:
    """Extract two team abbrs from a slug like 'mlb-nyy-bos-2026-05-09'.

    Used as a fallback when the title names only one team
    (e.g. "Run Line: Yankees -1.5"). Returns uppercase abbrs or None.
    """
    if not event_slug:
        return None
    m = _SLUG_PATTERN.match(event_slug)
    if not m:
        return None
    a = resolve_abbr(m.group(1))
    b = resolve_abbr(m.group(2))
    if not a or not b:
        return None
    return a, b
