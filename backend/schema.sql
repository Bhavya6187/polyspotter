-- Polybot Backend PostgreSQL Schema
-- Stores composite alerts produced by the local polybot scanner

-- alerts: one row per composite alert (a wallet+market+run grouping)
CREATE TABLE IF NOT EXISTS alerts (
    id              SERIAL PRIMARY KEY,
    alert_type      TEXT NOT NULL DEFAULT 'composite',  -- 'composite' or 'cluster'
    composite_score DOUBLE PRECISION NOT NULL,

    -- market info
    market_title    TEXT,
    condition_id    TEXT,
    event_slug      TEXT,
    market_url      TEXT,

    -- wallet (primary wallet for composite, NULL for cluster)
    wallet          TEXT,

    -- aggregate trade info
    total_usd       DOUBLE PRECISION NOT NULL DEFAULT 0,
    trade_count     INTEGER NOT NULL DEFAULT 1,

    -- cluster-specific
    cluster_headline TEXT,

    -- timestamps
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- when polybot produced this
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- dedup: same wallet+market+scan window shouldn't create duplicates
    dedup_key       TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_alerts_score ON alerts(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_scanned ON alerts(scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_wallet ON alerts(wallet);
CREATE INDEX IF NOT EXISTS idx_alerts_event ON alerts(event_slug);

-- alert_trades: individual trades that belong to an alert
CREATE TABLE IF NOT EXISTS alert_trades (
    id              SERIAL PRIMARY KEY,
    alert_id        INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,

    transaction_hash TEXT NOT NULL,
    wallet          TEXT NOT NULL,
    condition_id    TEXT,
    outcome         TEXT,
    side            TEXT,           -- 'BUY' or 'SELL'
    usd_value       DOUBLE PRECISION NOT NULL DEFAULT 0,
    size            DOUBLE PRECISION,
    price           DOUBLE PRECISION,
    trade_timestamp TIMESTAMPTZ,

    UNIQUE(alert_id, transaction_hash)
);

CREATE INDEX IF NOT EXISTS idx_alert_trades_alert ON alert_trades(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_trades_wallet ON alert_trades(wallet);

-- alert_signals: detection signals that contributed to an alert
CREATE TABLE IF NOT EXISTS alert_signals (
    id              SERIAL PRIMARY KEY,
    alert_id        INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,

    strategy        TEXT NOT NULL,       -- e.g. 'new_wallet_large_bet'
    severity        DOUBLE PRECISION NOT NULL,
    headline        TEXT NOT NULL,

    UNIQUE(alert_id, strategy, headline)
);

CREATE INDEX IF NOT EXISTS idx_alert_signals_alert ON alert_signals(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_signals_strategy ON alert_signals(strategy);

-- wallet_profiles: cached wallet-level stats pushed by polybot
CREATE TABLE IF NOT EXISTS wallet_profiles (
    wallet          TEXT PRIMARY KEY,
    total_positions INTEGER,
    closed_positions INTEGER,
    wins            INTEGER,
    losses          INTEGER,
    total_pnl       DOUBLE PRECISION,
    total_invested  DOUBLE PRECISION,
    avg_win_price   DOUBLE PRECISION,
    win_rate        DOUBLE PRECISION,
    times_flagged   INTEGER DEFAULT 0,
    first_seen_at   TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
