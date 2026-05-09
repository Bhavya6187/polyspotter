"""Soccer game data enrichment for market pages.

Supports EPL (eng.1), UEFA Champions League (uefa.champions), and FIFA
World Cup (fifa.world). League is resolved from market tags; team
resolution uses a hard-coded EPL alias table plus ESPN-name fallback for
UCL / WC.
"""

from __future__ import annotations

import re
import time as _time

import requests as _requests

from models import (
    SoccerGameData, SoccerTeam, SoccerGoal, SoccerCard, SoccerSub,
    SoccerStats, SoccerLineup, SoccerLineupPlayer, SoccerOdds,
    SoccerVenue, SoccerHeadToHead, SoccerAggregate, SoccerPenShootout,
)


# ---------------------------------------------------------------------------
# League dispatch
# ---------------------------------------------------------------------------

LEAGUE_TAG_MAP: dict[tuple[str, ...], str] = {
    ("epl", "english premier league", "premier league"): "eng.1",
    ("ucl", "uefa champions league", "champions league"): "uefa.champions",
    ("world cup", "fifa world cup"): "fifa.world",
}

LEAGUE_DISPLAY: dict[str, str] = {
    "eng.1": "EPL",
    "uefa.champions": "UCL",
    "fifa.world": "World Cup",
}


def resolve_league(tags: list[str]) -> str | None:
    """Resolve the ESPN league ID from market tags.

    Returns 'eng.1', 'uefa.champions', 'fifa.world', or None if no
    in-scope league tag is present.
    """
    lower = {t.lower() for t in tags if t}
    for aliases, league_id in LEAGUE_TAG_MAP.items():
        if lower & set(aliases):
            return league_id
    return None


# ---------------------------------------------------------------------------
# EPL team alias table — only EPL is hard-coded; UCL / WC fall back to
# ESPN-provided full names matched in _match_espn_game.
# ---------------------------------------------------------------------------

EPL_TEAM_ALIASES: dict[str, str] = {
    "arsenal": "ARS", "ars": "ARS",
    "aston villa": "AVL", "villa": "AVL", "avl": "AVL",
    "bournemouth": "BOU", "afc bournemouth": "BOU", "bou": "BOU",
    "brentford": "BRE", "bre": "BRE",
    "brighton": "BHA", "brighton & hove albion": "BHA", "brighton and hove albion": "BHA", "bha": "BHA",
    "chelsea": "CHE", "che": "CHE",
    "crystal palace": "CRY", "palace": "CRY", "cry": "CRY",
    "everton": "EVE", "eve": "EVE",
    "fulham": "FUL", "ful": "FUL",
    "ipswich": "IPS", "ipswich town": "IPS", "ips": "IPS",
    "leicester": "LEI", "leicester city": "LEI", "lei": "LEI",
    "liverpool": "LIV", "liv": "LIV",
    "manchester city": "MCI", "man city": "MCI", "mci": "MCI",
    "manchester united": "MUN", "man united": "MUN", "man utd": "MUN", "mun": "MUN",
    "newcastle": "NEW", "newcastle united": "NEW", "new": "NEW",
    "nottingham forest": "NFO", "nottm forest": "NFO", "forest": "NFO", "nfo": "NFO",
    "southampton": "SOU", "saints": "SOU", "sou": "SOU",
    "tottenham": "TOT", "spurs": "TOT", "tottenham hotspur": "TOT", "tot": "TOT",
    "west ham": "WHU", "west ham united": "WHU", "whu": "WHU",
    "wolves": "WOL", "wolverhampton": "WOL", "wolverhampton wanderers": "WOL", "wol": "WOL",
}


def resolve_epl_abbr(name: str) -> str | None:
    """Resolve an EPL team name to canonical 3-letter abbr. None for non-EPL teams."""
    return EPL_TEAM_ALIASES.get(name.lower().strip())


# ---------------------------------------------------------------------------
# Title parsing
# ---------------------------------------------------------------------------

_VS_PATTERN = re.compile(r"^(.+?)\s+(?:vs\.?|v)\s+(.+)$", re.IGNORECASE)
_SUFFIX_PATTERN = re.compile(
    r"[:\-–—]?\s*(?:O/U|Over/Under|Spread|ML|Moneyline|\+\d|\-\d|Draw)\b.*$",
    re.IGNORECASE,
)
_LEAGUE_PREFIX = re.compile(
    r"^(?:Premier League|EPL|English Premier League|"
    r"Champions League|UCL|UEFA Champions League|"
    r"World Cup|FIFA World Cup)\s*[:\-–—]\s*",
    re.IGNORECASE,
)


def parse_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from a soccer market title."""
    cleaned = _LEAGUE_PREFIX.sub("", title.strip())
    m = _VS_PATTERN.match(cleaned)
    if not m:
        return None
    a = _SUFFIX_PATTERN.sub("", m.group(1)).strip()
    b = _SUFFIX_PATTERN.sub("", m.group(2)).strip()
    if not a or not b:
        return None
    return a, b


# Slug formats (best-effort regex; widen during implementation if needed):
#   epl-ars-mci-2026-04-19
#   ucl-rma-bay-2026-04-09
#   wc-bra-arg-2026-06-15
_SLUG_PATTERN = re.compile(r"^(epl|ucl|wc)-([a-z0-9]{2,5})-([a-z0-9]{2,5})-\d{4}-\d{2}-\d{2}$")


def extract_codes_from_slug(event_slug: str) -> tuple[str, str] | None:
    """Slug-based team-abbr fallback. Only resolves EPL slugs; UCL / WC
    slugs return None and the plugin falls back to title-based matching."""
    if not event_slug:
        return None
    m = _SLUG_PATTERN.match(event_slug)
    if not m:
        return None
    league_prefix = m.group(1)
    if league_prefix != "epl":
        return None
    a = resolve_epl_abbr(m.group(2))
    b = resolve_epl_abbr(m.group(3))
    if not a or not b:
        return None
    return a, b
