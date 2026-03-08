"""
Strategy: flag large bets placed by newly created wallets.

A wallet is considered "new" if its Gamma-API profile was created fewer
than WALLET_AGE_DAYS ago (or has no profile at all).

Tracks flagged wallets in the database so repeat offenders are escalated
with higher severity on subsequent runs.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta

import requests

from detection_strategies import DetectionStrategy, Signal
import config
from db import (
    get_flagged_wallet_stats,
    get_wallet_pnl_summary,
    record_flagged_trade_event,
    record_flagged_wallet,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GAMMA_API = "https://gamma-api.polymarket.com"
WALLET_AGE_DAYS = 30
PROFILE_LOOKUP_DELAY = 0.25  # seconds between profile lookups

# ---------------------------------------------------------------------------
# Wallet profile cache:  address -> (created_at, profile dict)
# ---------------------------------------------------------------------------
_wallet_cache: dict[str, tuple[datetime | None, dict]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_wallet_profile(address: str) -> tuple[datetime | None, dict]:
    """Look up a wallet's public profile on the Gamma API.
    Results are cached."""
    short = f"{address[:8]}...{address[-6:]}"
    if address in _wallet_cache:
        if config.VERBOSE:
            print(f"    [cache hit] {short}")
        return _wallet_cache[address]

    if config.VERBOSE:
        print(f"    [lookup] Fetching profile for {short} ...")
    time.sleep(PROFILE_LOOKUP_DELAY)

    try:
        resp = requests.get(
            f"{GAMMA_API}/public-profile",
            params={"address": address},
            timeout=10,
        )
        if resp.status_code == 404:
            print(f"    [lookup] {short} — no profile found (treating as new)")
            _wallet_cache[address] = (None, {})
            return (None, {})
        resp.raise_for_status()
        profile = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] Profile lookup failed for {address}: {e}", file=sys.stderr)
        _wallet_cache[address] = (None, {})
        return (None, {})

    created_str = profile.get("createdAt")
    created_at = None
    if created_str:
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    pseudonym = profile.get("pseudonym", "anonymous")
    age = wallet_age_str(created_at)
    if config.VERBOSE:
        print(f"    [lookup] {short} — \"{pseudonym}\", age: {age}")
    _wallet_cache[address] = (created_at, profile)
    return (created_at, profile)


def is_new_wallet(created_at: datetime | None) -> bool:
    """Return True if the wallet was created within WALLET_AGE_DAYS, or if
    we have no creation date (no profile = potentially very new)."""
    if created_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=WALLET_AGE_DAYS)
    return created_at >= cutoff


def wallet_age_str(created_at: datetime | None) -> str:
    """Human-readable wallet age."""
    if created_at is None:
        return "unknown (no profile)"
    delta = datetime.now(timezone.utc) - created_at
    days = delta.days
    hours = delta.seconds // 3600
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {(delta.seconds % 3600) // 60}m"


def format_alert(trade: dict, created_at: datetime | None, profile: dict) -> str:
    """Format a human-readable console alert."""
    ts = trade.get("timestamp", 0)
    trade_time = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    wallet = trade.get("proxyWallet", "???")
    short_wallet = f"{wallet[:8]}...{wallet[-6:]}"
    pseudonym = trade.get("pseudonym") or profile.get("pseudonym") or "—"
    tx_hash = trade.get("transactionHash", "")
    short_tx = f"{tx_hash[:10]}..." if tx_hash else "—"

    usd = trade.get("_usd_value", trade.get("size", 0) * trade.get("price", 0))

    lines = [
        "",
        "=" * 72,
        "  NEW WALLET LARGE BET ALERT",
        "=" * 72,
        f"  Time:       {trade_time}",
        f"  Market:     {trade.get('title', '?')}",
        f"  Outcome:    {trade.get('outcome', '?')} ({trade.get('side', '?')})",
        f"  Size:       {float(trade.get('size', 0)):,.2f} shares @ ${float(trade.get('price', 0)):.4f}",
        f"  USD Value:  ${usd:,.2f}",
        f"  Wallet:     {short_wallet}  ({pseudonym})",
        f"  Wallet Age: {wallet_age_str(created_at)}",
        f"  Tx:         {short_tx}",
        f"  Polygonscan: https://polygonscan.com/address/{wallet}",
        f"  Market Slug: https://polymarket.com/event/{trade.get('eventSlug', '')}",
        "=" * 72,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class NewWalletLargeBetStrategy(DetectionStrategy):
    name = "new_wallet_large_bet"
    description = (
        "Flags large bets placed by wallets younger than "
        f"{WALLET_AGE_DAYS} days. Escalates repeat offenders from DB history."
    )

    def check_trade(self, trade: dict) -> Signal | None:
        wallet = trade.get("proxyWallet", "")
        usd = trade.get("_usd_value", 0)
        title = trade.get("title", "?")
        print(f"  [new_wallet_large_bet] ${usd:,.2f} on \"{title}\"")

        if not wallet:
            print(f"    [skip] No wallet address on this trade")
            return None

        created_at, _profile = get_wallet_profile(wallet)

        if is_new_wallet(created_at):
            age = wallet_age_str(created_at)
            print(f"    >>> ALERT: New wallet detected!")

            # Base severity scales with how new the wallet is
            if created_at is None:
                severity = 3.5
            else:
                delta = (datetime.now(timezone.utc) - created_at).days
                if delta < 7:
                    severity = 3.5
                elif delta < 14:
                    severity = 2.5
                else:
                    severity = 1.5

            # Only increment flag counters if this specific trade hasn't
            # been flagged before (prevents double-counting on overlapping scans)
            cid = trade.get("conditionId", "")
            trade_ts = trade.get("timestamp", 0)
            is_new_flag = record_flagged_trade_event(wallet, cid, trade_ts, float(usd))
            if is_new_flag:
                flag_stats = record_flagged_wallet(wallet, float(usd))
            else:
                flag_stats = get_flagged_wallet_stats(wallet) or {
                    "times_flagged": 1,
                    "total_usd_flagged": float(usd),
                    "first_flagged_at": "",
                    "last_flagged_at": "",
                }
            headline = f"New wallet ({age})"

            if flag_stats["times_flagged"] > 1:
                repeat_bonus = min(2.0, flag_stats["times_flagged"] * 0.5)
                severity = min(7.0, severity + repeat_bonus)
                headline += (
                    f" — REPEAT x{flag_stats['times_flagged']} "
                    f"(${flag_stats['total_usd_flagged']:,.0f} total flagged)"
                )
                print(f"    >>> REPEAT OFFENDER: flagged {flag_stats['times_flagged']} times, "
                      f"${flag_stats['total_usd_flagged']:,.0f} total")

            # Cross-reference with P&L data: a "new" wallet that already
            # has many positions or high profitability is very suspicious
            pnl = get_wallet_pnl_summary(wallet)
            if pnl["total_positions"] > 5:
                severity = min(7.0, severity + 1.0)
                headline += f", {pnl['total_positions']} positions already"
            if pnl["closed_positions"] >= 3 and pnl["total_pnl"] > 0:
                severity = min(7.0, severity + 0.5)
                headline += f", ${pnl['total_pnl']:+,.0f} P&L"

            return Signal(
                strategy=self.name,
                severity=severity,
                headline=headline,
                trade=trade,
                condition_id=trade.get("conditionId", ""),
            )
        else:
            age = wallet_age_str(created_at)

            # Even if the wallet isn't "new" anymore, check if it was
            # previously flagged — could be a wallet that aged out
            prior_stats = get_flagged_wallet_stats(wallet)
            if prior_stats and prior_stats["times_flagged"] >= 2:
                if config.VERBOSE:
                    print(f"    [note] Wallet is {age} old but was previously flagged "
                          f"{prior_stats['times_flagged']} times")
                return Signal(
                    strategy=self.name,
                    severity=1.0,
                    headline=(
                        f"Previously flagged wallet ({age} old), "
                        f"flagged {prior_stats['times_flagged']}x historically"
                    ),
                    trade=trade,
                    condition_id=trade.get("conditionId", ""),
                )

            if config.VERBOSE:
                print(f"    [ok] Wallet is {age} old — not flagged")
            return None
