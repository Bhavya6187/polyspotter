# Cricket Live Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add live IPL cricket match data (scores, ball-by-ball commentary, scorecard, odds) to Polymarket cricket market pages, mirroring the basketball enrichment pattern.

**Architecture:** New `backend/cricket.py` fetches from ESPN Cricket API (league 8048), parses into cricket Pydantic models, exposes via `/api/market/{id}/cricket`. Frontend detects cricket markets via tags, renders cricket components (score banner, ball-by-ball feed, scorecard, match info) above existing market content. Polling hook updates data every 15s when live.

**Tech Stack:** Python/FastAPI + requests (backend), ESPN Cricket API, React/Next.js + Tailwind CSS (frontend)

**Spec:** `docs/superpowers/specs/2026-04-08-cricket-live-page-design.md`

---

### Task 1: Cricket Pydantic Models

**Files:**
- Modify: `backend/models.py` (append after line 462)

- [ ] **Step 1: Add cricket data models to models.py**

Append these models after the existing basketball models (after line 462):

```python
# -- Cricket game data (proxied from ESPN Cricket API) -------------------------

class CricketTeam(BaseModel):
    name: str
    short_name: str = ""          # e.g. "GT", "DC"
    score: str = ""               # e.g. "156/9"
    overs: str = ""               # e.g. "20.0"
    logo_url: str | None = None

class BatsmanEntry(BaseModel):
    name: str
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    strike_rate: float = 0.0
    how_out: str = ""             # e.g. "c Kohli b Bumrah" or "not out"

class BowlerEntry(BaseModel):
    name: str
    overs: str = "0"
    maidens: int = 0
    runs: int = 0
    wickets: int = 0
    economy: float = 0.0

class FoWEntry(BaseModel):
    wicket_num: int
    score: int
    over: str = ""
    batsman: str = ""

class CricketInnings(BaseModel):
    team: str
    score: int = 0
    overs: str = ""
    wickets: int = 0
    batting: list[BatsmanEntry] = []
    bowling: list[BowlerEntry] = []
    fall_of_wickets: list[FoWEntry] = []

class BallEvent(BaseModel):
    over: int = 0
    ball_in_over: int = 0
    batsman: str = ""
    bowler: str = ""
    runs: int = 0
    extras: int = 0
    is_boundary: bool = False
    is_wicket: bool = False
    commentary_short: str = ""
    commentary_detail: str = ""
    score_after: str = ""

class CricketOdds(BaseModel):
    provider: str = "Bet 365"
    home_odds: str = ""           # fractional e.g. "24/25" or decimal
    away_odds: str = ""

class CricketPartnership(BaseModel):
    runs: int = 0
    balls: int = 0
    batsman1: str = ""
    batsman2: str = ""

class CricketSquadPlayer(BaseModel):
    name: str
    role: str = ""                # "batsman", "bowler", "allrounder", "wicketkeeper batter"

class CricketHeadToHead(BaseModel):
    home_wins: int = 0
    away_wins: int = 0
    total: int = 0

class CricketVenue(BaseModel):
    name: str = ""
    city: str = ""

class CricketToss(BaseModel):
    winner: str = ""
    decision: str = ""            # "bat" or "field"

class CricketGameData(BaseModel):
    match_id: str = ""
    espn_match_id: str | None = None
    status: str = "pre"           # "pre", "live", "complete"
    match_time: str | None = None # ISO datetime
    status_text: str = ""         # e.g. "Gujarat Titans won by 5 wickets"
    home: CricketTeam
    away: CricketTeam
    toss: CricketToss | None = None
    venue: CricketVenue | None = None
    odds: CricketOdds | None = None
    innings: list[CricketInnings] = []
    partnership: CricketPartnership | None = None
    run_rate: float | None = None
    required_rate: float | None = None
    balls: list[BallEvent] = []
    squads: dict[str, list[CricketSquadPlayer]] = {}  # {"home": [...], "away": [...]}
    head_to_head: CricketHeadToHead | None = None
```

- [ ] **Step 2: Verify models import cleanly**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "from models import CricketGameData, CricketTeam, BallEvent; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat: add cricket Pydantic models for ESPN API data"
```

---

### Task 2: Cricket Backend — Team Resolution & ESPN Fetching

**Files:**
- Create: `backend/cricket.py`

- [ ] **Step 1: Create cricket.py with team aliases, ESPN fetching, and scoreboard matching**

```python
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
```

- [ ] **Step 2: Verify file imports**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "from cricket import parse_team_names, resolve_short_name, TEAM_ALIASES; print(parse_team_names('Delhi Capitals vs Gujarat Titans')); print(resolve_short_name('Gujarat Titans'))"`

Expected: `('Delhi Capitals', 'Gujarat Titans')` and `GT`

- [ ] **Step 3: Commit**

```bash
git add backend/cricket.py
git commit -m "feat: add cricket.py with IPL team aliases and ESPN API fetching"
```

---

### Task 3: Cricket Backend — ESPN Data Parsers

**Files:**
- Modify: `backend/cricket.py` (append after the fetching functions)

- [ ] **Step 1: Add ESPN data parsing functions**

Append these parsing functions to `cricket.py`:

```python
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
```

- [ ] **Step 2: Verify parsers import**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "from cricket import _parse_balls_from_playbyplay, _parse_odds; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/cricket.py
git commit -m "feat: add ESPN cricket data parsers for scorecard, ball-by-ball, odds"
```

---

### Task 4: Cricket Backend — Cache & Main Orchestrator

**Files:**
- Modify: `backend/cricket.py` (append cache + orchestrator)

- [ ] **Step 1: Add caching layer and get_cricket_data orchestrator**

Append to `cricket.py`:

```python
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
        odds = _parse_odds(summary.get("pickcenter"))
        if odds:
            _cache_set(match_id, "odds", odds)

    toss = _cache_get(match_id, "toss")
    if toss is None:
        toss = _parse_toss(game_info)
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

    # Squads
    squads_raw = _cache_get(match_id, "squads")
    if squads_raw is None:
        squads_raw = _parse_squads(summary.get("rosters"))
        if squads_raw:
            _cache_set(match_id, "squads", squads_raw)

    # Map squad keys to home/away
    squads = {}
    if squads_raw:
        if home.short_name in squads_raw:
            squads["home"] = squads_raw[home.short_name]
        if away.short_name in squads_raw:
            squads["away"] = squads_raw[away.short_name]

    # Innings/scorecard
    innings = _cache_get(match_id, "innings")
    if innings is None:
        innings = _parse_innings_from_summary(summary)
        if innings:
            _cache_set(match_id, "innings", innings)
    innings = innings or []

    # Ball-by-ball (latest page only for live data)
    balls = _cache_get(match_id, "balls")
    if balls is None and status in ("live", "complete"):
        pbp = _fetch_espn_playbyplay(espn_match_id)
        balls = _parse_balls_from_playbyplay(pbp)
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
```

- [ ] **Step 2: Verify orchestrator runs without errors**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "from cricket import get_cricket_data; print(type(get_cricket_data))"`

Expected: `<class 'function'>`

- [ ] **Step 3: Commit**

```bash
git add backend/cricket.py
git commit -m "feat: add cricket cache layer and main get_cricket_data orchestrator"
```

---

### Task 5: Cricket Backend — FastAPI Endpoint

**Files:**
- Modify: `backend/app.py` (add endpoint after basketball endpoint ~line 1252)

- [ ] **Step 1: Add cricket import at the top of app.py**

Add after the basketball import (find the line `from basketball import get_basketball_data`):

```python
from cricket import get_cricket_data
```

- [ ] **Step 2: Add the /api/market/{condition_id}/cricket endpoint**

Add after the basketball endpoint (after line 1252):

```python
@app.get("/api/market/{condition_id}/cricket")
def get_market_cricket(
    condition_id: str,
    title: str = Query(default="", description="Market title, e.g. 'Delhi Capitals vs Gujarat Titans'"),
    event_slug: str = Query(default="", description="Event slug, e.g. 'ipl-dc-gt-2026-04-08'"),
):
    """Get live cricket game data for an IPL market.

    Matches the market title to an IPL match and returns live scores,
    ball-by-ball commentary, scorecard, Bet 365 odds, venue, toss, squads,
    and head-to-head. Returns null if no matching game is found."""
    if not title:
        return None
    return get_cricket_data(title, event_slug=event_slug)
```

- [ ] **Step 3: Verify the endpoint registers**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "from app import app; routes = [r.path for r in app.routes]; print('/api/market/{condition_id}/cricket' in routes)"`

Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat: add /api/market/{condition_id}/cricket FastAPI endpoint"
```

---

### Task 6: Frontend — API Client & Polling Hook

**Files:**
- Modify: `frontend/src/lib/api.js` (add fetchCricketData)
- Create: `frontend/src/hooks/useCricketData.js`

- [ ] **Step 1: Add fetchCricketData to api.js**

Add after the `fetchBasketballData` function in `frontend/src/lib/api.js`:

```javascript
export function fetchCricketData(conditionId, { title = "", event_slug = "" } = {}) {
  return request(`/api/market/${conditionId}/cricket`, { title, event_slug });
}
```

- [ ] **Step 2: Create useCricketData.js hook**

```javascript
import { useEffect, useState, useRef, useCallback } from "react";
import { fetchCricketData } from "../lib/api";

const POLL_INTERVALS = {
  pre: 60_000,
  live: 15_000,
  complete: null,
};

export default function useCricketData(conditionId, { initialData = null, title = "", eventSlug = "" } = {}) {
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  const retryDelay = useRef(15_000);

  const clearPoll = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!conditionId) return;

    let cancelled = false;

    const load = async () => {
      try {
        const result = await fetchCricketData(conditionId, { title, event_slug: eventSlug });
        if (cancelled) return;

        setData(result);
        setError(null);
        setLoading(false);
        retryDelay.current = 15_000;

        const status = result?.status;
        const interval = POLL_INTERVALS[status] ?? POLL_INTERVALS.pre;

        clearPoll();
        if (interval !== null) {
          intervalRef.current = setInterval(load, interval);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err);
        setLoading(false);

        clearPoll();
        const nextDelay = Math.min(retryDelay.current * 2, 60_000);
        retryDelay.current = nextDelay;
        intervalRef.current = setInterval(load, nextDelay);
      }
    };

    load();

    return () => {
      cancelled = true;
      clearPoll();
    };
  }, [conditionId, title, eventSlug, clearPoll]);

  return { data, loading, error };
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.js frontend/src/hooks/useCricketData.js
git commit -m "feat: add fetchCricketData API client and useCricketData polling hook"
```

---

### Task 7: Frontend — CricketScoreBanner Component

**Files:**
- Create: `frontend/src/components/CricketScoreBanner.jsx`

- [ ] **Step 1: Create CricketScoreBanner.jsx**

```jsx
"use client";

import { useState, useEffect } from "react";

function Countdown({ targetDate }) {
  const [timeLeft, setTimeLeft] = useState("");

  useEffect(() => {
    const tick = () => {
      const diff = new Date(targetDate).getTime() - Date.now();
      if (diff <= 0) {
        setTimeLeft("Starting soon");
        return;
      }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setTimeLeft(h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetDate]);

  return <span>{timeLeft}</span>;
}

function StatusBadge({ status }) {
  if (status === "live") {
    return (
      <div className="flex items-center gap-1.5">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: "var(--accent)" }} />
          <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} />
        </span>
        <span className="text-[0.65rem] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>
          Live
        </span>
      </div>
    );
  }
  if (status === "complete") {
    return (
      <span
        className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold uppercase tracking-wider"
        style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}
      >
        Final
      </span>
    );
  }
  return null;
}

export default function CricketScoreBanner({ game, polymarketPrice }) {
  if (!game) return null;

  const { status, match_time, home, away, toss, venue, odds, status_text } = game;

  return (
    <div
      className="mb-4 overflow-hidden rounded-xl border"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      {/* Score row */}
      <div className="flex items-center justify-center gap-6 px-4 py-4 sm:gap-10 sm:px-8">
        {/* Away team */}
        <div className="text-center min-w-[80px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {away.short_name}
          </div>
          <div
            className="text-2xl font-extrabold tabular-nums leading-tight sm:text-3xl"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-primary)",
            }}
          >
            {status === "pre" ? "\u2014" : away.score || "\u2014"}
          </div>
          {status !== "pre" && away.overs && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              ({away.overs} ov)
            </div>
          )}
        </div>

        {/* Center: status */}
        <div className="text-center">
          <StatusBadge status={status} />
          {status === "pre" && match_time && (
            <div className="mt-1 text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              <Countdown targetDate={match_time} />
            </div>
          )}
          {status_text && status !== "pre" && (
            <div className="mt-1 text-xs max-w-[200px]" style={{ color: "var(--text-secondary)" }}>
              {status_text}
            </div>
          )}
          {venue && (
            <div className="mt-0.5 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              {venue.name}{venue.city ? `, ${venue.city}` : ""}
            </div>
          )}
        </div>

        {/* Home team */}
        <div className="text-center min-w-[80px]">
          <div
            className="text-[0.65rem] font-semibold uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {home.short_name}
          </div>
          <div
            className="text-2xl font-extrabold tabular-nums leading-tight sm:text-3xl"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--text-primary)",
            }}
          >
            {status === "pre" ? "\u2014" : home.score || "\u2014"}
          </div>
          {status !== "pre" && home.overs && (
            <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
              ({home.overs} ov)
            </div>
          )}
        </div>
      </div>

      {/* Toss info */}
      {toss && toss.winner && (
        <div className="text-center pb-2 text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
          Toss: {toss.winner}{toss.decision ? `, elected to ${toss.decision}` : ""}
        </div>
      )}

      {/* Info strip: Odds + Polymarket */}
      <div
        className="grid grid-cols-1 gap-px sm:grid-cols-2"
        style={{ background: "var(--border)", borderTop: "1px solid var(--border)" }}
      >
        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            {odds?.provider || "Odds"}
          </div>
          {odds && (odds.home_odds || odds.away_odds) ? (
            <div className="flex gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
              <span>{home.short_name}: <b style={{ color: "var(--text-primary)" }}>{odds.home_odds}</b></span>
              <span>{away.short_name}: <b style={{ color: "var(--text-primary)" }}>{odds.away_odds}</b></span>
            </div>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>

        <div className="px-4 py-2.5" style={{ background: "var(--surface-card)" }}>
          <div
            className="mb-1 text-[0.55rem] uppercase tracking-wider"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
          >
            Polymarket
          </div>
          {polymarketPrice != null ? (
            <div className="text-xs font-bold" style={{ color: "var(--accent)" }}>
              {Math.round(polymarketPrice * 100)}&cent;
            </div>
          ) : (
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/CricketScoreBanner.jsx
git commit -m "feat: add CricketScoreBanner component with live scores, toss, odds"
```

---

### Task 8: Frontend — BallByBallFeed Component

**Files:**
- Create: `frontend/src/components/BallByBallFeed.jsx`

- [ ] **Step 1: Create BallByBallFeed.jsx**

```jsx
"use client";

import { useState } from "react";

export default function BallByBallFeed({ balls = [] }) {
  const [showAll, setShowAll] = useState(false);

  if (!balls || balls.length === 0) return null;

  const visible = showAll ? balls : balls.slice(0, 30);

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      <div className="px-4 py-2.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <h3
          className="text-[0.6rem] font-semibold uppercase tracking-widest"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
        >
          Ball by Ball
        </h3>
      </div>

      <div className="max-h-[400px] overflow-y-auto">
        {visible.map((ball, i) => {
          const bgStyle = ball.is_wicket
            ? { background: "rgba(239, 68, 68, 0.08)" }
            : ball.is_boundary
              ? { background: "rgba(0, 194, 106, 0.08)" }
              : {};

          return (
            <div
              key={i}
              className="flex gap-3 px-4 py-2 text-xs"
              style={{ ...bgStyle, borderBottom: "1px solid var(--border)" }}
            >
              {/* Over.ball badge */}
              <div
                className="shrink-0 w-10 text-center rounded px-1 py-0.5 font-mono text-[0.6rem] font-bold"
                style={{
                  background: "var(--surface-2)",
                  color: ball.is_wicket
                    ? "var(--bearish)"
                    : ball.is_boundary
                      ? "var(--accent)"
                      : "var(--text-muted)",
                }}
              >
                {ball.over}.{ball.ball_in_over}
              </div>

              {/* Commentary */}
              <div className="flex-1 min-w-0">
                <div style={{ color: "var(--text-primary)" }}>
                  {ball.commentary_short}
                </div>
                {ball.commentary_detail && ball.commentary_detail !== ball.commentary_short && (
                  <div className="mt-0.5 text-[0.6rem] leading-relaxed" style={{ color: "var(--text-muted)" }}>
                    {ball.commentary_detail}
                  </div>
                )}
              </div>

              {/* Runs badge */}
              <div className="shrink-0">
                {ball.is_wicket ? (
                  <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold" style={{ background: "rgba(239, 68, 68, 0.15)", color: "var(--bearish)" }}>
                    W
                  </span>
                ) : ball.is_boundary ? (
                  <span className="rounded px-1.5 py-0.5 text-[0.6rem] font-bold" style={{ background: "rgba(0, 194, 106, 0.15)", color: "var(--accent)" }}>
                    {ball.runs}
                  </span>
                ) : ball.runs > 0 ? (
                  <span className="text-[0.6rem] font-bold" style={{ color: "var(--text-secondary)" }}>
                    {ball.runs}
                  </span>
                ) : (
                  <span className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
                    0
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {balls.length > 30 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full py-2 text-xs font-medium cursor-pointer"
          style={{ color: "var(--accent)", background: "var(--surface-1)", border: "none", borderTop: "1px solid var(--border)" }}
        >
          Show all {balls.length} deliveries
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/BallByBallFeed.jsx
git commit -m "feat: add BallByBallFeed component with boundary/wicket highlighting"
```

---

### Task 9: Frontend — CricketScorecard Component

**Files:**
- Create: `frontend/src/components/CricketScorecard.jsx`

- [ ] **Step 1: Create CricketScorecard.jsx**

```jsx
"use client";

import { useState } from "react";

function BattingTable({ batting }) {
  if (!batting || batting.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="text-left py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Batter</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>R</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>B</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>4s</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>6s</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>SR</th>
          </tr>
        </thead>
        <tbody>
          {batting.map((b, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-1.5 px-2">
                <div style={{ color: "var(--text-primary)" }}>{b.name}</div>
                {b.how_out && (
                  <div className="text-[0.6rem]" style={{ color: "var(--text-muted)" }}>
                    {b.how_out}
                  </div>
                )}
              </td>
              <td className="text-right py-1.5 px-2 font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>{b.runs}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.balls}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.fours}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.sixes}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-muted)" }}>{b.strike_rate.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BowlingTable({ bowling }) {
  if (!bowling || bowling.length === 0) return null;

  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)" }}>
            <th className="text-left py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Bowler</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>O</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>M</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>R</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>W</th>
            <th className="text-right py-1.5 px-2 font-semibold" style={{ color: "var(--text-muted)" }}>Econ</th>
          </tr>
        </thead>
        <tbody>
          {bowling.map((b, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
              <td className="py-1.5 px-2" style={{ color: "var(--text-primary)" }}>{b.name}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.overs}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.maidens}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-secondary)" }}>{b.runs}</td>
              <td className="text-right py-1.5 px-2 font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>{b.wickets}</td>
              <td className="text-right py-1.5 px-2 tabular-nums" style={{ color: "var(--text-muted)" }}>{b.economy.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CricketScorecard({ innings = [], home, away }) {
  const [activeTab, setActiveTab] = useState(0);

  if (!innings || innings.length === 0) return null;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      {/* Tabs */}
      <div className="flex" style={{ borderBottom: "1px solid var(--border)" }}>
        {innings.map((inn, i) => (
          <button
            key={i}
            onClick={() => setActiveTab(i)}
            className="flex-1 py-2 text-xs font-semibold uppercase tracking-wider cursor-pointer"
            style={{
              fontFamily: "var(--font-display)",
              background: activeTab === i ? "var(--surface-card)" : "var(--surface-1)",
              color: activeTab === i ? "var(--text-primary)" : "var(--text-muted)",
              border: "none",
              borderBottom: activeTab === i ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            {inn.team}
            {inn.score > 0 && (
              <span className="ml-1.5" style={{ color: "var(--text-secondary)" }}>
                {inn.score}/{inn.wickets}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Active innings */}
      <div className="p-3">
        <BattingTable batting={innings[activeTab]?.batting} />
        <BowlingTable bowling={innings[activeTab]?.bowling} />

        {/* Fall of wickets */}
        {innings[activeTab]?.fall_of_wickets?.length > 0 && (
          <div className="mt-3 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="text-[0.55rem] uppercase tracking-wider font-semibold mb-1" style={{ color: "var(--text-muted)" }}>
              Fall of Wickets
            </div>
            <div className="flex flex-wrap gap-2 text-[0.6rem]" style={{ color: "var(--text-secondary)" }}>
              {innings[activeTab].fall_of_wickets.map((fow, i) => (
                <span key={i}>
                  {fow.wicket_num}/{fow.score}
                  {fow.batsman && ` (${fow.batsman})`}
                  {fow.over && `, ${fow.over} ov`}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/CricketScorecard.jsx
git commit -m "feat: add CricketScorecard component with batting/bowling tables"
```

---

### Task 10: Frontend — CricketMatchInfo & CricketPreMatch Components

**Files:**
- Create: `frontend/src/components/CricketMatchInfo.jsx`
- Create: `frontend/src/components/CricketPreMatch.jsx`

- [ ] **Step 1: Create CricketMatchInfo.jsx**

```jsx
"use client";

export default function CricketMatchInfo({ game }) {
  if (!game) return null;

  const { partnership, run_rate, required_rate, head_to_head, home, away } = game;

  const hasAnyData = partnership || run_rate || required_rate || head_to_head;
  if (!hasAnyData) return null;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px" style={{ background: "var(--border)" }}>
        {/* Partnership */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Partnership
          </div>
          {partnership ? (
            <>
              <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
                {partnership.runs}({partnership.balls})
              </div>
              <div className="text-[0.55rem]" style={{ color: "var(--text-muted)" }}>
                {partnership.batsman1} &amp; {partnership.batsman2}
              </div>
            </>
          ) : (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>

        {/* Run Rate */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Run Rate
          </div>
          <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
            {run_rate != null ? run_rate.toFixed(2) : "\u2014"}
          </div>
        </div>

        {/* Required Rate */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            Req. Rate
          </div>
          <div
            className="text-sm font-bold tabular-nums"
            style={{
              color: required_rate != null && run_rate != null && required_rate > run_rate
                ? "var(--bearish)"
                : "var(--text-primary)",
            }}
          >
            {required_rate != null ? required_rate.toFixed(2) : "\u2014"}
          </div>
        </div>

        {/* Head to Head */}
        <div className="px-3 py-2.5 text-center" style={{ background: "var(--surface-card)" }}>
          <div className="text-[0.55rem] uppercase tracking-wider font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}>
            H2H
          </div>
          {head_to_head ? (
            <div className="text-sm font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
              {home.short_name} {head_to_head.home_wins}-{head_to_head.away_wins} {away.short_name}
            </div>
          ) : (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>{"\u2014"}</div>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create CricketPreMatch.jsx**

```jsx
"use client";

export default function CricketPreMatch({ game }) {
  if (!game || game.status !== "pre") return null;

  const { squads, head_to_head, venue, home, away } = game;
  const homeSquad = squads?.home || [];
  const awaySquad = squads?.away || [];

  if (homeSquad.length === 0 && awaySquad.length === 0 && !head_to_head) return null;

  const roleBadgeColor = (role) => {
    const r = role?.toLowerCase() || "";
    if (r.includes("wicketkeeper")) return "rgba(168, 85, 247, 0.15)";
    if (r.includes("allrounder")) return "rgba(59, 130, 246, 0.15)";
    if (r.includes("bowler")) return "rgba(239, 68, 68, 0.1)";
    return "rgba(0, 194, 106, 0.1)";
  };

  const roleText = (role) => {
    const r = role?.toLowerCase() || "";
    if (r.includes("wicketkeeper")) return "WK";
    if (r.includes("allrounder") || r.includes("all-rounder")) return "AR";
    if (r.includes("bowler")) return "BOWL";
    return "BAT";
  };

  function SquadList({ players, teamName }) {
    if (!players || players.length === 0) return null;
    return (
      <div>
        <div
          className="text-[0.6rem] font-semibold uppercase tracking-wider mb-2"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
        >
          {teamName}
        </div>
        <div className="flex flex-col gap-1">
          {players.map((p, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span style={{ color: "var(--text-primary)" }}>{p.name}</span>
              {p.role && (
                <span
                  className="rounded px-1 py-0.5 text-[0.5rem] font-bold uppercase"
                  style={{ background: roleBadgeColor(p.role), color: "var(--text-secondary)" }}
                >
                  {roleText(p.role)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: "var(--border)", background: "var(--surface-card)" }}
    >
      <div className="px-4 py-2.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <h3
          className="text-[0.6rem] font-semibold uppercase tracking-widest"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)" }}
        >
          Match Preview
        </h3>
      </div>

      <div className="p-4">
        {/* Head to Head */}
        {head_to_head && (
          <div className="mb-4 text-center text-xs" style={{ color: "var(--text-secondary)" }}>
            Season record: <b style={{ color: "var(--text-primary)" }}>{home.short_name} {head_to_head.home_wins}-{head_to_head.away_wins} {away.short_name}</b>
            {" "}({head_to_head.total} matches)
          </div>
        )}

        {/* Squads */}
        {(homeSquad.length > 0 || awaySquad.length > 0) && (
          <div className="grid grid-cols-2 gap-4">
            <SquadList players={homeSquad} teamName={home.short_name || home.name} />
            <SquadList players={awaySquad} teamName={away.short_name || away.name} />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CricketMatchInfo.jsx frontend/src/components/CricketPreMatch.jsx
git commit -m "feat: add CricketMatchInfo and CricketPreMatch components"
```

---

### Task 11: Frontend — CricketPageClient & Page Routing

**Files:**
- Create: `frontend/src/app/market/[id]/cricket-page-client.jsx`
- Modify: `frontend/src/app/market/[id]/page.jsx`

- [ ] **Step 1: Create cricket-page-client.jsx**

This follows the exact same structure as `basketball-page-client.jsx` — same header, same two-column layout, but renders cricket components above the existing market content.

```jsx
"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import AlertRow from "../../../components/AlertRow";
import PriceChart from "../../../components/PriceChart";
import MarketStats from "../../../components/MarketStats";
import HoldersLeaderboard from "../../../components/HoldersLeaderboard";
import MarketPulse from "../../../components/MarketPulse";
import MarketTheses from "../../../components/MarketTheses";
import CricketScoreBanner from "../../../components/CricketScoreBanner";
import BallByBallFeed from "../../../components/BallByBallFeed";
import CricketScorecard from "../../../components/CricketScorecard";
import CricketMatchInfo from "../../../components/CricketMatchInfo";
import CricketPreMatch from "../../../components/CricketPreMatch";
import useLiveMarket from "../../../hooks/useLiveMarket";
import useCricketData from "../../../hooks/useCricketData";
import ThemeToggle from "../../../components/ThemeToggle";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function timeToResolution(dateStr) {
  if (!dateStr) return null;
  const diffMs = new Date(dateStr).getTime() - Date.now();
  if (diffMs <= 0) return "Resolved";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  return `${Math.floor(diffHr / 24)}d`;
}

export default function CricketPageClient({
  conditionId,
  initialLive,
  initialAlerts,
  priceHistory,
  holders,
  theses,
  initialCricketData,
  eventSlug = "",
}) {
  const { data: liveMarket } = useLiveMarket(conditionId);
  const live = liveMarket || initialLive;
  const alerts = initialAlerts || [];
  const [descExpanded, setDescExpanded] = useState(false);

  const marketTitle = live?.title || alerts?.[0]?.market_title || "";
  const slug = eventSlug || alerts?.[0]?.event_slug || "";
  const { data: cricketData } = useCricketData(conditionId, { initialData: initialCricketData, title: marketTitle, eventSlug: slug });

  const title = live?.title || alerts?.[0]?.market_title || "Market";
  const endDate = live?.end_date || alerts?.[0]?.end_date;
  const resolution = timeToResolution(endDate);
  const totalUsd = alerts.reduce((sum, a) => sum + (a.total_usd || 0), 0);
  const tags = [...new Set(alerts.flatMap((a) => a.tags || []))];
  const isUrgent = endDate && new Date(endDate).getTime() - Date.now() < 3600000 && new Date(endDate).getTime() - Date.now() > 0;
  const isSoon = endDate && new Date(endDate).getTime() - Date.now() < 86400000 && new Date(endDate).getTime() - Date.now() > 0;

  const outcomes = live?.outcomes || [];
  const description = alerts?.[0]?.market_description || live?.description;

  return (
    <main className="mx-auto max-w-5xl px-4 py-4">
      {/* Nav */}
      <nav className="mb-4 flex items-center justify-between" aria-label="Breadcrumb">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
          style={{ color: "var(--text-muted)" }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          All markets
        </Link>
        <ThemeToggle />
      </nav>

      {/* Compact header */}
      <header className="mb-4">
        <div className="flex gap-4 items-start">
          {alerts?.[0]?.market_image && (
            <div
              className="relative shrink-0 rounded-lg overflow-hidden"
              style={{ width: "72px", height: "72px", border: "1px solid var(--border)" }}
            >
              <Image src={alerts[0].market_image} alt="" fill className="object-cover" />
            </div>
          )}

          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
              {title}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
              {resolution && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"
                  style={{
                    background: isUrgent ? "rgba(239, 68, 68, 0.1)" : isSoon ? "rgba(245, 158, 11, 0.1)" : "var(--surface-2)",
                    color: resolution === "Resolved" ? "var(--text-muted)" : isUrgent ? "var(--bearish)" : isSoon ? "var(--warning)" : "var(--text-secondary)",
                    fontSize: "0.65rem",
                  }}
                >
                  {isUrgent && (
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
                    </span>
                  )}
                  {resolution}
                </span>
              )}
              {totalUsd > 0 && (
                <span style={{ fontFamily: "var(--font-display)" }}>{usdFmt.format(totalUsd)} tracked</span>
              )}
              <span>{alerts.length} signal{alerts.length !== 1 ? "s" : ""}</span>
              {tags.map((t) => (
                <span key={t} className="rounded-full px-1.5 py-0.5" style={{ background: "var(--surface-2)", color: "var(--text-muted)", fontSize: "0.6rem" }}>
                  {t}
                </span>
              ))}
            </div>
          </div>

          {/* Outcome pills */}
          {outcomes.length > 0 && (
            <div className="hidden sm:flex items-center gap-2 shrink-0">
              {outcomes.map((o) => {
                const pct = Math.round((o.price || 0) * 100);
                const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
                const isLeading = pct === maxPct && pct > 50;
                return (
                  <div key={o.name} className="rounded-lg border px-3 py-1.5 text-center" style={{ borderColor: isLeading ? "rgba(0, 194, 106, 0.3)" : "var(--border)", background: "var(--surface-card)", boxShadow: isLeading ? "var(--glow-medium)" : "none", minWidth: "72px" }}>
                    <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>{o.name}</div>
                    <div className="text-lg font-bold tabular-nums leading-tight" style={{ fontFamily: "var(--font-display)", color: isLeading ? "var(--accent)" : "var(--text-primary)" }}>{pct}&cent;</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Mobile outcome row */}
        {outcomes.length > 0 && (
          <div className="sm:hidden mt-3 flex gap-2">
            {outcomes.map((o) => {
              const pct = Math.round((o.price || 0) * 100);
              const maxPct = Math.max(...outcomes.map((oo) => Math.round((oo.price || 0) * 100)));
              const isLeading = pct === maxPct && pct > 50;
              return (
                <div key={o.name} className="flex-1 rounded-lg border px-3 py-1.5 text-center" style={{ borderColor: isLeading ? "rgba(0, 194, 106, 0.3)" : "var(--border)", background: "var(--surface-card)", boxShadow: isLeading ? "var(--glow-medium)" : "none" }}>
                  <div className="text-[0.6rem] uppercase tracking-wider" style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}>{o.name}</div>
                  <div className="text-lg font-bold tabular-nums leading-tight" style={{ fontFamily: "var(--font-display)", color: isLeading ? "var(--accent)" : "var(--text-primary)" }}>{pct}&cent;</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Description */}
        {description && (
          <div className="mt-2">
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)", display: "-webkit-box", WebkitLineClamp: descExpanded ? "unset" : 2, WebkitBoxOrient: "vertical", overflow: descExpanded ? "visible" : "hidden" }}>
              {description}
            </p>
            {description.length > 140 && (
              <button onClick={() => setDescExpanded(!descExpanded)} className="mt-0.5 text-xs font-medium cursor-pointer" style={{ color: "var(--accent)", background: "none", border: "none", padding: 0 }}>
                {descExpanded ? "Less" : "More"}
              </button>
            )}
          </div>
        )}
      </header>

      {/* Cricket Score Banner */}
      <CricketScoreBanner game={cricketData} polymarketPrice={outcomes?.[0]?.price} />

      {/* Cricket Match Info bar */}
      {cricketData && cricketData.status !== "pre" && (
        <div className="mb-4">
          <CricketMatchInfo game={cricketData} />
        </div>
      )}

      {/* Two-column: Trades (primary) + Sidebar */}
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        {/* Left: Notable Trades */}
        <section>
          {alerts.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2 className="text-xs font-semibold uppercase tracking-widest" style={{ fontFamily: "var(--font-display)", color: "var(--text-muted)", fontSize: "0.6rem" }}>
                Notable Trades
              </h2>
              {alerts.map((alert) => (
                <AlertRow key={alert.id} alert={alert} autoExpand activeTag="" onTagClick={() => {}} liveMarket={live} />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border p-12 text-center" style={{ borderColor: "var(--border)", background: "var(--surface-card)", color: "var(--text-muted)" }}>
              No signals found for this market.
            </div>
          )}
        </section>

        {/* Right sidebar */}
        <aside className="flex flex-col gap-4">
          {/* Price Chart */}
          {priceHistory && priceHistory.history?.length > 1 && (
            <PriceChart history={priceHistory.history} outcome={priceHistory.outcome} alerts={alerts} conditionId={conditionId} />
          )}

          {/* Market Stats */}
          <MarketStats volume24h={live?.volume_24h} liquidity={live?.liquidity} spread={live?.spread} alerts={alerts} />

          {/* Cricket Widgets */}
          {cricketData && (
            <>
              {/* Pre-match preview */}
              {cricketData.status === "pre" && (
                <CricketPreMatch game={cricketData} />
              )}

              {/* Ball-by-ball feed (live/complete) */}
              {cricketData.balls?.length > 0 && (
                <BallByBallFeed balls={cricketData.balls} />
              )}

              {/* Scorecard (live/complete) */}
              {cricketData.innings?.length > 0 && (
                <CricketScorecard innings={cricketData.innings} home={cricketData.home} away={cricketData.away} />
              )}
            </>
          )}

          {/* Holders + Pulse */}
          {(holders?.length > 0 || alerts.length > 0) && (
            <>
              <HoldersLeaderboard holders={holders} />
              <MarketPulse alerts={alerts} volume24h={live?.volume_24h} />
            </>
          )}
        </aside>
      </div>

      {/* Related Theses */}
      {theses?.length > 0 && (
        <div className="mt-8">
          <MarketTheses theses={theses} />
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 2: Modify page.jsx to detect cricket markets and route to CricketPageClient**

In `frontend/src/app/market/[id]/page.jsx`:

Add the import at line 2 (after BasketballPageClient import):

```javascript
import CricketPageClient from "./cricket-page-client";
```

In the `getMarketData` function, after the basketball detection block (after line 70), add cricket detection:

```javascript
    // Only fetch cricket data if tags suggest it's a cricket market
    const cricketTags = ["cricket", "ipl", "indian premier league"];
    const maybeCricket = !maybeBasketball && tags.some((t) =>
      cricketTags.includes(t.toLowerCase())
    );
    let cricketData = null;
    if (maybeCricket) {
      const marketTitle = live?.title || (alertsData?.alerts || [])[0]?.market_title || "";
      const eventSlug = (alertsData?.alerts || [])[0]?.event_slug || "";
      try {
        const cricketParams = new URLSearchParams({ title: marketTitle, event_slug: eventSlug });
        const cricketRes = await fetch(
          `${API_URL}/api/market/${conditionId}/cricket?${cricketParams}`,
          { next: { revalidate: 15 } }
        );
        cricketData = cricketRes?.ok ? await cricketRes.json() : null;
      } catch {}
    }
```

Update the return statement to include `cricketData`:

```javascript
    return {
      live,
      alerts: alertsData?.alerts || [],
      priceHistory: priceData,
      holders: holdersData?.holders || [],
      theses: thesesData?.theses || [],
      basketballData,
      cricketData,
    };
```

Also update the error return:

```javascript
    return {
      live: null,
      alerts: [],
      priceHistory: null,
      holders: [],
      theses: [],
      basketballData: null,
      cricketData: null,
    };
```

In the `MarketPage` function, destructure `cricketData`:

```javascript
  const { live, alerts, priceHistory, holders, theses, basketballData, cricketData } =
    await getMarketData(conditionId);
```

Update the routing logic at the bottom of the component (the IIFE around line 373):

```javascript
      {(() => {
        const isBasketball = !!basketballData;
        const isCricket = !isBasketball && !!cricketData;
        const PageClient = isBasketball
          ? BasketballPageClient
          : isCricket
            ? CricketPageClient
            : MarketPageClient;
        const clientProps = {
          conditionId,
          initialLive: live,
          initialAlerts: alerts,
          priceHistory,
          holders,
          theses,
          ...(isBasketball ? { initialGameData: basketballData, eventSlug: alerts?.[0]?.event_slug || "" } : {}),
          ...(isCricket ? { initialCricketData: cricketData, eventSlug: alerts?.[0]?.event_slug || "" } : {}),
        };
        return <PageClient {...clientProps} />;
      })()}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/market/[id]/cricket-page-client.jsx frontend/src/app/market/[id]/page.jsx
git commit -m "feat: add CricketPageClient and wire up cricket detection in page routing"
```

---

### Task 12: Integration Test — End-to-End Smoke Test

**Files:**
- No new files; manual verification

- [ ] **Step 1: Verify backend endpoint works with a real IPL match title**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "
from cricket import get_cricket_data
import json
result = get_cricket_data('Delhi Capitals vs Gujarat Titans')
if result:
    print('Status:', result.status)
    print('Home:', result.home.short_name, result.home.score)
    print('Away:', result.away.short_name, result.away.score)
    print('Venue:', result.venue)
    print('Odds:', result.odds)
    print('Innings:', len(result.innings))
    print('Balls:', len(result.balls))
    print('Squads:', {k: len(v) for k, v in result.squads.items()})
else:
    print('No match found (expected if no current IPL match for these teams)')
"`

Expected: Either match data printed, or "No match found" (both are valid depending on whether there's a current/recent IPL match between these teams).

- [ ] **Step 2: Test the FastAPI endpoint directly**

Run: `cd /Users/bhavya/git/polybot/backend && source ../venv/bin/activate && python -c "
from fastapi.testclient import TestClient
from app import app
client = TestClient(app)
resp = client.get('/api/market/test123/cricket', params={'title': 'Delhi Capitals vs Gujarat Titans'})
print('Status:', resp.status_code)
print('Body type:', type(resp.json()))
"`

Expected: Status 200, Body type: `<class 'dict'>` or `<class 'NoneType'>`

- [ ] **Step 3: Verify frontend builds without errors**

Run: `cd /Users/bhavya/git/polybot/frontend && npm run build 2>&1 | tail -20`

Expected: Build succeeds without errors.

- [ ] **Step 4: Commit any fixes needed**

Only if fixes were required from the above tests.

---

### Task 13: Final Review & Cleanup

- [ ] **Step 1: Run existing test suites to verify no regressions**

Run: `cd /Users/bhavya/git/polybot && source venv/bin/activate && pytest 2>&1 | tail -10`
Run: `cd /Users/bhavya/git/polybot/frontend && npm run lint 2>&1 | tail -10`

Expected: All tests pass, lint clean.

- [ ] **Step 2: Fix any issues found**

- [ ] **Step 3: Final commit if needed**
