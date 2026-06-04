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
from cachetools import LRUCache

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


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_REQUEST_TIMEOUT = 10


def _fetch_espn_scoreboard(league_id: str, date_str: str | None = None) -> dict | None:
    params = {}
    if date_str:
        params["dates"] = date_str
    try:
        resp = _requests.get(f"{ESPN_API}/{league_id}/scoreboard", params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_espn_summary(league_id: str, event_id: str) -> dict | None:
    try:
        resp = _requests.get(
            f"{ESPN_API}/{league_id}/summary",
            params={"event": event_id},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _match_espn_game_by_name(scoreboard: dict | None, name_a: str, name_b: str) -> tuple[str, dict] | None:
    """Find ESPN match ID by case-insensitive substring/abbreviation match.

    Used for UCL/WC where we don't have a hard-coded alias table; tries
    abbreviation, then displayName / shortDisplayName tokens.
    """
    if not scoreboard:
        return None
    norm_a = _normalize_name(name_a)
    norm_b = _normalize_name(name_b)
    for event in scoreboard.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        names = []
        for c in comps[0].get("competitors", []):
            team = c.get("team") or {}
            names.append({
                "abbr": _normalize_name(team.get("abbreviation", "")),
                "display": _normalize_name(team.get("displayName", "")),
                "short": _normalize_name(team.get("shortDisplayName", "")),
            })

        def matches(target):
            for entry in names:
                if target and (
                    target == entry["abbr"]
                    or target in entry["display"]
                    or target in entry["short"]
                    or entry["display"].endswith(target)
                ):
                    return entry
            return None

        m_a = matches(norm_a)
        m_b = matches(norm_b)
        if m_a and m_b and m_a is not m_b:
            return event.get("id"), event
    return None


def _match_espn_game_by_abbr(scoreboard: dict | None, abbr_a: str, abbr_b: str) -> str | None:
    if not scoreboard:
        return None
    pair = {abbr_a.upper(), abbr_b.upper()}
    for event in scoreboard.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        abbrs = {(c.get("team") or {}).get("abbreviation", "").upper() for c in comps[0].get("competitors", [])}
        if pair <= abbrs:
            return event.get("id")
    return None


def _extract_date_from_slug(event_slug: str) -> str | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", event_slug)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_status(status_data: dict) -> str:
    state = (status_data.get("type") or {}).get("state", "pre")
    return {"in": "live", "post": "final"}.get(state, "pre")


def _parse_minute(status_data: dict, status: str) -> str:
    type_block = status_data.get("type") or {}
    detail = type_block.get("shortDetail") or type_block.get("detail") or ""
    if status == "final":
        return "FT"
    if status == "pre":
        return ""
    # Live: ESPN returns minute in displayClock or detail like "67'", "HT"
    clock = status_data.get("displayClock") or ""
    if clock:
        return clock if clock.endswith("'") or clock in ("HT", "FT", "ET", "PEN") else f"{clock}'"
    return detail


def _parse_team(c: dict) -> dict:
    team = c.get("team") or {}
    abbr = (team.get("abbreviation") or "").upper()
    logos = team.get("logos") or []
    crest = logos[0].get("href") if logos else None
    records = c.get("records") or c.get("record") or []
    record = next((r.get("summary") for r in records if r.get("type") == "total"), None)
    return {
        "abbr": abbr,
        "name": team.get("shortDisplayName") or team.get("displayName", ""),
        "city": team.get("location", ""),
        "score": int(c.get("score", 0) or 0),
        "record": record,
        "crest_url": crest,
        "form": (c.get("form") or None),
    }


def _parse_goals(plays_data: list | None) -> list[SoccerGoal]:
    if not plays_data:
        return []
    out = []
    for p in plays_data:
        if not p.get("scoringPlay") and (p.get("type") or {}).get("text", "").lower() not in {"goal", "penalty - scored", "own goal"}:
            continue
        clock = (p.get("clock") or {}).get("displayValue", "") if isinstance(p.get("clock"), dict) else (p.get("clock") or "")
        team = ((p.get("team") or {}).get("abbreviation") or "").upper()
        scorer = ""
        assist = ""
        for participant in p.get("participants") or []:
            athlete = (participant.get("athlete") or {}).get("displayName", "")
            ptype = participant.get("type", "")
            if ptype in ("scorer", "goalScorer") and athlete:
                scorer = athlete
            elif ptype in ("assist", "assister") and athlete:
                assist = athlete
        out.append(SoccerGoal(
            minute=clock,
            team=team,
            scorer=scorer,
            assist=assist,
            type=(p.get("type") or {}).get("text", "regular").lower(),
        ))
    out.reverse()
    return out


def _parse_cards(plays_data: list | None) -> list[SoccerCard]:
    if not plays_data:
        return []
    out = []
    for p in plays_data:
        type_text = (p.get("type") or {}).get("text", "").lower()
        if "card" not in type_text:
            continue
        clock = (p.get("clock") or {}).get("displayValue", "") if isinstance(p.get("clock"), dict) else (p.get("clock") or "")
        color = "yellow" if "yellow" in type_text else ("red" if "red" in type_text else "yellow")
        if "second yellow" in type_text:
            color = "second yellow"
        team = ((p.get("team") or {}).get("abbreviation") or "").upper()
        athlete = ((p.get("participants") or [{}])[0].get("athlete") or {}).get("displayName", "")
        out.append(SoccerCard(minute=clock, team=team, player=athlete, color=color))
    out.reverse()
    return out


def _parse_subs(plays_data: list | None) -> list[SoccerSub]:
    if not plays_data:
        return []
    out = []
    for p in plays_data:
        if (p.get("type") or {}).get("text", "").lower() != "substitution":
            continue
        clock = (p.get("clock") or {}).get("displayValue", "") if isinstance(p.get("clock"), dict) else (p.get("clock") or "")
        team = ((p.get("team") or {}).get("abbreviation") or "").upper()
        on_p, off_p = "", ""
        for participant in p.get("participants") or []:
            athlete = (participant.get("athlete") or {}).get("displayName", "")
            ptype = participant.get("type", "").lower()
            if "in" in ptype and not on_p:
                on_p = athlete
            elif "out" in ptype and not off_p:
                off_p = athlete
        out.append(SoccerSub(minute=clock, team=team, on=on_p, off=off_p))
    out.reverse()
    return out


def _parse_match_stats(boxscore: dict | None) -> list[SoccerStats]:
    if not boxscore:
        return []
    out = []
    for team_block in boxscore.get("teams", []):
        abbr = ((team_block.get("team") or {}).get("abbreviation") or "").upper()
        stats = {s.get("name"): s.get("displayValue", "") for s in team_block.get("statistics", [])}

        def _i(key):
            try:
                return int(float(stats.get(key, 0)))
            except (TypeError, ValueError):
                return 0

        def _pct(key):
            v = stats.get(key, "")
            try:
                return float(str(v).replace("%", ""))
            except (TypeError, ValueError):
                return None

        out.append(SoccerStats(
            team=abbr,
            possession_pct=_pct("possessionPct"),
            shots=_i("totalShots"),
            shots_on_target=_i("shotsOnTarget"),
            corners=_i("wonCorners"),
            fouls=_i("foulsCommitted"),
            offsides=_i("offsides"),
        ))
    return out


def _parse_lineups(rosters: list | None) -> list[SoccerLineup]:
    if not rosters:
        return []
    out = []
    for team_block in rosters:
        abbr = ((team_block.get("team") or {}).get("abbreviation") or "").upper()
        formation = (team_block.get("formation") or {}).get("name", "") if isinstance(team_block.get("formation"), dict) else ""
        starters: list[SoccerLineupPlayer] = []
        bench: list[SoccerLineupPlayer] = []
        for player in team_block.get("roster") or []:
            athlete = player.get("athlete") or {}
            pos = (player.get("position") or {}).get("abbreviation", "") if isinstance(player.get("position"), dict) else ""
            try:
                num = int(player.get("jersey")) if player.get("jersey") else None
            except (TypeError, ValueError):
                num = None
            entry = SoccerLineupPlayer(
                name=athlete.get("displayName", ""),
                number=num,
                position=pos,
                is_starter=bool(player.get("starter")),
            )
            (starters if entry.is_starter else bench).append(entry)
        if starters or bench:
            out.append(SoccerLineup(team=abbr, formation=formation, starters=starters, bench=bench))
    return out


def _parse_odds(odds_data: list | None) -> SoccerOdds | None:
    if not odds_data:
        return None
    pick = next((p for p in odds_data if "365" in (p.get("provider", {}).get("name", ""))), odds_data[0])
    home = (pick.get("homeTeamOdds") or {}).get("odds", {}).get("summary", "")
    away = (pick.get("awayTeamOdds") or {}).get("odds", {}).get("summary", "")
    draw = (pick.get("drawOdds") or {}).get("odds", {}).get("summary", "") if pick.get("drawOdds") else ""
    if not (home or away or draw):
        return None
    return SoccerOdds(
        provider=pick.get("provider", {}).get("name", "Unknown"),
        home_odds=home or None,
        away_odds=away or None,
        draw_odds=draw or None,
    )


def _parse_venue(game_info: dict | None) -> SoccerVenue | None:
    if not game_info:
        return None
    v = game_info.get("venue") or {}
    name = v.get("fullName") or v.get("shortName")
    if not name:
        return None
    return SoccerVenue(name=name, city=(v.get("address") or {}).get("city", ""))


def _parse_head_to_head(series_data: list | None) -> SoccerHeadToHead | None:
    if not series_data:
        return None
    home_wins, away_wins, draws = 0, 0, 0
    for g in series_data:
        comps = g.get("competitions", [{}])
        if not comps:
            continue
        winner_found = False
        for c in comps[0].get("competitors", []):
            if c.get("winner") and c.get("homeAway") == "home":
                home_wins += 1; winner_found = True
            elif c.get("winner") and c.get("homeAway") == "away":
                away_wins += 1; winner_found = True
        if not winner_found:
            draws += 1
    return SoccerHeadToHead(home_wins=home_wins, draws=draws, away_wins=away_wins, total=len(series_data))


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_TTL = {"score": 15, "events": 15, "lineups": 30, "match_stats": 30, "odds": 60, "venue": 300, "head_to_head": 300, "scoreboard": 60, "summary": 60}
_match_cache: LRUCache = LRUCache(maxsize=500)


def _cache_get(key: str, field: str):
    entry = _match_cache.get(key, {}).get(field)
    if entry and entry[0] > _time.time():
        return entry[1]
    return None


def _cache_set(key: str, field: str, data):
    if key not in _match_cache:
        _match_cache[key] = {}
    ttl = _CACHE_TTL.get(field, 30)
    _match_cache[key][field] = (_time.time() + ttl, data)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def get_soccer_data(title: str, *, tags: list[str], event_slug: str = "") -> SoccerGameData | None:
    league_id = resolve_league(tags)
    if not league_id:
        return None

    parsed = parse_team_names(title)
    if not parsed:
        return None
    name_a, name_b = parsed

    # Resolve EPL via abbr; UCL/WC fall back to name match against scoreboard
    abbr_a = resolve_epl_abbr(name_a) if league_id == "eng.1" else None
    abbr_b = resolve_epl_abbr(name_b) if league_id == "eng.1" else None
    if league_id == "eng.1" and (not abbr_a or not abbr_b) and event_slug:
        from_slug = extract_codes_from_slug(event_slug)
        if from_slug:
            abbr_a, abbr_b = from_slug
    if league_id == "eng.1" and (not abbr_a or not abbr_b):
        # EPL needs at least one resolution path; can't continue
        return None

    dates_to_try = [None]
    date_str = _extract_date_from_slug(event_slug) if event_slug else None
    if date_str:
        dates_to_try.append(date_str)

    espn_event_id = None
    for d in dates_to_try:
        cache_key = f"__sc_sb_{league_id}_{d or 'today'}__"
        sb = _cache_get(cache_key, "scoreboard")
        if sb is None:
            sb = _fetch_espn_scoreboard(league_id, d)
            if sb:
                _cache_set(cache_key, "scoreboard", sb)
        if not sb:
            continue
        if league_id == "eng.1":
            espn_event_id = _match_espn_game_by_abbr(sb, abbr_a, abbr_b)
        else:
            matched = _match_espn_game_by_name(sb, name_a, name_b)
            espn_event_id = matched[0] if matched else None
        if espn_event_id:
            break

    if not espn_event_id:
        return None

    match_key = f"sc_{league_id}_{espn_event_id}"
    summary = _cache_get(match_key, "summary")
    if summary is None:
        summary = _fetch_espn_summary(league_id, espn_event_id)
        if summary:
            _cache_set(match_key, "summary", summary)
    if not summary:
        return None

    header = summary.get("header", {})
    comps = header.get("competitions") or [{}]
    comp = comps[0] if comps else {}
    status_data = comp.get("status", {})
    status = _parse_status(status_data)
    minute = _parse_minute(status_data, status)

    home_info, away_info = None, None
    for c in comp.get("competitors", []):
        info = _parse_team(c)
        if c.get("homeAway") == "home":
            home_info = info
        else:
            away_info = info
    if not home_info or not away_info:
        return None

    commentary = summary.get("commentary")
    if isinstance(commentary, dict):
        commentary_items = commentary.get("items")
    elif isinstance(commentary, list):
        commentary_items = commentary
    else:
        commentary_items = None
    plays = summary.get("plays") or summary.get("keyEvents") or commentary_items or []
    goals = _parse_goals(plays)
    cards = _parse_cards(plays)
    subs = _parse_subs(plays)
    match_stats = _parse_match_stats(summary.get("boxscore"))
    lineups = _parse_lineups(summary.get("rosters"))
    odds = _parse_odds(summary.get("odds"))
    venue = _parse_venue(summary.get("gameInfo"))
    head_to_head = _parse_head_to_head(summary.get("seasonseries") or summary.get("headToHeadGames"))
    attendance = (summary.get("gameInfo") or {}).get("attendance")
    referee_data = summary.get("referees") or summary.get("officials") or []
    referee = referee_data[0].get("displayName") if referee_data else None

    competition_round = ""
    notes = summary.get("notes") or []
    for n in notes:
        if isinstance(n, dict) and n.get("type") in ("event", "tournament", "round"):
            competition_round = n.get("headline") or n.get("text", "")
            break

    return SoccerGameData(
        game_id=match_key,
        espn_game_id=espn_event_id,
        competition=LEAGUE_DISPLAY[league_id],
        competition_round=competition_round,
        league_id=league_id,
        status=status,
        game_time=comp.get("date"),
        minute=minute,
        home=SoccerTeam(**home_info),
        away=SoccerTeam(**away_info),
        venue=venue,
        referee=referee,
        attendance=int(attendance) if attendance else None,
        odds=odds,
        goals=goals[:50],
        cards=cards[:50],
        subs=subs[:50],
        match_stats=match_stats,
        lineups=lineups,
        head_to_head=head_to_head,
    )


# ---------------------------------------------------------------------------
# Plugin wrapper
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from sports import register
from sports.base import OverlayResponse, SportOverlay


class SoccerOverlay(SportOverlay):
    sport_id = "soccer"
    tag_aliases = (
        "epl", "english premier league", "premier league",
        "ucl", "uefa champions league", "champions league",
        "world cup", "fifa world cup",
    )

    def can_handle(self, title: str, tags: list[str], event_slug: str = "") -> bool:
        if parse_team_names(title) is not None:
            return True
        return extract_codes_from_slug(event_slug) is not None

    def fetch(self, condition_id: str, title: str, tags: list[str], event_slug: str = "") -> OverlayResponse | None:
        data = get_soccer_data(title, tags=tags, event_slug=event_slug)
        if data is None:
            return None
        payload = data.model_dump()
        return OverlayResponse(
            sport=self.sport_id,
            status=payload.get("status", "pre"),
            last_updated=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


register(SoccerOverlay())
