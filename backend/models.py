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

    # Smart-grouping fields populated when /api/alerts/by-market is called
    # with group_events=true. is_event=True rows aggregate alerts across
    # all child markets sharing event_slug and link to /event/[slug];
    # is_event=False rows behave like the legacy condition_id-grouped row.
    is_event: bool = False
    event_title: str | None = None
    event_image: str | None = None
    market_count: int = 1


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
    status: str = "pre"           # "pre", "live", "final"
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


# -- MLB game data (proxied from ESPN Baseball API) ----------------------------

class MLBTeam(BaseModel):
    abbr: str                       # e.g. "NYY"
    name: str                       # e.g. "Yankees"
    city: str = ""                  # e.g. "New York"
    runs: int = 0
    hits: int = 0
    errors: int = 0
    record: str | None = None       # "92-70"

class MLBCount(BaseModel):
    balls: int = 0
    strikes: int = 0
    outs: int = 0

class MLBRunners(BaseModel):
    on_first: bool = False
    on_second: bool = False
    on_third: bool = False

class MLBLinescoreInning(BaseModel):
    inning: int
    home_runs: int = 0
    away_runs: int = 0

class MLBScoringPlay(BaseModel):
    inning: int
    half: str = ""                  # "top" | "bot"
    text: str
    away_score: int = 0
    home_score: int = 0
    team: str = ""                  # abbr of scoring team

class MLBBoxBatter(BaseModel):
    name: str
    position: str = ""
    at_bats: int = 0
    runs: int = 0
    hits: int = 0
    rbi: int = 0
    walks: int = 0
    strikeouts: int = 0
    avg: str = ""

class MLBBoxPitcher(BaseModel):
    name: str
    innings_pitched: str = "0.0"
    hits: int = 0
    runs: int = 0
    earned_runs: int = 0
    walks: int = 0
    strikeouts: int = 0
    era: str = ""

class MLBTeamBox(BaseModel):
    team: str
    batters: list[MLBBoxBatter] = []
    pitchers: list[MLBBoxPitcher] = []

class MLBOdds(BaseModel):
    provider: str = "DraftKings"
    home_ml: str | None = None      # "+105"
    away_ml: str | None = None
    run_line: str | None = None     # "-1.5"
    total: float | None = None      # 8.5

class MLBVenue(BaseModel):
    name: str
    city: str = ""

class MLBWeather(BaseModel):
    temperature: int | None = None
    condition: str = ""             # "Clear", "Partly cloudy"
    wind: str = ""                  # "8 mph SW"

class MLBProbablePitcher(BaseModel):
    name: str
    era: str = ""
    record: str = ""                # "12-7"

class MLBHeadToHead(BaseModel):
    home_wins: int = 0
    away_wins: int = 0
    total: int = 0

class MLBGameData(BaseModel):
    game_id: str
    espn_game_id: str | None = None
    status: str = "pre"             # "pre" | "live" | "final"
    game_time: str | None = None    # ISO datetime for scheduled first pitch
    inning: int = 0                 # 1-9+, 0 when pre
    half: str = ""                  # "top" | "bot" | "mid" | "end"
    count: MLBCount | None = None
    runners: MLBRunners | None = None
    home: MLBTeam
    away: MLBTeam
    venue: MLBVenue | None = None
    weather: MLBWeather | None = None
    attendance: int | None = None
    broadcast: str | None = None
    probable_home: MLBProbablePitcher | None = None
    probable_away: MLBProbablePitcher | None = None
    odds: MLBOdds | None = None
    linescore: list[MLBLinescoreInning] = []
    scoring_plays: list[MLBScoringPlay] = []
    home_box: MLBTeamBox | None = None
    away_box: MLBTeamBox | None = None
    current_pitcher: str = ""
    current_batter: str = ""
    head_to_head: MLBHeadToHead | None = None


# -- NHL game data (proxied from ESPN Hockey API) ------------------------------

class NHLTeam(BaseModel):
    abbr: str
    name: str
    city: str = ""
    score: int = 0
    record: str | None = None

class NHLPowerPlay(BaseModel):
    on_team: str = ""               # abbr of team on power play, "" if none
    seconds_left: int = 0

class NHLScoringEvent(BaseModel):
    period: int
    time: str = ""                  # "12:34" remaining
    team: str
    scorer: str
    assists: list[str] = []
    type: str = ""                  # "EV", "PP", "SH", "EN", "PEN"
    is_gwg: bool = False

class NHLPenalty(BaseModel):
    period: int
    time: str = ""
    team: str
    player: str
    infraction: str
    minutes: int = 2

class NHLGoalieLine(BaseModel):
    name: str
    team: str
    saves: int = 0
    shots_against: int = 0

class NHLTeamStatsLive(BaseModel):
    team: str
    shots: int = 0
    faceoff_pct: float | None = None
    hits: int = 0
    pp_summary: str = ""            # e.g. "1/3"
    pk_summary: str = ""            # e.g. "2/2"

class NHLTeamSeasonStats(BaseModel):
    pp_pct: float | None = None
    pk_pct: float | None = None
    gf_per_game: float | None = None
    ga_per_game: float | None = None
    last_ten: str | None = None     # "7-2-1"

class NHLOdds(BaseModel):
    provider: str = "DraftKings"
    home_ml: str | None = None
    away_ml: str | None = None
    puck_line: str | None = None
    total: float | None = None

class NHLVenue(BaseModel):
    name: str
    city: str = ""

class NHLHeadToHead(BaseModel):
    home_wins: int = 0
    away_wins: int = 0
    total: int = 0

class NHLGameData(BaseModel):
    game_id: str
    espn_game_id: str | None = None
    status: str = "pre"
    game_time: str | None = None
    period: str = ""                # "P1", "P2", "P3", "OT", "SO", "" pre
    clock: str = ""                 # "12:34"
    power_play: NHLPowerPlay | None = None
    home: NHLTeam
    away: NHLTeam
    venue: NHLVenue | None = None
    broadcast: str | None = None
    attendance: int | None = None
    odds: NHLOdds | None = None
    scoring_summary: list[NHLScoringEvent] = []
    penalties: list[NHLPenalty] = []
    team_stats_live: list[NHLTeamStatsLive] = []
    home_team_season: NHLTeamSeasonStats | None = None
    away_team_season: NHLTeamSeasonStats | None = None
    goalies: list[NHLGoalieLine] = []
    head_to_head: NHLHeadToHead | None = None


# -- Soccer game data (proxied from ESPN Soccer API; EPL/UCL/World Cup) --------

class SoccerTeam(BaseModel):
    abbr: str                       # e.g. "ARS", or 3-letter country code
    name: str                       # "Arsenal" / "Brazil"
    city: str = ""
    score: int = 0
    record: str | None = None       # "12-3-5"
    crest_url: str | None = None
    form: str | None = None         # last-5 result string e.g. "WWDLW", optional

class SoccerGoal(BaseModel):
    minute: str = ""                # "67'" or "45+2'"
    team: str                       # abbr
    scorer: str
    assist: str = ""
    type: str = ""                  # "regular" | "penalty" | "own goal" | "free kick"

class SoccerCard(BaseModel):
    minute: str = ""
    team: str
    player: str
    color: str                      # "yellow" | "red" | "second yellow"

class SoccerSub(BaseModel):
    minute: str = ""
    team: str
    on: str                         # player coming on
    off: str                        # player coming off

class SoccerStats(BaseModel):
    """Live match stats for one team."""
    team: str
    possession_pct: float | None = None
    shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    fouls: int = 0
    offsides: int = 0

class SoccerLineupPlayer(BaseModel):
    name: str
    number: int | None = None
    position: str = ""
    is_starter: bool = True

class SoccerLineup(BaseModel):
    team: str
    formation: str = ""             # "4-3-3"
    starters: list[SoccerLineupPlayer] = []
    bench: list[SoccerLineupPlayer] = []

class SoccerOdds(BaseModel):
    provider: str = "Bet 365"
    home_odds: str | None = None
    draw_odds: str | None = None
    away_odds: str | None = None

class SoccerVenue(BaseModel):
    name: str
    city: str = ""

class SoccerHeadToHead(BaseModel):
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0
    total: int = 0

class SoccerAggregate(BaseModel):
    home: int = 0
    away: int = 0
    leg: int = 1                    # 1 or 2

class SoccerPenShootout(BaseModel):
    home_score: int = 0
    away_score: int = 0
    sequence: list[str] = []        # ["ARS-G", "MCI-M", ...] G=goal M=miss

class SoccerGameData(BaseModel):
    game_id: str
    espn_game_id: str | None = None
    competition: str                # "EPL" | "UCL" | "World Cup"
    competition_round: str = ""     # "Group F · MD3" / "Quarterfinal — 1st Leg"
    league_id: str = ""             # "eng.1" / "uefa.champions" / "fifa.world"
    status: str = "pre"
    game_time: str | None = None
    minute: str = ""                # "67'" | "HT" | "FT" | "ET" | "PEN"
    home: SoccerTeam
    away: SoccerTeam
    aggregate: SoccerAggregate | None = None
    pen_shootout: SoccerPenShootout | None = None
    venue: SoccerVenue | None = None
    referee: str | None = None
    attendance: int | None = None
    odds: SoccerOdds | None = None
    goals: list[SoccerGoal] = []
    cards: list[SoccerCard] = []
    subs: list[SoccerSub] = []
    match_stats: list[SoccerStats] = []
    lineups: list[SoccerLineup] = []
    head_to_head: SoccerHeadToHead | None = None


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


# -- Events ------------------------------------------------------------------

class EventTag(BaseModel):
    id: str | None = None
    label: str
    slug: str | None = None


class EventOut(BaseModel):
    """Event metadata cached from Gamma /events?slug=."""
    slug: str
    gamma_event_id: str | None = None
    title: str | None = None
    description: str | None = None
    image: str | None = None
    icon: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    tags: list[EventTag] = []
    seo_title: str | None = None
    seo_description: str | None = None
    seo_summary: str | None = None
    seo_faqs: list[dict] = []


class EventMarketSummary(BaseModel):
    """One child market within an event, with our aggregate signal stats."""
    condition_id: str
    market_title: str | None = None
    market_image: str | None = None
    end_date: datetime | None = None
    alert_count: int = 0
    total_usd: float = 0
    max_score: float = 0


class EventStats(BaseModel):
    total_markets: int = 0
    total_alerts: int = 0
    total_usd: float = 0
    max_composite_score: float = 0
    latest_alert_at: datetime | None = None


class EventTopWallet(BaseModel):
    wallet: str
    total_usd_in_event: float = 0
    n_markets: int = 0
    n_alerts: int = 0
    win_rate: float | None = None
    total_pnl: float | None = None


class EventRelatedArticle(BaseModel):
    run_id: str
    published_date: str
    headline: str


class EventDetail(BaseModel):
    """Full payload for GET /api/event/{slug}."""
    event: EventOut
    markets: list[EventMarketSummary] = []
    stats: EventStats
    top_alerts: list[AlertOut] = []
    top_wallets: list[EventTopWallet] = []
    related_thesis: ThesisOut | None = None
    related_article: EventRelatedArticle | None = None


class EventListItem(BaseModel):
    """One row in GET /api/events — sitemap and index pages."""
    slug: str
    title: str | None = None
    image: str | None = None
    end_date: datetime | None = None
    n_markets: int = 0
    n_alerts: int = 0
    total_usd: float = 0
    tags: list[str] = []
    last_alert_at: datetime | None = None


class PaginatedEvents(BaseModel):
    events: list[EventListItem]
    total: int
    page: int
    per_page: int


# -- Scoreboard (grading engine) ---------------------------------------------

class ScoreboardWindow(BaseModel):
    wins: int
    losses: int
    hit_rate: float
    copy_return_pct: float


class ScoreboardRecentCall(BaseModel):
    market_title: str | None = None
    outcome: str
    won: bool
    return_pct: float
    event_slug: str | None = None
    resolved_at: datetime


class ScoreboardResponse(BaseModel):
    window_days: int
    window: ScoreboardWindow
    all_time: ScoreboardWindow
    recent: list[ScoreboardRecentCall]
