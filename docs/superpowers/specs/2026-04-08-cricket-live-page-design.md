# Cricket Live Page Design

**Date:** 2026-04-08
**Status:** Approved

## Overview

Add a live cricket match experience to Polymarket cricket market pages, mirroring the existing basketball enrichment pattern. When a market is detected as an IPL cricket match, the page renders a live score banner, ball-by-ball commentary feed, full scorecard, and match info bar above the existing Polymarket trading data (notable trades, price chart, top holders).

## Data Source

**ESPN API** — free, no auth required. Same API used for basketball enrichment.

- **Scoreboard:** `https://site.api.espn.com/apis/site/v2/sports/cricket/8048/scoreboard`
- **Match summary:** `https://site.api.espn.com/apis/site/v2/sports/cricket/8048/summary?event={matchId}`
- **Ball-by-ball:** `https://site.api.espn.com/apis/site/v2/sports/cricket/8048/playbyplay?event={matchId}`

League ID `8048` = IPL. Start with IPL only, expand to other leagues later.

Summary endpoint includes Bet 365 match-winner odds, venue, squads, toss, head-to-head, and officials.

## Approach

Mirror the basketball architecture (Approach A). New `backend/cricket.py` with a dedicated endpoint, cricket-specific Pydantic models in `backend/models.py`, and new frontend components rendered above the existing market page content.

## Backend

### Endpoint

```
GET /api/market/{condition_id}/cricket?title=...&event_slug=...
```

- `title`: Market title used to parse team names (e.g., "Delhi Capitals vs Gujarat Titans")
- `event_slug`: Contains date for matching (e.g., "ipl-dc-gt-2026-04-08")

### Data Flow

1. Parse team names from market title (handle "vs", "v", IPL team aliases)
2. Fetch ESPN scoreboard for IPL (league 8048) — find matching game by team + date
3. Fetch match summary (venue, squads, toss, Bet 365 odds, head-to-head)
4. Fetch ball-by-ball commentary (paginated, latest page first)
5. Merge into `CricketGameData` Pydantic model and return

### IPL Team Name Resolution

Map common names, abbreviations, and city names to ESPN team identifiers for all 10 IPL teams:

- Chennai Super Kings / CSK / Chennai
- Mumbai Indians / MI / Mumbai
- Royal Challengers Bengaluru / RCB / Bengaluru / Bangalore
- Kolkata Knight Riders / KKR / Kolkata
- Delhi Capitals / DC / Delhi
- Punjab Kings / PBKS / Punjab
- Rajasthan Royals / RR / Rajasthan
- Sunrisers Hyderabad / SRH / Hyderabad
- Gujarat Titans / GT / Gujarat
- Lucknow Super Giants / LSG / Lucknow

### Data Models

```
CricketGameData:
  match_id, espn_match_id
  status: "pre" | "live" | "complete"
  match_time (ISO datetime)
  home, away: CricketTeam
  toss: {winner: str, decision: "bat" | "field"}
  venue: {name: str, city: str}
  odds: CricketOdds
  innings: list[Innings]          # 1-4 innings (T20 = max 2)
  current_batting: CricketBattingCard
  current_bowling: CricketBowlingCard
  partnership: {runs: int, balls: int, batsman1: str, batsman2: str}
  run_rate: float
  required_rate: float | null
  balls: list[BallEvent]          # latest 50 deliveries
  squads: {home: list, away: list}
  head_to_head: {home_wins: int, away_wins: int, total: int}

CricketTeam:
  name: str
  short_name: str                 # e.g. "GT", "DC"
  score: str                      # e.g. "156/9"
  overs: str                      # e.g. "20.0"
  logo_url: str | null

Innings:
  team: str
  score: int
  overs: str
  wickets: int
  batting: list[BatsmanEntry]     # name, runs, balls, fours, sixes, strike_rate, how_out
  bowling: list[BowlerEntry]     # name, overs, maidens, runs, wickets, economy
  fall_of_wickets: list[FoWEntry] # wicket_num, score, over, batsman

BatsmanEntry:
  name: str
  runs: int
  balls: int
  fours: int
  sixes: int
  strike_rate: float
  how_out: str                    # e.g. "c Kohli b Bumrah" or "not out"

BowlerEntry:
  name: str
  overs: str
  maidens: int
  runs: int
  wickets: int
  economy: float

BallEvent:
  over: int
  ball_in_over: int
  batsman: str
  bowler: str
  runs: int
  extras: int
  is_boundary: bool               # 4 or 6
  is_wicket: bool
  commentary_short: str           # e.g. "Bumrah to Gill, FOUR"
  commentary_detail: str          # full descriptive text
  score_after: str                # e.g. "156/9"

CricketOdds:
  provider: str                   # "Bet 365"
  home_odds: float
  away_odds: float
```

### Caching Strategy

Per-field TTLs matching basketball pattern:

| Field | TTL |
|-------|-----|
| Score, balls, partnership | 15 seconds |
| Batting/bowling card | 30 seconds |
| Odds | 60 seconds |
| Squads, toss, venue, h2h | 300 seconds |
| Scoreboard | 60 seconds |

## Frontend

### Detection & Routing

In `page.jsx`, detect cricket markets by checking alert tags for `["cricket", "ipl", "indian premier league"]`. If matched:
- Fetch `/api/market/{condition_id}/cricket` during SSR
- Render `CricketPageClient` instead of `MarketPageClient`
- Revalidate every 15 seconds

### Page Layout

Cricket experience renders as a **top section** above the existing market content:

```
┌─────────────────────────────────────────────────────┐
│  CricketScoreBanner                                 │
│  Team logos, scores, overs, status, toss, venue,    │
│  Bet 365 odds. Pulsing live dot when in progress.   │
├─────────────────────────────────────────────────────┤
│  ┌──────────────────────┐ ┌───────────────────────┐ │
│  │ BallByBallFeed       │ │ CricketScorecard      │ │
│  │ Latest 30 deliveries │ │ Tabbed by team        │ │
│  │ Newest first         │ │ Batting + Bowling     │ │
│  │ Boundaries = green   │ │ tables + FoW          │ │
│  │ Wickets = red        │ │                       │ │
│  └──────────────────────┘ └───────────────────────┘ │
├─────────────────────────────────────────────────────┤
│  MatchInfo bar                                      │
│  Partnership | Run Rate | Req Rate | Last 5 ov | H2H│
├─────────────────────────────────────────────────────┤
│  [Existing market page: Notable Trades, Price Chart,│
│   Market Stats, Top Holders, Theses]                │
└─────────────────────────────────────────────────────┘
```

### New Components (6 files)

| Component | File | Purpose |
|-----------|------|---------|
| `CricketScoreBanner` | `frontend/src/components/CricketScoreBanner.jsx` | Team names/logos, scores, overs, match status, toss, venue, odds. Pulsing live indicator. Countdown for pre-match. |
| `BallByBallFeed` | `frontend/src/components/BallByBallFeed.jsx` | Latest 30 deliveries, newest first. Over.ball, batsman/bowler, runs, commentary. Boundaries green, wickets red. Expandable. |
| `CricketScorecard` | `frontend/src/components/CricketScorecard.jsx` | Tabbed by team. Batting table (name, runs, balls, 4s, 6s, SR, dismissal). Bowling table (name, O, M, R, W, Econ). Fall of wickets. |
| `MatchInfo` | `frontend/src/components/CricketMatchInfo.jsx` | Stat bar: partnership, run rate, required rate, last 5 overs, head-to-head. |
| `PreMatchInfo` | `frontend/src/components/CricketPreMatch.jsx` | Pre-match: squads (two-column, role badges), venue, h2h, odds, countdown. Swapped for live experience when match starts. |
| `CricketPageClient` | `frontend/src/app/market/[id]/cricket-page-client.jsx` | Orchestrator: renders cricket sections above, passes market data through to standard layout below. |

### Polling Hook — `useCricketData.js`

`frontend/src/hooks/useCricketData.js` — same pattern as `useBasketballData.js`:

- **Pre-match:** poll every 60 seconds
- **Live:** poll every 15 seconds
- **Complete:** stop polling
- Retry with exponential backoff on failure (max 60s)
- Cancellation cleanup

### Pre-Match Experience

Before the match starts, `CricketScoreBanner` shows:
- Team names, match time countdown ("Starts in 2h 34m")
- Bet 365 odds
- Venue name + city

Below the banner, `PreMatchInfo` shows:
- Squads — two-column layout, both teams, player roles as badges
- Head-to-head record
- Venue details

Once status changes from `"pre"` to `"live"`, `PreMatchInfo` is replaced by the full live experience (ball-by-ball, scorecard, match info bar). Transition is automatic via polled data.

## Files Changed

### New Files
- `backend/cricket.py` — ESPN API fetching, parsing, caching, team resolution
- `backend/models.py` — Add cricket Pydantic models (CricketGameData, CricketTeam, Innings, BallEvent, etc.)
- `frontend/src/components/CricketScoreBanner.jsx`
- `frontend/src/components/BallByBallFeed.jsx`
- `frontend/src/components/CricketScorecard.jsx`
- `frontend/src/components/CricketMatchInfo.jsx`
- `frontend/src/components/CricketPreMatch.jsx`
- `frontend/src/app/market/[id]/cricket-page-client.jsx`
- `frontend/src/hooks/useCricketData.js`

### Modified Files
- `backend/app.py` — Add `/api/market/{condition_id}/cricket` endpoint
- `frontend/src/app/market/[id]/page.jsx` — Add cricket tag detection + SSR fetch + routing to CricketPageClient
- `frontend/src/lib/api.js` — Add `fetchCricketData()` function

## Out of Scope (Future)
- Other cricket leagues (BBL, CPL, international matches)
- Additional odds sources (The Odds API, Betfair Exchange)
- Win probability model comparison vs Polymarket price
- Player profile links
- Wagon wheel / pitch map visualizations
