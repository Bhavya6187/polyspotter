"""
Pydantic models for API request/response serialization.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


# -- Ingest models (what polybot POSTs) ----------------------------------------

class TradeIn(BaseModel):
    transaction_hash: str
    wallet: str
    condition_id: str | None = None
    outcome: str | None = None
    side: str | None = None
    usd_value: float = 0
    size: float | None = None
    price: float | None = None
    trade_timestamp: datetime | None = None


class SignalIn(BaseModel):
    strategy: str
    severity: float
    headline: str


class CopyAction(BaseModel):
    outcome: str = ""
    side: str = ""
    entry_price: float = 0
    max_price: float = 0


class AlertIn(BaseModel):
    alert_type: str = "composite"
    composite_score: float
    tags: list[str] = []
    market_title: str | None = None
    condition_id: str | None = None
    event_slug: str | None = None
    market_url: str | None = None
    market_image: str | None = None
    market_description: str | None = None
    wallet: str | None = None
    total_usd: float = 0
    trade_count: int = 1
    cluster_headline: str | None = None
    end_date: datetime | None = None
    game_start_time: datetime | None = None
    event_end_estimate: datetime | None = None
    llm_headline: str | None = None
    llm_summary: str | None = None
    llm_bullets: list[str] = []
    llm_copy_action: CopyAction | dict | None = None
    scanned_at: datetime | None = None
    dedup_key: str | None = None
    trades: list[TradeIn] = []
    signals: list[SignalIn] = []


class WalletProfileIn(BaseModel):
    wallet: str
    total_positions: int | None = None
    closed_positions: int | None = None
    wins: int | None = None
    losses: int | None = None
    total_pnl: float | None = None
    total_invested: float | None = None
    avg_win_price: float | None = None
    win_rate: float | None = None
    times_flagged: int | None = None
    first_seen_at: datetime | None = None
    current_streak: int | None = None


class PriceCandleIn(BaseModel):
    condition_id: str
    token_id: str
    outcome: str | None = None
    t: float
    p: float


class PriceCandleOut(BaseModel):
    t: float
    p: float


class ThesisMarket(BaseModel):
    condition_id: str
    market_title: str
    outcome: str
    side: str
    usd_value: float = 0
    entry_price: float = 0


class ThesisIn(BaseModel):
    wallet: str
    event_slug: str
    thesis_headline: str | None = None
    markets: list[ThesisMarket] = []
    total_usd: float = 0
    composite_score: float = 0


class ThesisOut(BaseModel):
    id: int
    wallet: str
    event_slug: str
    thesis_headline: str | None = None
    markets: list[dict] = []
    total_usd: float = 0
    composite_score: float = 0
    win_rate: float | None = None
    total_pnl: float | None = None
    total_invested: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IngestPayload(BaseModel):
    alerts: list[AlertIn] = []
    wallet_profiles: list[WalletProfileIn] = []
    price_candles: list[PriceCandleIn] = []
    theses: list[ThesisIn] = []


# -- Response models -----------------------------------------------------------

class SignalOut(BaseModel):
    strategy: str
    severity: float
    headline: str


class TradeOut(BaseModel):
    transaction_hash: str
    wallet: str
    condition_id: str | None = None
    outcome: str | None = None
    side: str | None = None
    usd_value: float = 0
    size: float | None = None
    price: float | None = None
    trade_timestamp: datetime | None = None


class AlertOut(BaseModel):
    id: int
    alert_type: str
    composite_score: float
    tags: list[str] = []
    market_title: str | None = None
    condition_id: str | None = None
    event_slug: str | None = None
    market_url: str | None = None
    market_image: str | None = None
    market_description: str | None = None
    wallet: str | None = None
    total_usd: float
    trade_count: int
    cluster_headline: str | None = None
    end_date: datetime | None = None
    llm_headline: str | None = None
    llm_summary: str | None = None
    llm_bullets: list[str] = []
    llm_copy_action: CopyAction | None = None
    scanned_at: datetime | None = None
    created_at: datetime | None = None
    win_rate: float | None = None
    total_pnl: float | None = None
    total_invested: float | None = None


class AlertDetail(AlertOut):
    trades: list[TradeOut] = []
    signals: list[SignalOut] = []


class WalletProfileOut(BaseModel):
    wallet: str
    total_positions: int | None = None
    closed_positions: int | None = None
    wins: int | None = None
    losses: int | None = None
    total_pnl: float | None = None
    total_invested: float | None = None
    avg_win_price: float | None = None
    win_rate: float | None = None
    times_flagged: int | None = None
    first_seen_at: datetime | None = None
    updated_at: datetime | None = None
    current_streak: int | None = None


class WalletRecentAlert(BaseModel):
    id: int
    market_title: str | None = None
    composite_score: float = 0
    total_usd: float = 0
    llm_headline: str | None = None
    created_at: datetime | None = None
    condition_id: str | None = None


class WalletBet(BaseModel):
    market_title: str | None = None
    condition_id: str | None = None
    won: bool | None = None
    outcome: str | None = None
    entry_price: float | None = None
    resolution_price: float | None = None
    pnl_usd: float | None = None
    total_usd: float | None = None
    resolved_at: datetime | None = None


class WalletProfileDetailOut(WalletProfileOut):
    recent_alerts: list[WalletRecentAlert] = []
    bet_history: list[WalletBet] = []


class PaginatedAlerts(BaseModel):
    alerts: list[AlertOut]
    total: int
    page: int
    per_page: int


class MarketGroup(BaseModel):
    condition_id: str
    market_title: str | None = None
    market_url: str | None = None
    market_image: str | None = None
    event_slug: str | None = None
    end_date: datetime | None = None
    total_usd: float = 0
    alert_count: int = 0
    max_score: float = 0
    tags: list[str] = []
    scanned_at: datetime | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    seo_summary: str | None = None
    seo_faqs: list[dict] | None = None
    alerts: list[AlertOut] = []


class PaginatedMarkets(BaseModel):
    markets: list[MarketGroup]
    total: int
    total_alerts: int = 0
    page: int
    per_page: int


class SpotlightAlert(BaseModel):
    id: int
    market_title: str | None = None
    condition_id: str | None = None
    event_slug: str | None = None
    composite_score: float = 0
    total_usd: float = 0
    end_date: datetime | None = None
    llm_headline: str | None = None
    llm_summary: str | None = None
    wallet_count: int = 0
    best_win_rate: float | None = None
    best_total_pnl: float | None = None
    current_price: float | None = None
    price_change_24h: float | None = None
    candles: list[PriceCandleOut] = []
    llm_copy_action: dict | None = None


# -- Live market data (proxied from Polymarket CLOB/Gamma APIs) ----------------

class OutcomePrice(BaseModel):
    name: str
    token_id: str
    price: float  # current midpoint (0.00–1.00)

class LiveMarketData(BaseModel):
    condition_id: str
    outcomes: list[OutcomePrice] = []
    volume_24h: float | None = None
    liquidity: float | None = None
    description: str | None = None
    image: str | None = None  # market image URL from Gamma API
    spread: float | None = None  # bid-ask spread in cents for leading outcome


# -- Price history (proxied from CLOB API) ------------------------------------

class PricePoint(BaseModel):
    t: int  # unix timestamp
    p: float  # price 0.00–1.00

class PriceHistoryData(BaseModel):
    condition_id: str
    token_id: str
    outcome: str
    history: list[PricePoint] = []


# -- Market holders (from Polymarket Data API + wallet_profiles) ---------------

class HolderEntry(BaseModel):
    wallet: str
    position_size: float  # USD value
    outcome: str
    side: str  # "long" or "short"
    win_rate: float | None = None
    total_pnl: float | None = None
    total_invested: float | None = None

class MarketHoldersData(BaseModel):
    condition_id: str
    holders: list[HolderEntry] = []


# -- Basketball game data (proxied from NBA CDN + ESPN APIs) --------------------

class GameTeam(BaseModel):
    tricode: str
    name: str
    city: str
    score: int = 0
    record: str | None = None
    quarter_scores: list[int] = []

class SpreadInfo(BaseModel):
    display: str          # e.g. "LAC -17.5"
    value: float          # e.g. -17.5
    team: str             # tricode of favored team

class MoneylineInfo(BaseModel):
    home: str             # e.g. "+800"
    away: str             # e.g. "-1350"

class GameOdds(BaseModel):
    provider: str = "DraftKings"
    spread: SpreadInfo | None = None
    over_under: float | None = None
    moneyline: MoneylineInfo | None = None

class WinProbability(BaseModel):
    home: float = 0.5
    away: float = 0.5

class GamePlay(BaseModel):
    id: int
    clock: str
    period: int
    text: str
    away_score: int = 0
    home_score: int = 0
    type: str = ""        # "2pt", "3pt", "freethrow", "foul", "timeout", "turnover", "rebound", "substitution"
    team: str = ""        # tricode
    scoring: bool = False

class BoxScorePlayer(BaseModel):
    name: str
    position: str = ""
    starter: bool = False
    minutes: str = "0:00"
    points: int = 0
    rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    fg: str = "0-0"       # "made-attempted"
    three_pt: str = "0-0"
    ft: str = "0-0"
    plus_minus: int = 0

class TeamBoxScore(BaseModel):
    team: str             # tricode
    players: list[BoxScorePlayer] = []

class GameBoxScore(BaseModel):
    home: TeamBoxScore
    away: TeamBoxScore

class InjuryEntry(BaseModel):
    team: str
    player: str
    status: str           # "Out", "Doubtful", "Questionable", "Probable"
    detail: str = ""

class GameSeasonSeries(BaseModel):
    home_wins: int = 0
    away_wins: int = 0
    total_games: int = 0

class TeamStats(BaseModel):
    """Season averages and recent form for a team."""
    avg_points: float | None = None
    avg_points_against: float | None = None
    field_goal_pct: float | None = None
    three_point_pct: float | None = None
    avg_rebounds: float | None = None
    avg_assists: float | None = None
    avg_blocks: float | None = None
    avg_steals: float | None = None
    streak: str | None = None           # e.g. "W3", "L1"
    last_ten: str | None = None         # e.g. "7-3"

class TeamLeader(BaseModel):
    """A team's stat leader in a given category."""
    category: str                       # "pointsPerGame", "assistsPerGame", "reboundsPerGame"
    display_category: str = ""          # "PPG", "APG", "RPG"
    player: str
    value: str                          # "29.3"
    headshot: str | None = None

class LastFiveGame(BaseModel):
    """A single result from a team's last 5 games."""
    opponent: str                       # tricode
    at_vs: str = ""                     # "@" or "vs"
    result: str = ""                    # "W" or "L"
    score: str = ""                     # "113-110"

class PreGameTeamData(BaseModel):
    """Pre-game stats bundle for one team."""
    stats: TeamStats | None = None
    leaders: list[TeamLeader] = []
    last_five: list[LastFiveGame] = []
    record_home: str | None = None      # "28-9"
    record_away: str | None = None      # "21-15"

class Predictor(BaseModel):
    """ESPN matchup predictor win percentages."""
    home_pct: float = 50.0
    away_pct: float = 50.0

class GameData(BaseModel):
    game_id: str
    espn_game_id: str | None = None
    league: str = "nba"   # "nba" or "ncaa"
    status: str = "pre"   # "pre", "live", "final"
    clock: str = ""
    period: int = 0
    period_label: str = ""
    game_time: str | None = None        # ISO datetime for scheduled tip-off
    home: GameTeam
    away: GameTeam
    odds: GameOdds | None = None
    win_probability: WinProbability | None = None
    predictor: Predictor | None = None
    plays: list[GamePlay] = []
    box_score: GameBoxScore | None = None
    injuries: list[InjuryEntry] = []
    season_series: GameSeasonSeries | None = None
    home_pregame: PreGameTeamData | None = None
    away_pregame: PreGameTeamData | None = None
    venue: str | None = None
    broadcast: str | None = None


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


# -- Articles ----------------------------------------------------------------

class ArticleOut(BaseModel):
    """Full article payload returned to the frontend article page."""
    run_id: str
    event_slug: str
    published_date: str        # ISO YYYY-MM-DD
    headline: str
    subhead: str
    body_markdown: str
    cover_alt_text: str | None = None
    alert_ids: list[int]
    posted_url: str | None = None
    has_cover: bool


class ArticleListItem(BaseModel):
    """Single entry in GET /api/articles, used by the sitemap."""
    run_id: str
    event_slug: str
    published_date: str
    headline: str
