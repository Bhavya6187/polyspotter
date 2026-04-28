"""
Hourly "story" bot for PolySpotter.

Fetches the last 3 hours of alerts from Railway Postgres, researches them using
five tools (SQLite / Postgres / Gamma API / Data API / CLOB API), and writes an
engaging 3-5 tweet thread — not an alert recap but a short, specific story about
what a sharp bettor is doing and why it matters.

Five agent tools:
    - query_sqlite(sql)             — read-only SELECT against polybot.db
    - query_postgres(sql)           — read-only SELECT against Railway Postgres
    - call_gamma(path, params)      — GET against gamma-api.polymarket.com (markets, events)
    - call_data_api(path, params)   — GET against data-api.polymarket.com (trades)
    - call_clob(path, params)       — GET against clob.polymarket.com (price history + book)

Run via cron (once per hour):
    python storybot/storybot.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from typing import Any

import requests
from openai import OpenAI

import compressor
from bot_utils import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    GAMMA_BASE_URL,
    MAX_SEED_ALERTS,
    MODEL,
    QUERY_TIMEOUT_SECONDS,
    SETTLED_PRICE_THRESHOLD,
    _accumulate_usage,
    _compact_alert_for_picker,
    fetch_seed_alerts,
    log,
    query_postgres,
    query_sqlite,
)
from tweet_utils import (
    TWEET_MAX_CHARS,
    TWEET_URL_CHARS,
    _BANNED_TWEET_PHRASES,
    _POLYSPOTTER_URL_RE,
    _URL_RE,
    _build_twitter_client,
    _tweet_length,
    record_tweet,
)
from style_rules import STYLE_RULES_A, STYLE_RULES_B, STYLE_RULES_C


STORYBOT_DRY_RUN = os.environ.get("STORYBOT_DRY_RUN", "false").lower() == "true"

RESPONSE_CAP_BYTES = 12288   # 12 KB per tool response
MAX_TOOL_CALLS = 22
MAX_ITERATIONS = 20

GAMMA_PATH_ALLOWLIST = ("/markets", "/events")

DATA_API_BASE_URL = "https://data-api.polymarket.com"
DATA_API_PATH_ALLOWLIST = ("/trades",)

CLOB_BASE_URL = "https://clob.polymarket.com"
CLOB_PATH_ALLOWLIST = ("/prices-history", "/book")


# --- Gamma / Data API / CLOB tools ------------------------------------------

_MARKET_FIELDS_KEEP = (
    "id", "conditionId", "slug", "question",
    "outcomes", "outcomePrices",
    "volume", "volumeNum", "volume24hr", "volume1wk",
    "liquidity", "liquidityNum",
    "startDate", "endDate", "endDateIso", "gameStartTime",
    "bestBid", "bestAsk", "lastTradePrice", "spread",
    "oneHourPriceChange", "oneDayPriceChange",
    "oneWeekPriceChange", "oneMonthPriceChange",
    "clobTokenIds",
    "active", "closed", "archived", "negRisk",
    "groupItemTitle", "line", "sportsMarketType",
)

_EVENT_FIELDS_KEEP = (
    "id", "slug", "title", "ticker",
    "startDate", "endDate", "eventDate", "startTime",
    "volume", "volume24hr", "liquidity",
    "active", "closed", "archived", "negRisk",
)


_SIBLING_MARKET_FIELDS = (
    "conditionId", "slug", "question",
    "groupItemTitle", "line", "sportsMarketType",
    "volume24hr", "lastTradePrice", "bestBid", "bestAsk",
    "active", "closed",
)


def _slim_market(m: dict) -> dict:
    out = {k: m[k] for k in _MARKET_FIELDS_KEEP if k in m}
    evts = m.get("events")
    if isinstance(evts, list):
        out["events"] = [
            {k: e.get(k) for k in ("id", "slug", "title", "endDate") if k in e}
            for e in evts if isinstance(e, dict)
        ]
    return out


def _slim_market_sibling(m: dict) -> dict:
    """Tighter shape for markets nested inside an event response. Caller can
    fetch full detail with /markets?condition_ids=… for any market that matters."""
    return {k: m[k] for k in _SIBLING_MARKET_FIELDS if k in m}


def _slim_event(e: dict) -> dict:
    out = {k: e[k] for k in _EVENT_FIELDS_KEEP if k in e}
    tags = e.get("tags")
    if isinstance(tags, list):
        out["tags"] = [
            {k: t.get(k) for k in ("id", "label", "slug") if k in t}
            for t in tags if isinstance(t, dict)
        ]
    markets = e.get("markets")
    if isinstance(markets, list):
        out["markets"] = [_slim_market_sibling(m) for m in markets if isinstance(m, dict)]
    return out


def _slim_gamma_response(path: str, data: Any) -> Any:
    """Strip verbose fields (descriptions, series, clobRewards, eventMetadata
    prose, etc.) from Gamma /markets and /events responses. Keeps the
    tradeable fields the storybot actually uses."""
    if "/tags" in path:
        return data
    if path.startswith("/markets"):
        if isinstance(data, list):
            return [_slim_market(m) if isinstance(m, dict) else m for m in data]
        if isinstance(data, dict):
            return _slim_market(data)
    if path.startswith("/events"):
        if isinstance(data, list):
            return [_slim_event(e) if isinstance(e, dict) else e for e in data]
        if isinstance(data, dict):
            return _slim_event(data)
    return data


def _slim_clob_book(data: Any) -> Any:
    """Cap /book responses to top 20 levels per side (by best price)."""
    if not isinstance(data, dict):
        return data
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    out = dict(data)
    out["bids"] = sorted(bids, key=lambda b: float(b.get("price", 0)), reverse=True)[:20]
    out["asks"] = sorted(asks, key=lambda a: float(a.get("price", 0)))[:20]
    if len(bids) > 20 or len(asks) > 20:
        out["original_depth"] = {"bids": len(bids), "asks": len(asks)}
    return out


def _summarize_prices_history(data: Any) -> Any:
    """Prepend a `summary` dict (first/last/min/max price + delta + n_points)
    to /prices-history responses so the model doesn't have to scan the series
    to make a price-move claim."""
    if not isinstance(data, dict):
        return data
    history = data.get("history") or []
    if not history:
        return data
    prices = [pt["p"] for pt in history if isinstance(pt, dict) and "p" in pt]
    if not prices:
        return data
    first_p = history[0].get("p")
    last_p = history[-1].get("p")
    return {
        "summary": {
            "first_t": history[0].get("t"),
            "first_p": first_p,
            "last_t": history[-1].get("t"),
            "last_p": last_p,
            "min_p": min(prices),
            "max_p": max(prices),
            "abs_change": round((last_p or 0) - (first_p or 0), 6),
            "n_points": len(history),
        },
        "history": history,
    }


def call_gamma(path: str, params: dict | None = None) -> Any:
    """Generic GET to gamma-api.polymarket.com. Allowlist: /markets, /events."""
    if not path.startswith("/") or ".." in path or "//" in path:
        raise ValueError("path not allowed")
    if not any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in GAMMA_PATH_ALLOWLIST):
        raise ValueError(f"path must start with one of {GAMMA_PATH_ALLOWLIST}")
    resp = requests.get(f"{GAMMA_BASE_URL}{path}", params=params or None,
                        timeout=QUERY_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return _slim_gamma_response(path, resp.json())


def call_data_api(path: str, params: dict | None = None) -> Any:
    """Generic GET to data-api.polymarket.com. Allowlist: /trades."""
    if not path.startswith("/") or ".." in path or "//" in path:
        raise ValueError("path not allowed")
    if not any(path == p or path.startswith(p + "?") for p in DATA_API_PATH_ALLOWLIST):
        raise ValueError(f"path must be one of {DATA_API_PATH_ALLOWLIST}")
    resp = requests.get(f"{DATA_API_BASE_URL}{path}", params=params or None,
                        timeout=QUERY_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def call_clob(path: str, params: dict | None = None) -> Any:
    """Generic GET to clob.polymarket.com. Allowlist: /prices-history, /book."""
    if not path.startswith("/") or ".." in path or "//" in path:
        raise ValueError("path not allowed")
    if not any(path == p or path.startswith(p + "?") for p in CLOB_PATH_ALLOWLIST):
        raise ValueError(f"path must be one of {CLOB_PATH_ALLOWLIST}")
    resp = requests.get(f"{CLOB_BASE_URL}{path}", params=params or None,
                        timeout=QUERY_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    if path.startswith("/book"):
        return _slim_clob_book(data)
    if path.startswith("/prices-history"):
        return _summarize_prices_history(data)
    return data


# --- Tool envelope + dispatch -----------------------------------------------

def _envelope(data: Any = None, *, error: str | None = None) -> dict:
    """Build a tool-response envelope. Truncates to RESPONSE_CAP_BYTES when JSON-serialized."""
    if error is not None:
        return {"error": error}
    serialized = json.dumps(data, default=str)
    truncated = False
    if len(serialized) > RESPONSE_CAP_BYTES:
        truncated = True
        if isinstance(data, list):
            trimmed = list(data)
            while trimmed and len(json.dumps(trimmed, default=str)) > RESPONSE_CAP_BYTES:
                trimmed.pop()
            data = trimmed
        else:
            data = serialized[: RESPONSE_CAP_BYTES - 1] + "…"
    out = {"data": data}
    if truncated:
        out["truncated"] = True
    return out


_BACKENDS = {
    "sqlite": query_sqlite,
    "postgres": query_postgres,
    "gamma": call_gamma,
    "data_api": call_data_api,
    "clob": call_clob,
}


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "query",
        "description": (
            "Fetch data for research. Describe WHAT you want in `intent` (plain "
            "language) — a downstream builder model picks the backend (scanner "
            "SQLite, Railway Postgres, Gamma API, or CLOB API), writes the exact "
            "SQL / HTTP call, runs it, and returns a compressed result. "
            "Numeric/identifier-heavy payloads are compressed deterministically "
            "(values preserved byte-for-byte); free-text payloads may be summarized. "
            "Response shape: {\"data\": <payload>, \"backend\": \"...\", \"compression\": \"...\"}."
        ),
        "parameters": {
            "type": "object",
            "required": ["intent"],
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "Natural-language description of the data you want. Name "
                        "specific wallets, condition_ids, event_slugs, token_ids, "
                        "time windows when they apply. Example: 'wallet_profiles row "
                        "for 0xabc…', 'all alert_trades on alert_id=42 sorted by "
                        "trade_timestamp desc', 'CLOB price history for token X over "
                        "the last hour at 1-min fidelity'."
                    ),
                },
                "hint": {
                    "type": "string",
                    "description": (
                        "Optional extra context for the builder (e.g. which backend "
                        "you think holds the data, or a specific column name)."
                    ),
                },
            },
        },
    }},
]


def _derive_scope(chosen_alerts: list[dict]) -> dict:
    """Build the session scope dict from the picked alerts.

    The picker contract guarantees all chosen_alerts share one event_slug.
    Cluster alerts have wallet=None — those are skipped from the wallets list
    (the full cluster membership only appears once research pulls alert_trades).
    """
    event_slug = chosen_alerts[0].get("event_slug")
    condition_ids = sorted({a["condition_id"] for a in chosen_alerts if a.get("condition_id")})
    alert_ids = [a["id"] for a in chosen_alerts if a.get("id") is not None]
    wallets = sorted({a["wallet"] for a in chosen_alerts if a.get("wallet")})
    scope: dict = {}
    if event_slug:
        scope["event_slug"] = event_slug
    if condition_ids:
        scope["condition_ids"] = condition_ids
    if alert_ids:
        scope["alert_ids"] = alert_ids
    if wallets:
        scope["wallets"] = wallets
    return scope


_HEX_ID_RE = re.compile(r"\A0x[0-9a-fA-F]+\Z")


def _hex_in_clause(values: list[str]) -> str | None:
    """SQL `IN (...)` literal for hex-id values, with strict hex validation.
    Returns None when no value is valid (caller should skip the query)."""
    safe = [f"'{v}'" for v in values if isinstance(v, str) and _HEX_ID_RE.fullmatch(v)]
    return "(" + ",".join(safe) + ")" if safe else None


PREFETCH_WALLET_CAP = 50           # cap distinct wallets fed to phase-2 IN-clauses
PREFETCH_EVENT_HISTORY_CAP = 200   # cap rows in wallet_event_history


def _run_task(name: str, spec: tuple) -> tuple:
    t0 = time.monotonic()
    try:
        backend = spec[0]
        if backend in ("postgres", "sqlite"):
            data = _BACKENDS[backend](spec[1])
        else:
            data = _BACKENDS[backend](spec[1], spec[2] if len(spec) > 2 else None)
        return name, {"ok": True, "data": data,
                      "ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return name, {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                      "ms": int((time.monotonic() - t0) * 1000)}


def _wallets_from_alert_trades(scope_wallets: list[str], alert_trades_data: Any) -> list[str]:
    """Union scope.wallets with distinct wallets in alert_trades, capped to
    PREFETCH_WALLET_CAP by total usd_value across the trades (so we keep the
    wallets most worth profiling)."""
    by_wallet_usd: dict[str, float] = {w: float("inf") for w in scope_wallets or []}
    if isinstance(alert_trades_data, list):
        for t in alert_trades_data:
            if not isinstance(t, dict):
                continue
            w = t.get("wallet")
            if not isinstance(w, str) or not _HEX_ID_RE.fullmatch(w):
                continue
            usd = t.get("usd_value") or 0
            try:
                by_wallet_usd[w] = by_wallet_usd.get(w, 0) + float(usd)
            except (TypeError, ValueError):
                by_wallet_usd.setdefault(w, 0)
    ranked = sorted(by_wallet_usd.items(), key=lambda kv: kv[1], reverse=True)
    return [w for w, _ in ranked[:PREFETCH_WALLET_CAP]]


def prefetch_bundle(scope: dict) -> dict:
    """Two-phase parallel prefetch of the predictable queries derivable from
    `scope`. Returns {item: {"ok": bool, "data"|"error", "ms": int}}.

    Phase 1 (parallel): alert-id-keyed and event/condition-keyed queries.
    Phase 2 (parallel, kicked off the moment alert_trades returns): wallet-keyed
        queries spanning ALL wallets in the picked alerts (named + cluster
        members surfaced by alert_trades).

    Pre-fetching skips one builder-LLM call per query and avoids the
    scope-vs-cluster gap where cluster wallets were previously unknown until
    the orchestrator did its own research.
    """
    import concurrent.futures

    if not scope:
        return {}

    alert_ids = scope.get("alert_ids") or []
    scope_wallets = scope.get("wallets") or []
    cids = scope.get("condition_ids") or []
    ev_slug = scope.get("event_slug")

    phase1: dict[str, tuple] = {}
    if alert_ids:
        ids_csv = ",".join(str(int(x)) for x in alert_ids)
        phase1["alert_trades"] = ("postgres", f"""
            SELECT a.id AS alert_id, a.alert_type, a.total_usd, a.trade_count,
                   a.market_title, a.cluster_headline,
                   t.transaction_hash, t.wallet, t.outcome, t.side,
                   t.usd_value, t.size, t.price, t.trade_timestamp
            FROM alerts a JOIN alert_trades t ON t.alert_id = a.id
            WHERE a.id IN ({ids_csv})
            ORDER BY t.trade_timestamp ASC
        """)
        phase1["tweeted_dedup"] = ("postgres", f"""
            SELECT alert_id, tweet_id, tweeted_at FROM tweeted_alerts
            WHERE alert_id IN ({ids_csv})
        """)
    cid_csv = ",".join(c for c in cids if isinstance(c, str) and _HEX_ID_RE.fullmatch(c))
    if cid_csv:
        phase1["market_meta"] = ("gamma", "/markets", {"condition_ids": cid_csv})
    if ev_slug:
        phase1["event_meta"] = ("gamma", "/events", {"slug": ev_slug})

    if not phase1 and not scope_wallets:
        return {}

    results: dict = {}
    t_start = time.monotonic()
    max_workers = max(len(phase1), 1) + 4   # headroom for phase 2 to share the pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {n: ex.submit(_run_task, n, s) for n, s in phase1.items()}

        # Phase 2 depends on alert_trades (for cluster wallet discovery). If
        # alert_trades isn't queued (no alert_ids) we still run phase 2 against
        # scope.wallets only.
        alert_trades_data: Any = None
        if "alert_trades" in futs:
            _, r = futs["alert_trades"].result()
            results["alert_trades"] = r
            if r.get("ok"):
                alert_trades_data = r["data"]
        all_wallets = _wallets_from_alert_trades(scope_wallets, alert_trades_data)

        if all_wallets:
            wlist = _hex_in_clause(all_wallets)
            phase2: dict[str, tuple] = {
                "wallet_profiles": ("postgres", f"""
                    SELECT wallet, total_positions, closed_positions, wins, losses,
                           total_pnl, total_invested, win_rate, times_flagged,
                           current_streak, first_seen_at, updated_at
                    FROM wallet_profiles WHERE wallet IN {wlist}
                """),
                "wallet_funders": ("sqlite", f"""
                    SELECT wallet, funder, discovered_at
                    FROM wallet_funders WHERE wallet IN {wlist}
                """),
            }
            if ev_slug:
                phase2["wallet_event_history"] = ("sqlite", f"""
                    SELECT wallet, market_title, condition_id, outcome, side,
                           usd_value, price, trade_timestamp
                    FROM wallet_event_history
                    WHERE wallet IN {wlist} AND event_slug = '{ev_slug}'
                    ORDER BY usd_value DESC
                    LIMIT {PREFETCH_EVENT_HISTORY_CAP}
                """)
            for n, s in phase2.items():
                futs[n] = ex.submit(_run_task, n, s)

        # Drain everything still pending (phase 1 leftovers + all of phase 2)
        for name, fut in futs.items():
            if name in results:
                continue
            _, results[name] = fut.result()

    total_ms = int((time.monotonic() - t_start) * 1000)
    log("prefetch_bundle",
        items=list(results.keys()),
        ok=[n for n, r in results.items() if r["ok"]],
        errors={n: r["error"] for n, r in results.items() if not r["ok"]},
        total_ms=total_ms)
    return results


def _make_dispatcher(llm_client, *, usage: dict | None, scope: dict | None = None):
    def dispatch(name: str, args: dict) -> dict:
        if name != "query":
            return _envelope(error=f"unknown tool: {name}")
        intent = args.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return _envelope(error="intent must be a non-empty string")
        hint = args.get("hint") if isinstance(args.get("hint"), str) else None
        try:
            result = compressor.run_query(
                llm_client,
                intent=intent,
                hint=hint,
                model=MODEL,
                backends=_BACKENDS,
                scope=scope,
                usage=usage,
            )
        except Exception as exc:
            return _envelope(error=f"compressor: {type(exc).__name__}: {exc}")

        if result.get("error"):
            return {"error": result["error"]}

        # Final byte cap as defense in depth — compressor should already fit.
        data = result["data"]
        serialized = json.dumps(data, default=str)
        truncated = False
        if len(serialized) > RESPONSE_CAP_BYTES:
            truncated = True
            if isinstance(data, list):
                trimmed = list(data)
                while trimmed and len(json.dumps(trimmed, default=str)) > RESPONSE_CAP_BYTES:
                    trimmed.pop()
                data = trimmed
            else:
                data = serialized[: RESPONSE_CAP_BYTES - 1] + "…"

        out: dict = {
            "data": data,
            "backend": result.get("backend"),
            "compression": result.get("compression"),
        }
        if truncated:
            out["truncated"] = True
        if result.get("router_error"):
            out["router_error"] = result["router_error"]
        if result.get("compress_error"):
            out["compress_error"] = result["compress_error"]
        return out

    return dispatch


# --- System prompt -----------------------------------------------------------

SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service that surfaces
notable bets on Polymarket (whales, sharp wallets, coordinated flow, informed
edge). Every hour, a cron triggers you to look at what sharp money just did
and, when something genuinely merits attention, write an engaging 3-5 tweet
thread that tells the whole story.

## Your job, in order
1. The kickoff user message contains the alert(s) picked by a preceding
   triage pass. When there are multiple, they all share the same event —
   treat them as a single story and look for signal overlap across them
   (wallet_clustering + concentrated_one_sided = coordinated squad;
   timing + win_rate = sharp at the buzzer; composite + cluster alert on
   the same game = multiple angles on one story). Their full fields are
   embedded: `llm_headline`, `llm_summary`, `llm_bullets`,
   `llm_copy_action`, `cluster_headline`, the `signals` array (which
   detection strategies fired, with severity + headline),
   `market_description` (resolution criteria), `tags`, and `seo_summary`.
   No need to re-query for any of that. (`seo_faqs` is NOT embedded —
   query it if you need Q&A-style context.) Already-settled markets
   (closed / UMA-resolving / priced >= {SETTLED_PRICE_THRESHOLD}) have
   been filtered out via Gamma. Sports markets are pre-kickoff only —
   in-progress games are excluded from seeding.
2. RESEARCH. A great thread cites specific, surprising facts the raw
   alerts don't already contain. You'll need several — one per tweet.
   Research all three layers:

   The alerts/market themselves:
     - market_volume_snapshots / orderbook_snapshots → 24h volume + book depth
     - CLOB /prices-history    → canonical price time-series (PREFER this over
                                 price_candles for any price-move claim)
     - alert_trades            → individual trades backing the alert(s)

   The wallet(s) (usually the richest source of surprise):
     - wallet_profiles               → track record, edge, streaks (rollup; PREFETCHED for all wallets)
     - wallet_funders                → part of a shared-funder cluster? (PREFETCHED for all wallets)
     - wallet_event_history          → broader thesis on this event (PREFETCHED for all wallets, top by usd)
     - Data API /trades?user=<wallet> → their recent activity across Polymarket (NOT prefetched)

   The tag / event context:
     - Gamma /events?slug=<event>    → sibling markets, event metadata
     - alerts filtered by tag        → other recent alerts in this vertical
                                       (sports / politics / crypto) — is this
                                       part of a broader pattern or an outlier?
     - wallet_theses                 → cross-market thesis groupings on this event
3. Write the thread.

## What each detection strategy means
The `signals` array on each seed alert (and rows in `alert_signals`) uses
these strategy names. Severity is 0-10; higher = stronger.

- **win_rate_tracking** (1.0-6.0): Wallet has >=75% win rate on 10+
  resolved bets AND beats implied odds by 15%+ (edge-adjusted). These are
  sharp bettors — a proven track record, not luck.
- **new_wallet_large_bet** (1.0-7.0): Wallets <30 days old placing large
  ($3k+) bets. Severity scales with wallet youth; escalated if the
  wallet is also already profitable. Signals informed conviction from a
  fresh account.
- **timing_relative_resolution** (1.0-8.0): Bets placed within 60 min of
  market resolution (short-duration markets like 5-min BTC binaries are
  excluded). "SERIAL TIMER" wallets that repeatedly bet near resolution
  across long-duration markets get heavily escalated — possible
  real-time information edge.
- **low_activity_large_bet** (0.5-4.0): Large bets on thinly-traded
  markets (<$5k 24h vol) or where a single bet is >=50% of 24h volume.
  Someone confident is moving real money into a market others ignore.
- **pre_event_volume_spike** (1.0-4.0): Scan-window volume >=10x the
  normalized average AND >=$10k absolute. A sudden flood into a
  normally quiet market — informed positioning.
- **wallet_clustering** (5.0-8.0): >=2 wallets funded by the same
  Etherscan address (traced via funding history). Severity scales
  logarithmically with cluster size. One actor deploying capital across
  multiple wallets.
- **concentrated_one_sided** (3.5-8.0): >=3 distinct wallets all betting
  the same direction on the same outcome within the scan window,
  totaling >=$5k. Jumps +1.5 if wallets in the cluster share a funder.
  Coordinated directional flow.
- **price_impact** (1.0-5.0): Significant price shift — within-window
  >=15pp, historical breakout >=25pp, or rapid velocity (>=10pp in 5
  min). Thin orderbooks boost severity. Someone is moving the market
  with conviction.
- **correlated_cross_market** (1.5-4.0): Wallet betting across multiple
  markets in the same event (same `event_slug`). Mixed directions =
  hedged thesis (3.0); consistent = directional thesis (1.5). Serial
  cross-market traders (>=3 events) escalate to 4.0.

The `signals` array is attached to every chosen alert, sorted by severity
DESC. Do NOT re-query `alert_signals` for alerts already in the kickoff
— they're already there. The top signal (or the strongest signal across
the group when you got multiple alerts) is usually the heart of the
story — lead the opening tweet with what IT says, not the raw
composite_score.

## The query tool
You have ONE research tool: `query(intent, hint?)`. Describe WHAT you want in
natural language — a downstream builder model chooses the backend (scanner
SQLite, Railway Postgres, Gamma API, or CLOB API), writes the exact SQL / HTTP
call, and runs it. The result is then compressed before reaching you.

Available data sources (reference only — you don't write SQL yourself):
- scanner SQLite (polybot.db) — wallet P&L, clusters, funders, event history, sparklines
- Railway Postgres            — alerts, alert_trades, alert_signals, wallet_profiles, wallet_theses, tweeted_alerts, price_candles
- Gamma API                   — /markets, /events
- Data API                    — /trades (recent trades by wallet or by market)
- CLOB API                    — /prices-history (canonical price series), /book

Compressor behavior:
- Numeric / identifier-heavy payloads are compressed deterministically (top_k,
  filter, project, aggregate) — values are byte-exact.
- Free-text payloads (descriptions, FAQs) may be summarized by an LLM.

Each response arrives as `{{"data": <payload>, "backend": "...", "compression": "..."}}`.
If the payload doesn't answer your intent, re-query with a more specific intent
— don't just repeat the same one. Be specific: name the wallet, condition_id,
event_slug, token_id, alert_id, or time window you need.

The schemas below are for framing good intents. You can reference a specific
column or table name in your intent when useful ("from alert_trades join
alerts, the trades backing alert_id=42 sorted by usd_value desc").

{compressor.SCHEMA_DOCS}

## Thread style (3-5 tweets — this is the engaging part, do not skip)
Build a micro-story across 3-5 tweets posted as a reply chain. Each tweet
must stand on its own AND advance the narrative.

Shape — think setup → turn → payoff, not hook/beat/beat/beat/close.
The single most common failure mode is writing a parallel list of facts
("side A did X, side B did Y, the price moved") and calling it a
thread. That reads like a report. A thread needs a TURN.

- HOOK (tweet 1): One sentence that makes someone stop scrolling.
  Stakes baked in: the track record, the timing asymmetry, the weird
  thing. A hook is NOT a summary of the whole event — don't cram three
  beats into it just because they're all true.
  GOOD hooks (stakes baked in, story in one line):
    "A wallet that's hit 14 of its last 15 bets just loaded $82k on the No"
    "Three wallets funded by the same address quietly piled into UNDER 2.5 in the last 40 minutes"
    "Volume on this market 9x'd in 2 hours — and 73% of it is one wallet taking YES at 0.31"
  BAD hooks (read like SQL output, no stakes for the reader):
    "Over 64m26s pre-tip, 14 wallets pushed $94,199.97 through 15 Sixers-Celtics trades"
    "16 wallets bought $78,131.61 of Spurs from 00:57 to 01:47 UTC"

- BODY (tweets 2 through N-1): Build a narrative turn. Setup → twist →
  consequence. A setup is a picture the reader buys into ("retail
  piled in on the Yankees"). A twist flips it ("then a +$2M lifetime
  wallet showed up on the other side"). A consequence shows what
  happened next ("the price went up and came back 20 cents in half an hour").
  If you can reorder your body tweets without losing meaning, they're
  parallel beats, not a story — rewrite.
  If the strongest story you have is "coordinated buys + volume spike"
  with no real turn, that's usually not a thread. Consider skip.

- PAYOFF (final tweet): Give the reader something they can do or
  watch. A price level that's now the line. A wallet to track. The
  next catalyst. A question the market has to answer. Not just the
  current orderbook state. Followed by 1-2 polyspotter.com deep links
  (see "Links" below). The URL is MANDATORY — if no market/wallet/
  alert/tag page adds anything for the reader, the thread isn't ready;
  return skip. NEVER close with "in bio", "full breakdown", "more at",
  "link below", or equivalent — instant credibility tax.

Characters, not aggregates. When one wallet carries the story, give
them a one-line persona in the tweet that introduces them ("a wallet
that's up $2.4M lifetime", "a 2-day-old account that's already been
flagged 28 times"), then refer back to them across the thread ("that
same guy", "the new wallet"). Don't introduce a third character in the
last tweet — the reader is still mapping the first two.

{STYLE_RULES_A}

## Links (final tweet only)
Build URLs against `https://polyspotter.com`. Prefer the market page —
it's the richest landing surface. Use a wallet link when the story is
primarily about one specific wallet. Use alert / tag only when clearly
more relevant. 1-2 links max in the final tweet.

- market: https://polyspotter.com/market/<slug>
    <slug> = kebab-cased `market_title` (lowercase, non-alnum → single
    dash, trim leading/trailing dashes, max 80 chars) + "-" + first 7
    chars of `condition_id` (i.e. "0x" + 5 hex chars).
    Example: market_title "Will Trump win 2024?" +
    condition_id "0xc5300759dc..." → "will-trump-win-2024-0xc53007"
- wallet: https://polyspotter.com/wallet/<wallet_address>
    (use the full 0x-prefixed address from the alert)
- alert:  https://polyspotter.com/alert/<alert_id>
- tag:    https://polyspotter.com/tag/<tag-slug>
    <tag-slug> = lowercase, whitespace → single dash

All URLs wrap to {TWEET_URL_CHARS} chars regardless of length — don't
shorten them yourself, just paste the full URL.

{STYLE_RULES_B}

{STYLE_RULES_C}

## When to skip
If research reveals the picked alert(s) aren't actually a great story —
track record weaker than the signals suggested, no surprising numbers
beyond what's already in the alert, or the narrative just doesn't hold
up — return decision=skip. Don't force a thread.

## Output format (strict JSON — your final assistant content)
{{
  "decision": "post" | "skip",
  "reason": "one short sentence explaining the pick or the skip",
  "tweets": ["<tweet 1>", "<tweet 2>", ...] | null,   // 3-5 items, each ≤{TWEET_MAX_CHARS} chars, posted as a reply chain
  "alert_ids": [<int>, ...] | null                    // alerts this thread is about (for dedup recording)
}}

When decision=post, `tweets` must have exactly 3, 4, or 5 items and
`alert_ids` must be real IDs from the `alerts` table you saw in tool
responses.

Budget: up to {MAX_TOOL_CALLS} tool calls. If you hit the budget, write the
thread with what you have — do not keep digging.
"""


_BUNDLE_DESCRIPTIONS = {
    "alert_trades":         "Postgres alerts ⨯ alert_trades for the picked alert_ids.",
    "tweeted_dedup":        "Postgres tweeted_alerts rows for the picked alert_ids (empty = none tweeted).",
    "wallet_profiles":      "Postgres wallet_profiles for ALL wallets in alert_trades (named + cluster).",
    "wallet_funders":       "SQLite wallet_funders for ALL wallets in alert_trades.",
    "wallet_event_history": ("SQLite wallet_event_history for ALL wallets in alert_trades, scoped to "
                             f"the picked event_slug; top {PREFETCH_EVENT_HISTORY_CAP} rows by usd_value."),
    "market_meta":          "Gamma /markets?condition_ids=… (current prices, volume, clobTokenIds).",
    "event_meta":           "Gamma /events?slug=… (sibling markets, summary fields only — call /markets for full detail).",
}


def _format_prefetched_block(prefetched: dict) -> str:
    """Render the prefetch_bundle results into a `<prefetched>` block for
    the kickoff message. Failed items are silently dropped — orchestrator
    can fetch on demand."""
    ok_items = {n: r["data"] for n, r in prefetched.items() if r.get("ok")}
    if not ok_items:
        return ""
    lines = [
        "<prefetched>",
        "These queries have already been run for the picked event/alerts/wallets.",
        "Use these values directly — do NOT call `query` to re-fetch them. ",
        "Each item below is keyed by name, with a one-line description.",
        "",
    ]
    for name, data in ok_items.items():
        desc = _BUNDLE_DESCRIPTIONS.get(name, "")
        lines.append(f"## {name} — {desc}")
        lines.append(json.dumps(data, default=str, separators=(",", ":")))
        lines.append("")
    lines.append("</prefetched>")
    return "\n".join(lines) + "\n\n"


def build_kickoff_message(chosen_alerts: list[dict],
                          prefetched: dict | None = None) -> str:
    """Kickoff user message for stage 2: the alert(s) picked upstream.

    `chosen_alerts` is 1+ alerts (all sharing the same `event_slug` when >1).
    `prefetched` (optional) is the output of `prefetch_bundle(scope)` — its
    successful items are embedded as a `<prefetched>` block at the top.
    """
    assert chosen_alerts, "chosen_alerts must be non-empty"
    prefix = _format_prefetched_block(prefetched) if prefetched else ""
    if len(chosen_alerts) == 1:
        payload = json.dumps(chosen_alerts[0], default=str, indent=2)
        return prefix + (
            "A preceding triage pass picked this alert as the best story "
            "for the hour. Research it with the four tools, then write the "
            "thread — or skip if research reveals it's not actually "
            "interesting. Remember: engaging 3-5 tweet story, not alert "
            "recap.\n\n"
            f"chosen_alert:\n{payload}"
        )
    slug = chosen_alerts[0].get("event_slug") or "(unknown event)"
    payload = json.dumps(chosen_alerts, default=str, indent=2)
    return prefix + (
        f"A preceding triage pass picked these {len(chosen_alerts)} alerts "
        f"— all on event '{slug}' — as the best story for the hour. Treat "
        "them as ONE story: look for signal overlap and what they "
        "collectively reveal. Research with the four tools, then write "
        "the thread — or skip if research reveals it's not actually "
        "interesting. Remember: engaging 3-5 tweet story, not alert "
        "recap.\n\n"
        f"chosen_alerts ({len(chosen_alerts)} rows):\n{payload}"
    )


# --- Picker (stage 1) --------------------------------------------------------

PICKER_SYSTEM_PROMPT = f"""You triage the top alerts from the last 3 hours \
for PolySpotter's hourly story bot. Downstream, a researcher model will pick \
up your choice and write a 3-5 tweet thread about it.

You see a compact list of up to {MAX_SEED_ALERTS} alerts (id, composite_score,
signals, headline, market, wallet, $ size, event_slug, tags, timing). Pick the
single best **story** for the hour, or skip if nothing stands out.

A story is usually one event, not one alert. Alerts come in clusters: the
same event may generate a composite alert + a cluster alert, or multiple
wallets may fire on the same market. When that happens, include ALL the
alerts for that event in your pick — the researcher uses them together to
spot signal overlap (e.g. wallet_clustering + concentrated_one_sided =
coordinated squad). Group by `event_slug`.

Favor:
- High-severity signals (wallet_clustering, timing_relative_resolution,
  concentrated_one_sided, new_wallet_large_bet at 5+)
- Events with multiple alerts reinforcing each other
- Specific numeric hooks (large $ size, coordinated flow, sharp timing)
- Surprising / story-worthy angles over generic big bets

Skip if:
- All alerts are small or lack a clear narrative
- Nothing stands out above the noise

Return exactly this JSON and nothing else:
{{"decision": "post" | "skip", "alert_ids": [<int>, ...] | null, \
"reason": "<one short sentence>"}}

When decision=post, `alert_ids` must be 1+ IDs from the list. If more than
one, ALL of them must share the same `event_slug`.
"""


def pick_story(llm_client, seed_alerts: list[dict], *,
               usage: dict | None = None,
               timings: list[dict] | None = None) -> dict:
    """Stage 1: pick the alert(s) that make the hour's story. No tools.

    Returns the raw model JSON ({"decision", "alert_ids", "reason"}). On
    invalid JSON, returns a skip decision with the parse error as reason.
    """
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    t0 = time.monotonic()
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PICKER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=10000,
        reasoning_effort="high",
        response_format={"type": "json_object"},
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if usage is not None:
        _accumulate_usage(usage, response)
    if timings is not None:
        timings.append({"stage": "pick", "ms": elapsed_ms})
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "alert_ids": None,
                "reason": f"picker returned invalid JSON: {exc}"}


def resolve_pick(pick: dict, seed_alerts: list[dict]
                 ) -> tuple[list[dict] | None, str | None]:
    """Map a picker decision onto the seed list. Returns (chosen_alerts, error).

    chosen_alerts is None on error. Enforces: IDs exist in the seed list, and
    multi-alert picks all share the same event_slug.
    """
    ids = pick.get("alert_ids")
    if not isinstance(ids, list) or not ids:
        return None, "alert_ids must be a non-empty list"
    by_id = {a.get("id"): a for a in seed_alerts}
    chosen: list[dict] = []
    for i in ids:
        try:
            aid = int(i)
        except (TypeError, ValueError):
            return None, f"alert_ids must be integers, got {i!r}"
        alert = by_id.get(aid)
        if alert is None:
            return None, f"alert_id {aid} not in seed list"
        chosen.append(alert)
    if len(chosen) > 1:
        slugs = {a.get("event_slug") for a in chosen}
        if len(slugs) != 1 or None in slugs:
            return None, f"multi-alert picks must share one event_slug, got {slugs!r}"
    return chosen, None


# --- Agent loop --------------------------------------------------------------

class AgentError(Exception):
    pass


def _assistant_tool_message(msg) -> dict:
    return {
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in msg.tool_calls
        ],
    }


def run_agent(llm_client, *, chosen_alerts: list[dict],
              on_tool_call=None, transcript: list[dict] | None = None,
              usage: dict | None = None,
              timings: list[dict] | None = None,
              system_prompt: str = SYSTEM_PROMPT,
              kickoff_message: str | None = None,
              json_retry_hint: str | None = None,
              max_tool_calls: int = MAX_TOOL_CALLS,
              max_iterations: int = MAX_ITERATIONS) -> dict:
    """Drive the function-calling loop until the LLM emits final JSON.

    `chosen_alerts` is the 1+ alerts already picked by `pick_story()` (all
    sharing one `event_slug` when >1); they're injected into the kickoff
    user message so the researcher can go straight to digging.

    If `transcript` is provided, every message (system, user, assistant, tool)
    is appended in-place — caller retains the full transcript even if we raise.
    If `usage` is provided, per-request token totals are accumulated in-place
    — caller retains partial usage even if we raise.
    If `timings` is provided, one entry is appended per research iteration
    with LLM + per-tool-call durations.

    `on_tool_call` is called with (name, args, env, elapsed_ms) after each
    tool dispatches.

    `json_retry_hint` overrides the hint appended when the model's first
    attempt at final JSON fails to parse.  When None a generic hint is used
    that does not reference any schema details.
    """
    scope = _derive_scope(chosen_alerts)
    messages: list[dict] = transcript if transcript is not None else []
    messages.append({"role": "system", "content": system_prompt})
    if kickoff_message is None:
        prefetched = prefetch_bundle(scope)
        kickoff_message = build_kickoff_message(chosen_alerts, prefetched=prefetched)
    messages.append({"role": "user", "content": kickoff_message})
    calls_used = 0
    forcing_final = False
    final_json_retries = 0
    dispatch = _make_dispatcher(llm_client, usage=usage, scope=scope)

    for iter_idx in range(max_iterations):
        remaining = max_tool_calls - calls_used
        kwargs = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "temperature": 1,
            "max_completion_tokens": 12000,
        }
        if remaining > 0 and not forcing_final:
            kwargs["tool_choice"] = "auto"
        else:
            kwargs["tool_choice"] = "none"
            kwargs["response_format"] = {"type": "json_object"}

        t_llm = time.monotonic()
        response = llm_client.chat.completions.create(**kwargs)
        llm_ms = int((time.monotonic() - t_llm) * 1000)
        if usage is not None:
            _accumulate_usage(usage, response)
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        iter_timing = {"stage": "research_iter", "iter": iter_idx + 1,
                       "llm_ms": llm_ms, "tool_calls": []}
        if timings is not None:
            timings.append(iter_timing)

        if tool_calls:
            messages.append(_assistant_tool_message(msg))
            dispatched = 0
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    env = _envelope(error=f"bad arguments JSON: {exc}")
                    tool_ms = 0
                else:
                    if not forcing_final and dispatched < remaining:
                        t_tool = time.monotonic()
                        env = dispatch(call.function.name, args)
                        tool_ms = int((time.monotonic() - t_tool) * 1000)
                        dispatched += 1
                    else:
                        env = _envelope(error="tool budget exhausted")
                        tool_ms = 0
                iter_timing["tool_calls"].append({
                    "name": call.function.name,
                    "ms": tool_ms,
                    "error": env.get("error"),
                    "truncated": env.get("truncated", False),
                })
                if on_tool_call is not None:
                    on_tool_call(call.function.name,
                                 args if isinstance(args, dict) else {},
                                 env, tool_ms)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(env, default=str),
                })
            calls_used += dispatched
            if calls_used >= max_tool_calls and not forcing_final:
                forcing_final = True
                messages.append({
                    "role": "user",
                    "content": "Tool budget exhausted. Return your final JSON decision now.",
                })
            continue

        content = msg.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            if final_json_retries >= 1:
                return {
                    "decision": "skip",
                    "reason": f"agent could not produce valid JSON ({exc})",
                    "tweets": None,
                    "alert_ids": None,
                }
            final_json_retries += 1
            messages.append({"role": "assistant", "content": content})
            hint = json_retry_hint or (
                "Respond with exactly one JSON object and nothing else, "
                "matching the schema described in your system prompt."
            )
            messages.append({
                "role": "user",
                "content": "Your previous response was empty or not valid JSON. " + hint,
            })
            forcing_final = True
            continue

    raise AgentError("agent exceeded MAX_ITERATIONS without final JSON")


# --- Validation --------------------------------------------------------------

def validate_decision(decision: dict) -> tuple[bool, str]:
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"
    tweets = decision.get("tweets")
    if not isinstance(tweets, list):
        return False, "tweets must be a list of strings"
    if not 3 <= len(tweets) <= 5:
        return False, f"tweets must have 3-5 items, got {len(tweets)}"
    for i, t in enumerate(tweets):
        if not isinstance(t, str) or not t.strip():
            return False, f"tweets[{i}] must be a non-empty string"
        tlen = _tweet_length(t)
        if tlen > TWEET_MAX_CHARS:
            return False, f"tweets[{i}] length {tlen} exceeds {TWEET_MAX_CHARS}"
        if i != len(tweets) - 1 and _URL_RE.search(t):
            return False, f"tweets[{i}] contains a URL; URLs only allowed in the last tweet"
        lower = t.lower()
        for phrase in _BANNED_TWEET_PHRASES:
            if phrase in lower:
                return False, f"tweets[{i}] contains banned CTA phrase {phrase!r}"
    if not _POLYSPOTTER_URL_RE.search(tweets[-1]):
        return False, "final tweet must contain a polyspotter.com deep link (/market, /wallet, /alert, or /tag)"
    ids = decision.get("alert_ids") or []
    if not isinstance(ids, list) or not ids:
        return False, "alert_ids must be a non-empty list when posting"
    try:
        [int(i) for i in ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {ids!r}"
    return True, ""


# --- Thread posting ----------------------------------------------------------

def post_thread(tweets: list[str], *, twitter_client, dry_run: bool) -> list[str]:
    """Post a reply-chain thread. Returns the list of tweet ids (root first)."""
    if dry_run:
        return [f"dryrun-{uuid.uuid4().hex[:12]}" for _ in tweets]
    tweet_ids: list[str] = []
    reply_to: str | None = None
    for text in tweets:
        kwargs: dict[str, Any] = {"text": text}
        if reply_to:
            kwargs["in_reply_to_tweet_id"] = reply_to
        resp = twitter_client.create_tweet(**kwargs)
        data = getattr(resp, "data", None) or {}
        tweet_id = str(data.get("id") or "")
        if not tweet_id:
            raise RuntimeError(f"create_tweet returned no id: {resp!r}")
        tweet_ids.append(tweet_id)
        reply_to = tweet_id
    return tweet_ids


# --- Dry-run transcript dump -------------------------------------------------

_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")


def _dump_dry_run(run_id: str, transcript: list[dict], *,
                  pick: dict | None = None,
                  decision: dict | None = None, error: str | None = None,
                  usage: dict | None = None,
                  timings: list[dict] | None = None) -> str:
    """Write the full chain (stage-1 pick, stage-2 transcript, final decision,
    per-step timings) to storybot/dry_runs/<run_id>.json."""
    os.makedirs(_DRY_RUN_DIR, exist_ok=True)
    path = os.path.join(_DRY_RUN_DIR, f"{run_id}.json")
    payload = {
        "run_id": run_id,
        "model": MODEL,
        "tweet_max_chars": TWEET_MAX_CHARS,
        "max_tool_calls": MAX_TOOL_CALLS,
        "max_iterations": MAX_ITERATIONS,
        "pick": pick,
        "transcript": transcript,
        "final_decision": decision,
        "error": error,
        "llm_usage": usage or {},
        "timings": timings or [],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


# --- Entrypoint --------------------------------------------------------------

def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    log("run_start", run_id=run_id, dry_run=STORYBOT_DRY_RUN)

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)

    def _on_tool(name: str, args: dict, env: dict, elapsed_ms: int) -> None:
        preview_source = args.get("intent") or args.get("sql") or args.get("path") or ""
        if STORYBOT_DRY_RUN:
            preview = preview_source or json.dumps(args)[:200]
            meta = []
            if env.get("backend"):
                meta.append(f"backend={env['backend']}")
            if env.get("compression"):
                meta.append(f"compression={env['compression']}")
            meta_s = f" [{', '.join(meta)}]" if meta else ""
            status = f"ERROR: {env['error']}" if env.get("error") else \
                     ("ok (truncated)" if env.get("truncated") else "ok")
            print(f"  tool  {name}  ({elapsed_ms} ms){meta_s}\n    {preview}\n    → {status}",
                  flush=True)
        else:
            log("tool_call", run_id=run_id, name=name,
                args_preview=preview_source[:200],
                backend=env.get("backend"),
                compression=env.get("compression"),
                error=env.get("error"), truncated=env.get("truncated", False),
                elapsed_ms=elapsed_ms)

    transcript: list[dict] | None = [] if STORYBOT_DRY_RUN else None
    usage_totals: dict = {}
    timings: list[dict] = []
    pick: dict | None = None
    run_start_t = time.monotonic()

    t_seed = time.monotonic()
    try:
        seed_alerts = fetch_seed_alerts()
    except Exception as exc:
        log("seed_fetch_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    seed_ms = int((time.monotonic() - t_seed) * 1000)
    timings.append({"stage": "seed_fetch", "ms": seed_ms, "count": len(seed_alerts)})
    log("seed_fetched", run_id=run_id, count=len(seed_alerts), elapsed_ms=seed_ms)
    if STORYBOT_DRY_RUN:
        print(f"[dry-run] seeded {len(seed_alerts)} alerts ({seed_ms} ms)", flush=True)

    if not seed_alerts:
        log("skip", run_id=run_id, reason="no alerts in the last 3 hours")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    # Stage 1: pick the story (or skip the hour).
    try:
        pick = pick_story(llm_client, seed_alerts, usage=usage_totals, timings=timings)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("pick_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    pick_ms = next((t["ms"] for t in reversed(timings) if t.get("stage") == "pick"), 0)
    log("pick", run_id=run_id, decision=pick.get("decision"),
        alert_ids=pick.get("alert_ids"), reason=pick.get("reason"),
        elapsed_ms=pick_ms)
    if STORYBOT_DRY_RUN:
        print(
            f"[dry-run] pick: {pick.get('decision')} "
            f"alert_ids={pick.get('alert_ids')} — {pick.get('reason')} "
            f"({pick_ms} ms)",
            flush=True,
        )

    if pick.get("decision") != "post":
        log("llm_usage", run_id=run_id, **usage_totals)
        log("skip", run_id=run_id, reason=pick.get("reason") or "picker chose to skip")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings)
            print(f"[dry-run] transcript → {path}", flush=True)
        return 0

    chosen_alerts, err = resolve_pick(pick, seed_alerts)
    if chosen_alerts is None:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("pick_error", run_id=run_id, error=err, pick=pick)
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"invalid pick: {err}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1

    # Stage 2: research + write.
    try:
        decision = run_agent(
            llm_client, chosen_alerts=chosen_alerts,
            on_tool_call=_on_tool, transcript=transcript,
            usage=usage_totals, timings=timings,
        )
    except AgentError as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("agent_error", run_id=run_id, error=str(exc))
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"AgentError: {exc}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        if STORYBOT_DRY_RUN and transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 error=f"{type(exc).__name__}: {exc}")
            print(f"[dry-run] transcript → {path}", flush=True)
        return 1

    log("llm_usage", run_id=run_id, **usage_totals)

    if STORYBOT_DRY_RUN:
        iters = [t for t in timings if t.get("stage") == "research_iter"]
        tool_total = sum(len(t.get("tool_calls") or []) for t in iters)
        research_ms = sum(t.get("llm_ms", 0) for t in iters) + sum(
            tc.get("ms", 0) for t in iters for tc in t.get("tool_calls") or []
        )
        print(
            f"[dry-run] timings: seed={seed_ms/1000:.2f}s "
            f"pick={pick_ms/1000:.2f}s "
            f"research={research_ms/1000:.2f}s "
            f"({len(iters)} iters, {tool_total} tool calls) "
            f"total={int((time.monotonic() - run_start_t) * 1000)/1000:.2f}s",
            flush=True,
        )
        print(
            f"[dry-run] llm usage: "
            f"prompt={usage_totals.get('prompt_tokens', 0):,} "
            f"completion={usage_totals.get('completion_tokens', 0):,} "
            f"reasoning={usage_totals.get('reasoning_tokens', 0):,} "
            f"cached={usage_totals.get('cached_prompt_tokens', 0):,} "
            f"total={usage_totals.get('total_tokens', 0):,} "
            f"requests={usage_totals.get('requests', 0)}",
            flush=True,
        )
        if transcript is not None:
            path = _dump_dry_run(run_id, transcript, pick=pick,
                                 usage=usage_totals, timings=timings,
                                 decision=decision)
            print(f"[dry-run] transcript → {path}", flush=True)

    ok, err = validate_decision(decision)
    if not ok:
        log("validation_error", run_id=run_id, error=err, decision=decision)
        return 1

    if decision["decision"] == "skip":
        log("skip", run_id=run_id, reason=decision.get("reason"))
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    tweets: list[str] = [t for t in decision["tweets"]]
    alert_ids = [int(i) for i in decision["alert_ids"]]
    thread_text = "\n\n".join(tweets)

    try:
        twitter_client = _build_twitter_client()
        tweet_ids = post_thread(tweets, twitter_client=twitter_client, dry_run=STORYBOT_DRY_RUN)
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    root_tweet_id = tweet_ids[0]
    log("posted", run_id=run_id, tweet_id=root_tweet_id, tweet_ids=tweet_ids,
        alert_ids=alert_ids, tweet_count=len(tweets),
        tweet_lengths=[len(t) for t in tweets])
    for i, t in enumerate(tweets, 1):
        print(f"\n--- Tweet {i}/{len(tweets)} ({len(t)} chars) ---\n{t}", flush=True)
    print("", flush=True)

    if STORYBOT_DRY_RUN:
        log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=root_tweet_id,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    try:
        record_tweet(alert_ids, root_tweet_id, thread_text)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        # Thread is live — still a success.
        log("run_end", run_id=run_id, posted=True, tweet_id=root_tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=root_tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
