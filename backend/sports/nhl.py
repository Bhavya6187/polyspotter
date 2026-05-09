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


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
_REQUEST_TIMEOUT = 10


def _fetch_espn_scoreboard(date_str: str | None = None) -> dict | None:
    params = {}
    if date_str:
        params["dates"] = date_str
    try:
        resp = _requests.get(f"{ESPN_API}/scoreboard", params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


def _fetch_espn_summary(event_id: str) -> dict | None:
    try:
        resp = _requests.get(f"{ESPN_API}/summary", params={"event": event_id}, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


_ESPN_ABBR_MAP: dict[str, str] = {
    "TBL": "TB", "TBR": "TB",
    "NJD": "NJ",
    "LAK": "LA",
    "SJS": "SJ",
    "WSH": "WSH",
    "VGK": "VGK",
}


def _normalize_espn_abbr(abbr: str) -> str:
    return _ESPN_ABBR_MAP.get(abbr.upper(), abbr.upper())


def _match_espn_game(scoreboard: dict | None, abbr_a: str, abbr_b: str) -> str | None:
    if not scoreboard:
        return None
    pair = {abbr_a.upper(), abbr_b.upper()}
    for event in scoreboard.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        abbrs = {_normalize_espn_abbr(c.get("team", {}).get("abbreviation", "")) for c in comps[0].get("competitors", [])}
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


def _parse_period_clock(status_data: dict) -> tuple[str, str]:
    period_num = status_data.get("period", 0) or 0
    detail = (status_data.get("type") or {}).get("detail", "")
    period_label = ""
    if period_num == 0:
        period_label = ""
    elif period_num <= 3:
        period_label = f"P{period_num}"
    elif period_num == 4:
        period_label = "OT"
    elif "shoot" in detail.lower():
        period_label = "SO"
    else:
        period_label = f"OT{period_num - 3}"
    clock = status_data.get("displayClock", "") or ""
    return period_label, clock


def _parse_teams(comp: dict) -> tuple[dict | None, dict | None]:
    home, away = None, None
    for c in comp.get("competitors", []):
        team = c.get("team") or {}
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        records = c.get("records") or c.get("record") or []
        record = next((r.get("summary") for r in records if r.get("type") == "total"), None)
        entry = {
            "abbr": abbr,
            "name": team.get("shortDisplayName", team.get("displayName", "")),
            "city": team.get("location", ""),
            "score": int(c.get("score", 0) or 0),
            "record": record,
        }
        if c.get("homeAway") == "home":
            home = entry
        else:
            away = entry
    return home, away


def _parse_scoring_summary(plays_data: list | None) -> list[NHLScoringEvent]:
    if not plays_data:
        return []
    out = []
    for p in plays_data:
        period = (p.get("period") or {}).get("number", 0)
        team = _normalize_espn_abbr((p.get("team") or {}).get("abbreviation", ""))
        scorer = ""
        assists: list[str] = []
        for participant in p.get("participants", []):
            athlete = (participant.get("athlete") or {}).get("displayName", "")
            ptype = participant.get("type", "")
            if ptype == "scorer" and athlete:
                scorer = athlete
            elif ptype == "assist" and athlete:
                assists.append(athlete)
        strength = (p.get("strength") or {}).get("text", "EV")
        out.append(NHLScoringEvent(
            period=int(period),
            time=p.get("clock", {}).get("displayValue", "") if isinstance(p.get("clock"), dict) else (p.get("clock") or ""),
            team=team,
            scorer=scorer,
            assists=assists,
            type=strength,
            is_gwg=bool(p.get("isGameWinningGoal", False)),
        ))
    out.reverse()  # newest first
    return out


def _parse_penalties(penalties_data: list | None) -> list[NHLPenalty]:
    if not penalties_data:
        return []
    out = []
    for p in penalties_data:
        period = (p.get("period") or {}).get("number", 0)
        team = _normalize_espn_abbr((p.get("team") or {}).get("abbreviation", ""))
        athlete = (p.get("participants") or [{}])[0].get("athlete") or {}
        out.append(NHLPenalty(
            period=int(period),
            time=p.get("clock", {}).get("displayValue", "") if isinstance(p.get("clock"), dict) else (p.get("clock") or ""),
            team=team,
            player=athlete.get("displayName", ""),
            infraction=p.get("text", "") or p.get("type", {}).get("text", ""),
            minutes=int(p.get("minutes", 2) or 2),
        ))
    out.reverse()
    return out


def _parse_odds(pickcenter: list | None) -> NHLOdds | None:
    if not pickcenter:
        return None
    pick = next((p for p in pickcenter if p.get("provider", {}).get("name") == "DraftKings"), pickcenter[0])
    home_ml = pick.get("homeTeamOdds", {}).get("moneyLine")
    away_ml = pick.get("awayTeamOdds", {}).get("moneyLine")

    def fmt_ml(v):
        if v is None:
            return None
        return f"+{int(v)}" if v > 0 else str(int(v))

    return NHLOdds(
        provider=pick.get("provider", {}).get("name", "Unknown"),
        home_ml=fmt_ml(home_ml),
        away_ml=fmt_ml(away_ml),
        puck_line=str(pick.get("spread")) if pick.get("spread") is not None else None,
        total=float(pick["overUnder"]) if pick.get("overUnder") is not None else None,
    )


def _parse_venue(game_info: dict | None) -> NHLVenue | None:
    if not game_info:
        return None
    v = game_info.get("venue") or {}
    name = v.get("fullName") or v.get("shortName")
    if not name:
        return None
    return NHLVenue(name=name, city=(v.get("address") or {}).get("city", ""))


def _parse_head_to_head(series_data: list | None) -> NHLHeadToHead | None:
    if not series_data:
        return None
    home_wins, away_wins = 0, 0
    for g in series_data:
        comps = g.get("competitions", [{}])
        if not comps:
            continue
        for c in comps[0].get("competitors", []):
            if c.get("winner") and c.get("homeAway") == "home":
                home_wins += 1
            elif c.get("winner") and c.get("homeAway") == "away":
                away_wins += 1
    return NHLHeadToHead(home_wins=home_wins, away_wins=away_wins, total=len(series_data))


def _parse_team_stats_live(boxscore: dict | None) -> list[NHLTeamStatsLive]:
    if not boxscore:
        return []
    out = []
    for team_block in boxscore.get("teams", []):
        abbr = _normalize_espn_abbr((team_block.get("team") or {}).get("abbreviation", ""))
        stats = {s.get("name"): s.get("displayValue", "") for s in team_block.get("statistics", [])}
        out.append(NHLTeamStatsLive(
            team=abbr,
            shots=int(stats.get("shotsTotal", 0) or 0) if str(stats.get("shotsTotal", "")).isdigit() else 0,
            faceoff_pct=_safe_float(stats.get("faceoffsWonPct")),
            hits=int(stats.get("hits", 0) or 0) if str(stats.get("hits", "")).isdigit() else 0,
            pp_summary=str(stats.get("powerPlayConversion") or stats.get("powerPlay") or ""),
            pk_summary=str(stats.get("penaltyKill") or ""),
        ))
    return out


def _safe_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_goalies(boxscore: dict | None) -> list[NHLGoalieLine]:
    if not boxscore:
        return []
    out = []
    for team_block in boxscore.get("players", []):
        abbr = _normalize_espn_abbr((team_block.get("team") or {}).get("abbreviation", ""))
        for stats_group in team_block.get("statistics", []):
            if (stats_group.get("name") or "").lower() != "goalies":
                continue
            keys = stats_group.get("keys", [])
            for a in stats_group.get("athletes", []):
                stats = dict(zip(keys, a.get("stats", [])))
                saves = stats.get("saves", "0")
                shots = stats.get("shotsAgainst", "0")
                try:
                    saves_i = int(saves)
                    shots_i = int(shots)
                except (ValueError, TypeError):
                    saves_i, shots_i = 0, 0
                out.append(NHLGoalieLine(
                    name=(a.get("athlete") or {}).get("displayName", ""),
                    team=abbr,
                    saves=saves_i,
                    shots_against=shots_i,
                ))
    return out


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_TTL = {"score": 15, "events": 15, "box": 30, "odds": 60, "venue": 300, "head_to_head": 300, "scoreboard": 60, "summary": 60}
_game_cache: dict[str, dict[str, tuple[float, object]]] = {}


def _cache_get(key: str, field: str):
    entry = _game_cache.get(key, {}).get(field)
    if entry and entry[0] > _time.time():
        return entry[1]
    return None


def _cache_set(key: str, field: str, data):
    if key not in _game_cache:
        _game_cache[key] = {}
    ttl = _CACHE_TTL.get(field, 30)
    _game_cache[key][field] = (_time.time() + ttl, data)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def get_nhl_data(title: str, *, event_slug: str = "") -> NHLGameData | None:
    abbr_a, abbr_b = None, None
    parsed = parse_team_names(title)
    if parsed:
        abbr_a = resolve_abbr(parsed[0])
        abbr_b = resolve_abbr(parsed[1])
    if (not abbr_a or not abbr_b) and event_slug:
        from_slug = extract_codes_from_slug(event_slug)
        if from_slug:
            abbr_a, abbr_b = from_slug
    if not abbr_a or not abbr_b:
        return None

    dates_to_try = [None]
    date_str = _extract_date_from_slug(event_slug) if event_slug else None
    if date_str:
        dates_to_try.append(date_str)

    espn_event_id = None
    for d in dates_to_try:
        cache_key = f"__nhl_sb_{d or 'today'}__"
        sb = _cache_get(cache_key, "scoreboard")
        if sb is None:
            sb = _fetch_espn_scoreboard(d)
            if sb:
                _cache_set(cache_key, "scoreboard", sb)
        if sb:
            espn_event_id = _match_espn_game(sb, abbr_a, abbr_b)
            if espn_event_id:
                break

    if not espn_event_id:
        return None

    game_key = f"nhl_{espn_event_id}"
    summary = _cache_get(game_key, "summary")
    if summary is None:
        summary = _fetch_espn_summary(espn_event_id)
        if summary:
            _cache_set(game_key, "summary", summary)
    if not summary:
        return None

    header = summary.get("header", {})
    comps = header.get("competitions") or [{}]
    comp = comps[0] if comps else {}
    status_data = comp.get("status", {})
    status = _parse_status(status_data)
    period_label, clock = _parse_period_clock(status_data)
    home_info, away_info = _parse_teams(comp)
    if not home_info or not away_info:
        return None

    odds = _parse_odds(summary.get("pickcenter"))
    venue = _parse_venue(summary.get("gameInfo"))
    scoring_summary = _parse_scoring_summary(summary.get("scoringPlays"))
    penalties = _parse_penalties(summary.get("penalties"))
    team_stats_live = _parse_team_stats_live(summary.get("boxscore"))
    goalies = _parse_goalies(summary.get("boxscore"))
    head_to_head = _parse_head_to_head(summary.get("seasonseries") or summary.get("headToHeadGames"))
    attendance = (summary.get("gameInfo") or {}).get("attendance")
    broadcasts = comp.get("broadcasts") or []
    broadcast = (broadcasts[0].get("names") or [None])[0] if broadcasts else None

    return NHLGameData(
        game_id=game_key,
        espn_game_id=espn_event_id,
        status=status,
        game_time=comp.get("date"),
        period=period_label,
        clock=clock,
        power_play=None,  # ESPN exposes power play state inconsistently; left None for v1
        home=NHLTeam(**home_info),
        away=NHLTeam(**away_info),
        venue=venue,
        broadcast=broadcast,
        attendance=int(attendance) if attendance else None,
        odds=odds,
        scoring_summary=scoring_summary[:50],
        penalties=penalties[:50],
        team_stats_live=team_stats_live,
        goalies=goalies,
        head_to_head=head_to_head,
    )


# ---------------------------------------------------------------------------
# Plugin wrapper
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from sports import register
from sports.base import OverlayResponse, SportOverlay


class NHLOverlay(SportOverlay):
    sport_id = "nhl"
    tag_aliases = ("nhl", "hockey", "stanley cup")

    def can_handle(self, title: str, tags: list[str], event_slug: str = "") -> bool:
        if parse_team_names(title) is not None:
            return True
        return extract_codes_from_slug(event_slug) is not None

    def fetch(self, condition_id: str, title: str, tags: list[str], event_slug: str = "") -> OverlayResponse | None:
        data = get_nhl_data(title, event_slug=event_slug)
        if data is None:
            return None
        payload = data.model_dump()
        return OverlayResponse(
            sport=self.sport_id,
            status=payload.get("status", "pre"),
            last_updated=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


register(NHLOverlay())
