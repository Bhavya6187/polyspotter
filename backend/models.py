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
