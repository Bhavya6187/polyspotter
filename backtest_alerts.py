#!/usr/bin/env python3
"""
Backtest the most recent 1000 polybot-generated alerts that hit *resolved*
markets, and dump per-alert metrics + raw debugging context to a JSONL file.

For each resolved alert we record:
  - The original alert (composite_score, signals, trades, tags, LLM verdict).
  - A current wallet-profile snapshot for the alerting wallet.
  - The market's final state (outcomes, outcomePrices, winning outcome).
  - Per-trade backtest results (won, copy-trade pnl, roi, direction match).
  - Alert-level rollups across the trades.

Source: hosted backend at $BACKTEST_API_BASE (default https://api.polyspotter.com).
Resolution: Gamma `closed=true` OR any outcomePrice >= 0.99.

See docs/superpowers/specs/2026-05-09-backtest-alerts-design.md for the full design.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import requests

from gamma_cache import get_market_by_condition

DEFAULT_API_BASE = "https://api.polyspotter.com"
RESOLVED_PRICE_THRESHOLD = 0.99
LOST_PRICE_THRESHOLD = 0.01
PER_PAGE = 100  # backend caps at 100
RETRY_ATTEMPTS = 3
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Backend HTTP
# ---------------------------------------------------------------------------
def _request_json(session: requests.Session, url: str, *, params: dict | None = None) -> dict | list | None:
    """GET with retry. Returns parsed JSON, or None for 404."""
    last_err: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = session.get(url, params=params, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            if resp.status_code == 404:
                return None
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {RETRY_ATTEMPTS} attempts: {last_err}")


def fetch_alerts_page(session: requests.Session, api_base: str, page: int) -> list[dict]:
    data = _request_json(
        session,
        f"{api_base}/api/alerts",
        params={"page": page, "per_page": PER_PAGE, "min_score": 0},
    )
    return data["alerts"] if isinstance(data, dict) else []


def fetch_alert_detail(session: requests.Session, api_base: str, alert_id: int) -> dict | None:
    return _request_json(session, f"{api_base}/api/alerts/{alert_id}")


def fetch_wallet_profile(session: requests.Session, api_base: str, wallet: str) -> dict | None:
    """Wallet profile via /api/wallets/{wallet}. Returns None on 404."""
    return _request_json(session, f"{api_base}/api/wallets/{wallet.lower()}")


# ---------------------------------------------------------------------------
# Market resolution
# ---------------------------------------------------------------------------
def _parse_json_field(market: dict, key: str) -> list:
    raw = market.get(key, "[]")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def get_market_resolution(condition_id: str) -> dict | None:
    """Look up market resolution state from Gamma.

    Returns a dict with: closed, outcomes, final_prices, winning_outcome,
    resolved (bool indicating whether the market should be included).
    Returns None if Gamma has no record of the market.
    """
    market = get_market_by_condition(condition_id)
    if not market:
        return None

    outcomes = [str(o) for o in _parse_json_field(market, "outcomes")]
    raw_prices = _parse_json_field(market, "outcomePrices")
    final_prices: list[float] = []
    for p in raw_prices:
        try:
            final_prices.append(float(p))
        except (TypeError, ValueError):
            final_prices.append(0.0)

    closed = bool(market.get("closed"))
    any_extreme = any(p >= RESOLVED_PRICE_THRESHOLD for p in final_prices)
    resolved = closed or any_extreme

    winning_outcome: str | None = None
    if outcomes and final_prices and len(outcomes) == len(final_prices):
        for o, p in zip(outcomes, final_prices):
            if p >= RESOLVED_PRICE_THRESHOLD:
                winning_outcome = o
                break

    return {
        "closed": closed,
        "outcomes": outcomes,
        "final_prices": final_prices,
        "winning_outcome": winning_outcome,
        "resolved": resolved,
    }


# ---------------------------------------------------------------------------
# Per-trade and per-alert backtest math
# ---------------------------------------------------------------------------
def _final_price_for_trade(trade: dict, market_state: dict) -> float | None:
    """Find the final price of the trade's held outcome, or None."""
    outcomes = market_state["outcomes"]
    final_prices = market_state["final_prices"]
    if not outcomes or len(outcomes) != len(final_prices):
        return None
    target = (trade.get("outcome") or "").strip()
    if not target:
        return None
    for o, p in zip(outcomes, final_prices):
        if o.strip().lower() == target.lower():
            return p
    return None


def _backtest_trade(trade: dict, market_state: dict) -> dict:
    """Compute won / pnl_usd / roi / direction_match for a single trade."""
    side = (trade.get("side") or "").upper()
    entry = float(trade.get("price") or 0)
    size = float(trade.get("size") or 0)
    usd_value = float(trade.get("usd_value") or 0)
    final_price = _final_price_for_trade(trade, market_state)

    won: bool | None
    pnl_usd: float
    direction_match: bool
    roi: float

    if final_price is None:
        won = None
        pnl_usd = 0.0
        roi = 0.0
        direction_match = False
    else:
        if side == "BUY":
            pnl_usd = size * (final_price - entry)
            direction_match = final_price > entry
            if final_price >= RESOLVED_PRICE_THRESHOLD:
                won = True
            elif final_price <= LOST_PRICE_THRESHOLD:
                won = False
            else:
                won = None
        elif side == "SELL":
            pnl_usd = size * (entry - final_price)
            direction_match = final_price < entry
            if final_price <= LOST_PRICE_THRESHOLD:
                won = True
            elif final_price >= RESOLVED_PRICE_THRESHOLD:
                won = False
            else:
                won = None
        else:
            won = None
            pnl_usd = 0.0
            direction_match = False

        roi = (pnl_usd / usd_value) if usd_value > 0 else 0.0

    return {
        "transaction_hash": trade.get("transaction_hash"),
        "outcome": trade.get("outcome"),
        "side": side,
        "entry_price": entry,
        "final_price": final_price,
        "won": won,
        "pnl_usd": pnl_usd,
        "roi": roi,
        "direction_match": direction_match,
    }


def _aggregate_backtest(per_trade: list[dict], total_usd: float) -> dict:
    """Roll up per-trade results into alert-level metrics."""
    if not per_trade:
        return {
            "trades_won_pct": 0.0,
            "copy_trade_pnl_usd": 0.0,
            "copy_trade_roi": 0.0,
            "price_direction_match_pct": 0.0,
            "per_trade_results": [],
        }

    decided = [r for r in per_trade if r["won"] is not None]
    trades_won_pct = (
        sum(1 for r in decided if r["won"]) / len(decided) if decided else 0.0
    )
    pnl = sum(r["pnl_usd"] for r in per_trade)
    roi = (pnl / total_usd) if total_usd > 0 else 0.0
    direction_match_pct = sum(1 for r in per_trade if r["direction_match"]) / len(per_trade)

    return {
        "trades_won_pct": trades_won_pct,
        "copy_trade_pnl_usd": pnl,
        "copy_trade_roi": roi,
        "price_direction_match_pct": direction_match_pct,
        "per_trade_results": per_trade,
    }


# ---------------------------------------------------------------------------
# Wallet profile shaping
# ---------------------------------------------------------------------------
_WALLET_PROFILE_KEYS = (
    "wallet",
    "total_positions",
    "closed_positions",
    "wins",
    "losses",
    "total_pnl",
    "total_invested",
    "avg_win_price",
    "win_rate",
    "current_streak",
    "times_flagged",
)


def _shape_wallet_profile(profile: dict | None) -> dict | None:
    if not profile:
        return None
    return {k: profile.get(k) for k in _WALLET_PROFILE_KEYS}


# ---------------------------------------------------------------------------
# Build one JSONL row from a backend alert detail
# ---------------------------------------------------------------------------
def build_jsonl_row(detail: dict, market_state: dict, wallet_profile: dict | None) -> dict:
    """Translate a backend AlertDetail dict into our JSONL schema."""
    trades = detail.get("trades", []) or []
    per_trade = [_backtest_trade(t, market_state) for t in trades]
    total_usd_at_risk = sum(float(t.get("usd_value") or 0) for t in trades)
    backtest = _aggregate_backtest(per_trade, total_usd_at_risk)

    return {
        "alert_id": detail["id"],
        "alert_type": detail.get("alert_type"),
        "scanned_at": detail.get("scanned_at"),
        "created_at": detail.get("created_at"),
        "composite_score": detail.get("composite_score"),
        "tags": detail.get("tags") or [],
        "market_title": detail.get("market_title"),
        "condition_id": detail.get("condition_id"),
        "event_slug": detail.get("event_slug"),
        "end_date": detail.get("end_date"),
        "wallet": detail.get("wallet"),
        "total_usd": detail.get("total_usd"),
        "trade_count": detail.get("trade_count"),
        "cluster_headline": detail.get("cluster_headline"),
        "signals": detail.get("signals") or [],
        "trades": trades,
        "llm": {
            "headline": detail.get("llm_headline"),
            "summary": detail.get("llm_summary"),
            "bullets": detail.get("llm_bullets") or [],
            "copy_action": detail.get("llm_copy_action") or {},
        },
        "wallet_profile": _shape_wallet_profile(wallet_profile),
        "market_state": {
            "closed": market_state["closed"],
            "outcomes": market_state["outcomes"],
            "final_prices": market_state["final_prices"],
            "winning_outcome": market_state["winning_outcome"],
        },
        "backtest": backtest,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run_backtest(api_base: str, limit: int, scan_cap: int, out_path: str) -> None:
    session = requests.Session()
    print(f"[*] Backtest source: {api_base}")
    print(f"[*] Target resolved alerts: {limit}")
    print(f"[*] Scan cap: {scan_cap}")
    print(f"[*] Output: {out_path}")
    print()

    scanned = 0
    kept = 0
    skipped_unresolved = 0
    skipped_no_market = 0
    errored = 0
    page = 1
    wallet_cache: dict[str, dict | None] = {}

    pnl_total = 0.0
    roi_sum = 0.0
    win_rate_sum = 0.0
    win_rate_count = 0
    strategy_in_winners: Counter = Counter()
    strategy_in_losers: Counter = Counter()

    with open(out_path, "w") as fh:
        while kept < limit and scanned < scan_cap:
            try:
                page_alerts = fetch_alerts_page(session, api_base, page)
            except RuntimeError as e:
                print(f"[ERROR] page {page}: {e}", file=sys.stderr)
                break
            if not page_alerts:
                print(f"[*] Reached end of alerts at page {page}")
                break

            for alert_summary in page_alerts:
                if kept >= limit or scanned >= scan_cap:
                    break
                scanned += 1
                alert_id = alert_summary.get("id")
                cid = alert_summary.get("condition_id")
                if not cid:
                    skipped_no_market += 1
                    continue

                try:
                    state = get_market_resolution(cid)
                except Exception as e:
                    print(f"[WARN] alert {alert_id}: gamma lookup failed: {e}", file=sys.stderr)
                    errored += 1
                    continue

                if not state:
                    skipped_no_market += 1
                    continue
                if not state["resolved"]:
                    skipped_unresolved += 1
                    continue

                try:
                    detail = fetch_alert_detail(session, api_base, alert_id)
                except RuntimeError as e:
                    print(f"[WARN] alert {alert_id}: detail fetch failed: {e}", file=sys.stderr)
                    errored += 1
                    continue
                if not detail:
                    errored += 1
                    continue

                wallet = detail.get("wallet")
                wallet_profile = None
                if wallet:
                    if wallet not in wallet_cache:
                        try:
                            wallet_cache[wallet] = fetch_wallet_profile(session, api_base, wallet)
                        except RuntimeError as e:
                            print(f"[WARN] wallet {wallet}: profile fetch failed: {e}", file=sys.stderr)
                            wallet_cache[wallet] = None
                    wallet_profile = wallet_cache[wallet]

                row = build_jsonl_row(detail, state, wallet_profile)
                fh.write(json.dumps(row, default=str) + "\n")
                fh.flush()
                kept += 1

                bt = row["backtest"]
                pnl_total += bt["copy_trade_pnl_usd"]
                roi_sum += bt["copy_trade_roi"]
                if any(r["won"] is not None for r in bt["per_trade_results"]):
                    win_rate_sum += bt["trades_won_pct"]
                    win_rate_count += 1
                strategies = [s["strategy"] for s in row["signals"]]
                won_overall = bt["trades_won_pct"] >= 0.5
                bucket = strategy_in_winners if won_overall else strategy_in_losers
                for s in set(strategies):
                    bucket[s] += 1

                if kept % 25 == 0 or kept == limit:
                    print(
                        f"  Scanned {scanned} | Kept {kept} | "
                        f"Unresolved {skipped_unresolved} | No-market {skipped_no_market} | "
                        f"Errors {errored}",
                        flush=True,
                    )

            page += 1

    _print_summary(
        kept=kept,
        scanned=scanned,
        skipped_unresolved=skipped_unresolved,
        skipped_no_market=skipped_no_market,
        errored=errored,
        pnl_total=pnl_total,
        roi_sum=roi_sum,
        win_rate_sum=win_rate_sum,
        win_rate_count=win_rate_count,
        strategy_in_winners=strategy_in_winners,
        strategy_in_losers=strategy_in_losers,
        out_path=out_path,
    )


def _print_summary(
    *,
    kept: int,
    scanned: int,
    skipped_unresolved: int,
    skipped_no_market: int,
    errored: int,
    pnl_total: float,
    roi_sum: float,
    win_rate_sum: float,
    win_rate_count: int,
    strategy_in_winners: Counter,
    strategy_in_losers: Counter,
    out_path: str,
) -> None:
    print()
    print("=" * 72)
    print("  Backtest summary")
    print("=" * 72)
    print(f"  Scanned alerts:              {scanned}")
    print(f"  Resolved (kept in JSONL):    {kept}")
    print(f"  Skipped unresolved:          {skipped_unresolved}")
    print(f"  Skipped (no Gamma record):   {skipped_no_market}")
    print(f"  Errors:                      {errored}")
    print()
    if kept > 0:
        print(f"  Total copy-trade PnL:        ${pnl_total:,.2f}")
        print(f"  Mean copy-trade ROI:         {roi_sum / kept:.3f}")
        if win_rate_count > 0:
            print(f"  Mean trades-won pct:         {win_rate_sum / win_rate_count:.3f}")
        print()
        print("  Strategy presence (winning vs. losing alerts):")
        all_strategies = sorted(set(strategy_in_winners) | set(strategy_in_losers))
        for s in all_strategies:
            w = strategy_in_winners.get(s, 0)
            l = strategy_in_losers.get(s, 0)
            total = w + l
            win_pct = (w / total) if total else 0
            print(f"    {s:32s}  win {w:>4} | loss {l:>4} | win-rate {win_pct:.2%}")
    print()
    print(f"  Output: {out_path}")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--limit", type=int, default=1000,
                        help="target number of resolved alerts to keep (default 1000)")
    parser.add_argument("--scan-cap", type=int, default=5000,
                        help="max alerts to scan from the backend before stopping (default 5000)")
    parser.add_argument("--out", default="backtest_alerts.jsonl",
                        help="output JSONL path (default backtest_alerts.jsonl)")
    parser.add_argument("--api-base", default=None,
                        help="backend base URL (default $BACKTEST_API_BASE or "
                             f"{DEFAULT_API_BASE})")
    args = parser.parse_args()

    api_base = args.api_base or os.environ.get("BACKTEST_API_BASE", DEFAULT_API_BASE)
    run_backtest(api_base.rstrip("/"), args.limit, args.scan_cap, args.out)


if __name__ == "__main__":
    main()
