"""NHL game data enrichment for market pages.

Fetches scores, scoring summary, penalties, team stats, odds, and
head-to-head from the ESPN Hockey API.
"""

from __future__ import annotations

import re
import time as _time

import requests as _requests

from models import (
    NHLGameData, NHLTeam, NHLPowerPlay, NHLScoringEvent, NHLPenalty,
    NHLGoalieLine, NHLTeamStatsLive, NHLTeamSeasonStats, NHLOdds,
    NHLVenue, NHLHeadToHead,
)


# ---------------------------------------------------------------------------
# Team alias table — name/city/abbr → canonical NHL abbr
# ---------------------------------------------------------------------------

TEAM_ALIASES: dict[str, str] = {
    # Atlantic
    "bruins": "BOS", "boston": "BOS", "boston bruins": "BOS", "bos": "BOS",
    "sabres": "BUF", "buffalo": "BUF", "buffalo sabres": "BUF", "buf": "BUF",
    "red wings": "DET", "detroit": "DET", "detroit red wings": "DET", "det": "DET",
    "panthers": "FLA", "florida": "FLA", "florida panthers": "FLA", "fla": "FLA",
    "canadiens": "MTL", "montreal": "MTL", "montreal canadiens": "MTL", "habs": "MTL", "mtl": "MTL",
    "senators": "OTT", "ottawa": "OTT", "ottawa senators": "OTT", "ott": "OTT",
    "lightning": "TB", "tampa bay": "TB", "tampa bay lightning": "TB", "tb": "TB", "tbl": "TB",
    "maple leafs": "TOR", "leafs": "TOR", "toronto": "TOR", "toronto maple leafs": "TOR", "tor": "TOR",
    # Metropolitan
    "hurricanes": "CAR", "carolina": "CAR", "carolina hurricanes": "CAR", "canes": "CAR", "car": "CAR",
    "blue jackets": "CBJ", "columbus": "CBJ", "columbus blue jackets": "CBJ", "cbj": "CBJ",
    "devils": "NJ", "new jersey": "NJ", "new jersey devils": "NJ", "nj": "NJ", "njd": "NJ",
    "islanders": "NYI", "ny islanders": "NYI", "new york islanders": "NYI", "nyi": "NYI",
    "rangers": "NYR", "ny rangers": "NYR", "new york rangers": "NYR", "nyr": "NYR",
    "flyers": "PHI", "philadelphia": "PHI", "philadelphia flyers": "PHI", "phi": "PHI",
    "penguins": "PIT", "pittsburgh": "PIT", "pittsburgh penguins": "PIT", "pit": "PIT",
    "capitals": "WSH", "washington": "WSH", "washington capitals": "WSH", "caps": "WSH", "wsh": "WSH",
    # Central
    "blackhawks": "CHI", "chicago": "CHI", "chicago blackhawks": "CHI", "chi": "CHI",
    "avalanche": "COL", "colorado": "COL", "colorado avalanche": "COL", "col": "COL",
    "stars": "DAL", "dallas": "DAL", "dallas stars": "DAL", "dal": "DAL",
    "wild": "MIN", "minnesota": "MIN", "minnesota wild": "MIN", "min": "MIN",
    "predators": "NSH", "nashville": "NSH", "nashville predators": "NSH", "preds": "NSH", "nsh": "NSH",
    "blues": "STL", "st. louis": "STL", "st louis": "STL", "st. louis blues": "STL", "stl": "STL",
    "jets": "WPG", "winnipeg": "WPG", "winnipeg jets": "WPG", "wpg": "WPG",
    "utah hockey club": "UTA", "utah": "UTA", "utah hc": "UTA", "uta": "UTA",
    # Pacific
    "ducks": "ANA", "anaheim": "ANA", "anaheim ducks": "ANA", "ana": "ANA",
    "flames": "CGY", "calgary": "CGY", "calgary flames": "CGY", "cgy": "CGY",
    "oilers": "EDM", "edmonton": "EDM", "edmonton oilers": "EDM", "edm": "EDM",
    "kings": "LA", "la kings": "LA", "los angeles kings": "LA", "la": "LA", "lak": "LA",
    "sharks": "SJ", "san jose": "SJ", "san jose sharks": "SJ", "sj": "SJ", "sjs": "SJ",
    "kraken": "SEA", "seattle": "SEA", "seattle kraken": "SEA", "sea": "SEA",
    "canucks": "VAN", "vancouver": "VAN", "vancouver canucks": "VAN", "van": "VAN",
    "golden knights": "VGK", "vegas": "VGK", "vegas golden knights": "VGK", "knights": "VGK", "vgk": "VGK",
}


_VS_PATTERN = re.compile(r"^(.+?)\s+(?:vs\.?|v)\s+(.+)$", re.IGNORECASE)
_SUFFIX_PATTERN = re.compile(
    r"[:\-–—]?\s*(?:O/U|Over/Under|Spread|ML|Moneyline|Puck\s*Line|\+\d|\-\d)\b.*$",
    re.IGNORECASE,
)
_LEAGUE_PREFIX = re.compile(r"^(?:NHL|National Hockey League|Stanley Cup)\s*[:\-–—]\s*", re.IGNORECASE)


def parse_team_names(title: str) -> tuple[str, str] | None:
    cleaned = _LEAGUE_PREFIX.sub("", title.strip())
    m = _VS_PATTERN.match(cleaned)
    if not m:
        return None
    a = _SUFFIX_PATTERN.sub("", m.group(1)).strip()
    b = _SUFFIX_PATTERN.sub("", m.group(2)).strip()
    if not a or not b:
        return None
    return a, b


def resolve_abbr(name: str) -> str | None:
    return TEAM_ALIASES.get(name.lower().strip())


_SLUG_PATTERN = re.compile(r"^nhl-([a-z0-9]{2,5})-([a-z0-9]{2,5})-\d{4}-\d{2}-\d{2}$")


def extract_codes_from_slug(event_slug: str) -> tuple[str, str] | None:
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
