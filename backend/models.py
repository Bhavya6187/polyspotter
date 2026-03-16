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


class AlertIn(BaseModel):
    alert_type: str = "composite"
    composite_score: float
    tags: list[str] = []
    market_title: str | None = None
    condition_id: str | None = None
    event_slug: str | None = None
    market_url: str | None = None
    wallet: str | None = None
    total_usd: float = 0
    trade_count: int = 1
    cluster_headline: str | None = None
    end_date: datetime | None = None
    llm_summary: str | None = None
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


class IngestPayload(BaseModel):
    alerts: list[AlertIn] = []
    wallet_profiles: list[WalletProfileIn] = []


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
    wallet: str | None = None
    total_usd: float
    trade_count: int
    cluster_headline: str | None = None
    end_date: datetime | None = None
    llm_summary: str | None = None
    scanned_at: datetime | None = None
    created_at: datetime | None = None


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


class PaginatedAlerts(BaseModel):
    alerts: list[AlertOut]
    total: int
    page: int
    per_page: int
