"""MLB game data enrichment for market pages.

Fetches scores, linescore, scoring plays, box, odds, probable pitchers,
and head-to-head from the ESPN Baseball API.
"""

from __future__ import annotations

import re
import time as _time

import requests as _requests
from cachetools import LRUCache

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


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"
_REQUEST_TIMEOUT = 10


def _fetch_espn_scoreboard(date_str: str | None = None) -> dict | None:
    """Fetch MLB scoreboard from ESPN. Optionally for a specific date (YYYYMMDD)."""
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
    """Fetch game summary from ESPN."""
    try:
        resp = _requests.get(
            f"{ESPN_API}/summary",
            params={"event": event_id},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except _requests.RequestException:
        return None


# ESPN abbreviation normalization for MLB teams (kept narrow — ESPN's
# baseball API mostly uses the same abbrs we do, but a few divergences:)
_ESPN_ABBR_MAP: dict[str, str] = {
    "ATH": "ATH",  # Athletics — ESPN now uses "ATH"
    "WSH": "WSH",
    "CWS": "CWS",
    "TB": "TB",
    "KC": "KC",
    "SD": "SD",
    "SF": "SF",
}


def _normalize_espn_abbr(abbr: str) -> str:
    return _ESPN_ABBR_MAP.get(abbr.upper(), abbr.upper())


def _match_espn_game(scoreboard: dict | None, abbr_a: str, abbr_b: str) -> str | None:
    """Find ESPN game ID matching two team abbrs in scoreboard."""
    if not scoreboard:
        return None
    pair = {abbr_a.upper(), abbr_b.upper()}
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
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", event_slug)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


# ---------------------------------------------------------------------------
# ESPN parsers
# ---------------------------------------------------------------------------

def _parse_status(status_data: dict) -> str:
    state = (status_data.get("type") or {}).get("state", "pre")
    if state == "in":
        return "live"
    if state == "post":
        return "final"
    return "pre"


def _parse_teams(comp: dict) -> tuple[dict | None, dict | None]:
    home, away = None, None
    for c in comp.get("competitors", []):
        team = c.get("team") or {}
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        records = c.get("records") or c.get("record") or []
        record = None
        for r in records:
            if r.get("type") == "total":
                record = r.get("summary")
        # ESPN MLB also exposes hits/errors via "hits" / "errors" fields under linescores;
        # we'll surface them by inning later. The competitor-level "score" carries runs.
        entry = {
            "abbr": abbr,
            "name": team.get("shortDisplayName", team.get("displayName", "")),
            "city": team.get("location", ""),
            "runs": int(c.get("score", "0") or 0),
            "hits": int(c.get("hits", 0) or 0),
            "errors": int(c.get("errors", 0) or 0),
            "record": record,
        }
        if c.get("homeAway") == "home":
            home = entry
        else:
            away = entry
    return home, away


def _parse_inning_and_half(status_data: dict) -> tuple[int, str]:
    period = status_data.get("period", 0) or 0
    detail = (status_data.get("type") or {}).get("detail", "").lower()
    half = ""
    if "top" in detail:
        half = "top"
    elif "bot" in detail or "bottom" in detail:
        half = "bot"
    elif "mid" in detail:
        half = "mid"
    elif "end" in detail:
        half = "end"
    return int(period), half


def _parse_count_and_runners(situation: dict | None) -> tuple[MLBCount | None, MLBRunners | None]:
    if not situation:
        return None, None
    count = MLBCount(
        balls=int(situation.get("balls", 0) or 0),
        strikes=int(situation.get("strikes", 0) or 0),
        outs=int(situation.get("outs", 0) or 0),
    )
    runners = MLBRunners(
        on_first=bool(situation.get("onFirst")),
        on_second=bool(situation.get("onSecond")),
        on_third=bool(situation.get("onThird")),
    )
    return count, runners


def _parse_linescore(comps: list[dict]) -> list[MLBLinescoreInning]:
    """Parse per-inning runs from competition.competitors[].linescores."""
    home_innings, away_innings = [], []
    for c in comps:
        ls = c.get("linescores") or []
        runs = [int(x.get("value", 0) or 0) for x in ls]
        if c.get("homeAway") == "home":
            home_innings = runs
        else:
            away_innings = runs
    n = max(len(home_innings), len(away_innings))
    out = []
    for i in range(n):
        out.append(MLBLinescoreInning(
            inning=i + 1,
            home_runs=home_innings[i] if i < len(home_innings) else 0,
            away_runs=away_innings[i] if i < len(away_innings) else 0,
        ))
    return out


def _parse_scoring_plays(plays_data: list | None) -> list[MLBScoringPlay]:
    if not plays_data:
        return []
    out = []
    for p in plays_data:
        period = (p.get("period") or {}).get("number", 0)
        team_block = p.get("team") or {}
        out.append(MLBScoringPlay(
            inning=int(period),
            half="top" if (p.get("period") or {}).get("type") == "Top" else "bot",
            text=p.get("text", ""),
            away_score=int(p.get("awayScore", 0) or 0),
            home_score=int(p.get("homeScore", 0) or 0),
            team=_normalize_espn_abbr(team_block.get("abbreviation", "")),
        ))
    out.reverse()  # newest first
    return out


def _parse_box(boxscore: dict | None) -> tuple[MLBTeamBox | None, MLBTeamBox | None]:
    """Parse home/away box from ESPN boxscore.players."""
    if not boxscore:
        return None, None
    teams_block = boxscore.get("players", [])
    home_box, away_box = None, None
    home_team_id = None
    # The teams[] array has the home/away marker
    for t in boxscore.get("teams", []):
        if t.get("homeAway") == "home":
            home_team_id = (t.get("team") or {}).get("id")

    for team_block in teams_block:
        team = team_block.get("team") or {}
        abbr = _normalize_espn_abbr(team.get("abbreviation", ""))
        batters: list[MLBBoxBatter] = []
        pitchers: list[MLBBoxPitcher] = []
        for stats_group in team_block.get("statistics", []):
            group_name = (stats_group.get("name") or "").lower()
            keys = stats_group.get("keys", [])
            athletes = stats_group.get("athletes", [])
            if "batt" in group_name:
                for a in athletes:
                    name = (a.get("athlete") or {}).get("displayName", "")
                    stats = dict(zip(keys, a.get("stats", [])))
                    batters.append(MLBBoxBatter(
                        name=name,
                        position=(a.get("position") or {}).get("abbreviation", ""),
                        at_bats=_to_int(stats.get("atBats")),
                        runs=_to_int(stats.get("runs")),
                        hits=_to_int(stats.get("hits")),
                        rbi=_to_int(stats.get("RBIs")),
                        walks=_to_int(stats.get("walks")),
                        strikeouts=_to_int(stats.get("strikeouts")),
                        avg=str(stats.get("avg") or ""),
                    ))
            elif "pitch" in group_name:
                for a in athletes:
                    name = (a.get("athlete") or {}).get("displayName", "")
                    stats = dict(zip(keys, a.get("stats", [])))
                    pitchers.append(MLBBoxPitcher(
                        name=name,
                        innings_pitched=str(stats.get("inningsPitched") or "0.0"),
                        hits=_to_int(stats.get("hits")),
                        runs=_to_int(stats.get("runs")),
                        earned_runs=_to_int(stats.get("earnedRuns")),
                        walks=_to_int(stats.get("walks")),
                        strikeouts=_to_int(stats.get("strikeouts")),
                        era=str(stats.get("ERA") or ""),
                    ))
        box = MLBTeamBox(team=abbr, batters=batters, pitchers=pitchers)
        if home_team_id and team.get("id") == home_team_id:
            home_box = box
        else:
            away_box = box
    return home_box, away_box


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _parse_odds(pickcenter: list | None) -> MLBOdds | None:
    if not pickcenter:
        return None
    pick = next((p for p in pickcenter if p.get("provider", {}).get("name") == "DraftKings"), pickcenter[0])
    home_ml = pick.get("homeTeamOdds", {}).get("moneyLine")
    away_ml = pick.get("awayTeamOdds", {}).get("moneyLine")
    return MLBOdds(
        provider=pick.get("provider", {}).get("name", "Unknown"),
        home_ml=f"+{int(home_ml)}" if isinstance(home_ml, (int, float)) and home_ml > 0 else (str(int(home_ml)) if home_ml is not None else None),
        away_ml=f"+{int(away_ml)}" if isinstance(away_ml, (int, float)) and away_ml > 0 else (str(int(away_ml)) if away_ml is not None else None),
        run_line=str(pick.get("spread")) if pick.get("spread") is not None else None,
        total=float(pick["overUnder"]) if pick.get("overUnder") is not None else None,
    )


def _parse_venue(game_info: dict | None) -> MLBVenue | None:
    if not game_info:
        return None
    v = game_info.get("venue") or {}
    name = v.get("fullName") or v.get("shortName")
    if not name:
        return None
    return MLBVenue(name=name, city=(v.get("address") or {}).get("city", ""))


def _parse_weather(game_info: dict | None) -> MLBWeather | None:
    if not game_info:
        return None
    w = game_info.get("weather") or {}
    if not w:
        return None
    return MLBWeather(
        temperature=int(w["temperature"]) if w.get("temperature") is not None else None,
        condition=w.get("displayValue", "") or w.get("conditionId", ""),
        wind=w.get("wind", "") or "",
    )


def _parse_probable_pitchers(probable_data: list | None) -> tuple[MLBProbablePitcher | None, MLBProbablePitcher | None]:
    if not probable_data:
        return None, None
    home, away = None, None
    for entry in probable_data:
        athlete = entry.get("athlete") or {}
        stats = entry.get("statistics") or []
        era = ""
        record = ""
        for s in stats:
            if s.get("name") == "ERA":
                era = s.get("displayValue", "")
            elif s.get("name") in ("wins-losses", "WL"):
                record = s.get("displayValue", "")
        p = MLBProbablePitcher(name=athlete.get("displayName", ""), era=era, record=record)
        if entry.get("homeAway") == "home":
            home = p
        else:
            away = p
    return home, away


def _parse_head_to_head(series_data: list | None) -> MLBHeadToHead | None:
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
    return MLBHeadToHead(home_wins=home_wins, away_wins=away_wins, total=len(series_data))


# ---------------------------------------------------------------------------
# Cache (per-field TTL, keyed by game_id)
# ---------------------------------------------------------------------------

_CACHE_TTL = {
    "score": 15, "plays": 15, "linescore": 30, "box": 30, "odds": 60,
    "venue": 300, "head_to_head": 300, "scoreboard": 60, "summary": 60,
}
_game_cache: LRUCache = LRUCache(maxsize=200)


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

def get_mlb_data(title: str, *, event_slug: str = "") -> MLBGameData | None:
    """Resolve a market title to live MLB game data.

    Tries today's scoreboard first, then the slug date (for upcoming games).
    """
    abbr_a: str | None = None
    abbr_b: str | None = None
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
        cache_key = f"__mlb_sb_{d or 'today'}__"
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

    game_key = f"mlb_{espn_event_id}"
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
    inning, half = _parse_inning_and_half(status_data)
    home_info, away_info = _parse_teams(comp)
    if not home_info or not away_info:
        return None

    situation = summary.get("situation") or {}
    count, runners = _parse_count_and_runners(situation)

    linescore = _parse_linescore(comp.get("competitors", []))
    scoring_plays = _parse_scoring_plays(summary.get("scoringPlays"))
    home_box, away_box = _parse_box(summary.get("boxscore"))
    odds = _parse_odds(summary.get("pickcenter"))
    venue = _parse_venue(summary.get("gameInfo"))
    weather = _parse_weather(summary.get("gameInfo"))
    probable_home, probable_away = _parse_probable_pitchers(summary.get("probables"))
    head_to_head = _parse_head_to_head(summary.get("seasonseries") or summary.get("headToHeadGames"))

    attendance = (summary.get("gameInfo") or {}).get("attendance")
    broadcasts = comp.get("broadcasts") or []
    broadcast = None
    if broadcasts:
        names = broadcasts[0].get("names") or []
        broadcast = names[0] if names else None

    return MLBGameData(
        game_id=game_key,
        espn_game_id=espn_event_id,
        status=status,
        game_time=comp.get("date"),
        inning=inning,
        half=half,
        count=count,
        runners=runners,
        home=MLBTeam(**home_info),
        away=MLBTeam(**away_info),
        venue=venue,
        weather=weather,
        attendance=int(attendance) if attendance else None,
        broadcast=broadcast,
        probable_home=probable_home,
        probable_away=probable_away,
        odds=odds,
        linescore=linescore,
        scoring_plays=scoring_plays[:50],
        home_box=home_box,
        away_box=away_box,
        current_pitcher=(situation.get("pitcher") or {}).get("athlete", {}).get("displayName", "") if isinstance(situation.get("pitcher"), dict) else "",
        current_batter=(situation.get("batter") or {}).get("athlete", {}).get("displayName", "") if isinstance(situation.get("batter"), dict) else "",
        head_to_head=head_to_head,
    )


# ---------------------------------------------------------------------------
# Plugin wrapper
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from sports import register
from sports.base import OverlayResponse, SportOverlay


class MLBOverlay(SportOverlay):
    sport_id = "mlb"
    tag_aliases = ("mlb", "baseball", "world series")

    def can_handle(self, title: str, tags: list[str], event_slug: str = "") -> bool:
        if parse_team_names(title) is not None:
            return True
        return extract_codes_from_slug(event_slug) is not None

    def fetch(
        self,
        condition_id: str,
        title: str,
        tags: list[str],
        event_slug: str = "",
    ) -> OverlayResponse | None:
        data = get_mlb_data(title, event_slug=event_slug)
        if data is None:
            return None
        payload = data.model_dump()
        return OverlayResponse(
            sport=self.sport_id,
            status=payload.get("status", "pre"),
            last_updated=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )


register(MLBOverlay())
