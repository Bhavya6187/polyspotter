"""
Result pipeline: post-resolution follow-ups for tweets we already shipped.

For each tweet recorded in `tweeted_alerts` whose underlying Polymarket
markets have all resolved, compute the cluster's realized W/L + P&L and
have the LLM compose a short follow-up tweet. The follow-up is printed
to stdout and saved as a `live_runs/result_<tweet_id>.json` artifact;
nothing is posted to Twitter yet — that's a deliberate choice so the
voice/format can be tuned against real outputs first.

Dedup: the artifact file's existence means "we've already produced a
result for this tweet". Re-runs of the script skip it.

Run via cron:
    python storybot/result_pipeline.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

# Make the project root importable so `import db` works when this script
# is run directly (cron / manual run from storybot/), not just under pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

import gamma_cache
from openai import OpenAI

from bot_utils import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    MODEL,
    QUERY_TIMEOUT_SECONDS,
    log,
)

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
_LIVE_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_runs")
_DRY_RUN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dry_runs")
_RUN_OUTPUT_DIR = _DRY_RUN_DIR if DRY_RUN else _LIVE_RUN_DIR

# How far back to look for tweets that might now have a result. Anything
# older than this is treated as "stale, never resolved" and skipped — we'd
# rather miss a 30-day-late result than spam old replies.
RESULT_LOOKBACK_DAYS = 14

# Wait at least this long after posting before considering a result. Keeps
# us from chasing tweets where the kickoff hasn't even happened yet.
RESULT_MIN_AGE_MINUTES = 60


# Curated result selection. We do NOT post every resolved call — we post a
# small, win-weighted set per day, but never hide a big loss (honesty floor),
# because a visibly all-wins record reads as cherry-picked and destroys the
# trust the whole accountability layer exists to build.
RESULT_DAILY_CAP = 2
RESULT_WIN_BIAS = 0.8            # target fraction of posted results that are wins
RESULT_LOSS_NOTABLE_USD = 20000.0  # a loss this big is ALWAYS eligible
RESULT_WASH_BAND = 0.01         # |net_pl| within 1% of invested -> "wash"


def classify_outcome(aggregate: dict) -> str:
    """'cashed' | 'burned' | 'wash' from net P&L vs invested."""
    net = float(aggregate.get("net_pl_usd") or 0.0)
    invested = float(aggregate.get("total_invested_usd") or 0.0)
    if invested > 0 and abs(net) <= RESULT_WASH_BAND * invested:
        return "wash"
    return "cashed" if net > 0 else "burned"


def build_scorecard_data(aggregate: dict, *, event_label: str,
                         outcome_side: str, flagged_days_ago: int) -> dict:
    """Map an aggregate_result() dict to ResultScorecardData for the renderer."""
    verdict = classify_outcome(aggregate).upper()  # CASHED | BURNED | WASH
    return {
        "verdict": verdict,
        "net_pl_usd": float(aggregate.get("net_pl_usd") or 0.0),
        "record_str": f"{int(aggregate.get('n_won') or 0)}-"
                      f"{int(aggregate.get('n_lost') or 0)}",
        "event_label": event_label,
        "outcome_side": outcome_side,
        "flagged_days_ago": int(flagged_days_ago),
    }


def select_results(candidates: list[dict], *, posted_today: list[bool],
                   daily_cap: int = RESULT_DAILY_CAP,
                   win_bias: float = RESULT_WIN_BIAS,
                   loss_notable_usd: float = RESULT_LOSS_NOTABLE_USD) -> list[dict]:
    """Pick which resolved calls to post today.

    candidates: dicts with keys is_win(bool), net_pl_usd(float),
    notability(float >= 0), plus any caller payload (e.g. 'id').
    posted_today: is_win flags already posted this ET day (cap + win-share).

    Rules: wins are always eligible; losses are eligible only if notable
    (>= loss_notable_usd). When a slot is free, force a win if the running
    win share is below win_bias; otherwise take whichever remaining item is
    the bigger story (higher notability). Deterministic.
    """
    slots = max(0, int(daily_cap) - len(posted_today))
    if slots <= 0:
        return []
    wins = sorted([c for c in candidates if c.get("is_win")],
                  key=lambda c: c.get("notability", 0.0), reverse=True)
    losses = sorted(
        [c for c in candidates
         if not c.get("is_win")
         and abs(float(c.get("net_pl_usd") or 0.0)) >= loss_notable_usd],
        key=lambda c: c.get("notability", 0.0), reverse=True)

    selected: list[dict] = []
    posted = list(posted_today)
    wi, li = 0, 0
    while len(selected) < slots and (wi < len(wins) or li < len(losses)):
        nxt_win = wins[wi] if wi < len(wins) else None
        nxt_loss = losses[li] if li < len(losses) else None
        # `share` is the win fraction over today's already-posted results PLUS
        # what we've selected so far this run — i.e. cumulative within the ET
        # day. So once enough wins are banked, the next slot can "afford" a
        # notable loss; a fresh day (empty posted) starts at 0.0 and forces a
        # win first.
        total = len(posted)
        share = (sum(1 for w in posted if w) / total) if total else 0.0
        if nxt_loss is None:
            pick_win = True
        elif nxt_win is None:
            pick_win = False
        elif share < win_bias:
            pick_win = True  # below target -> must add a win
        else:
            pick_win = nxt_win.get("notability", 0.0) >= nxt_loss.get("notability", 0.0)
        if pick_win:
            selected.append(nxt_win); posted.append(True); wi += 1
        else:
            selected.append(nxt_loss); posted.append(False); li += 1
    return selected


# --- Tweet candidates --------------------------------------------------------

def fetch_candidate_tweets() -> list[dict]:
    """Return tweets older than RESULT_MIN_AGE_MINUTES, posted within the
    last RESULT_LOOKBACK_DAYS, grouped by tweet_id, with the alert_ids and
    condition_ids they covered."""
    if not DATABASE_URL:
        log("config_error", error="DATABASE_URL not set")
        return []
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT tweet_id,
                   MAX(tweet_text) AS tweet_text,
                   MAX(tweeted_at) AS tweeted_at,
                   array_agg(DISTINCT alert_id)     AS alert_ids,
                   array_agg(DISTINCT condition_id) AS condition_ids
            FROM tweeted_alerts
            WHERE tweeted_at >= NOW() - INTERVAL %s
              AND tweeted_at <= NOW() - INTERVAL %s
            GROUP BY tweet_id
            ORDER BY MAX(tweeted_at) DESC
            """,
            (f"{RESULT_LOOKBACK_DAYS} days",
             f"{RESULT_MIN_AGE_MINUTES} minutes"),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_alert_trades(alert_ids: list[int]) -> list[dict]:
    """Return all trades for the given alerts. We need (condition_id,
    outcome, side, usd_value, size, price) to compute realized P&L."""
    if not alert_ids:
        return []
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT alert_id, wallet, condition_id, outcome, side,
                   usd_value, size, price
            FROM alert_trades
            WHERE alert_id = ANY(%s)
            """,
            ([int(i) for i in alert_ids],),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_alert_meta(alert_ids: list[int]) -> dict[int, dict]:
    """Return {alert_id: {market_title, event_slug, ...}} for the alerts."""
    if not alert_ids:
        return {}
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, market_title, event_slug, condition_id, wallet
            FROM alerts
            WHERE id = ANY(%s)
            """,
            ([int(i) for i in alert_ids],),
        )
        rows = cur.fetchall()
        cur.close()
        return {int(r["id"]): dict(r) for r in rows}
    finally:
        conn.close()


# --- Resolution --------------------------------------------------------------

def _resolution_for_market(condition_id: str) -> dict | None:
    """Return {closed, winning_outcome, outcomes, prices} for a market, or
    None if the market is not yet resolved or the lookup failed.

    Polymarket binary markets resolve with outcomePrices like ["1","0"] —
    the index whose price == 1 is the winning outcome name from `outcomes`.
    If both prices are 0 or 0.5/0.5 (rare ambiguous resolution), we treat
    it as unresolved and skip.
    """
    market = gamma_cache.get_market_by_condition(condition_id)
    if not market:
        return None
    if not market.get("closed"):
        return None
    raw_outcomes = market.get("outcomes") or "[]"
    raw_prices = market.get("outcomePrices") or "[]"
    try:
        outcomes = (json.loads(raw_outcomes)
                    if isinstance(raw_outcomes, str) else raw_outcomes)
        prices = (json.loads(raw_prices)
                  if isinstance(raw_prices, str) else raw_prices)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    try:
        prices_f = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    # Pick the outcome whose resolution price is 1 (or close to it). If no
    # outcome cleared 0.99, treat as unresolved.
    winners = [(i, p) for i, p in enumerate(prices_f) if p >= 0.99]
    if len(winners) != 1:
        return None
    win_idx, _ = winners[0]
    return {
        "closed": True,
        "winning_outcome": outcomes[win_idx],
        "outcomes": outcomes,
        "prices": prices_f,
        "question": market.get("question"),
    }


# --- P&L --------------------------------------------------------------------

def _compute_trade_pl(trade: dict, won: bool) -> float:
    """Realized P&L for a single BUY trade, given whether the bet won.

    Polymarket shares pay $1 at resolution if correct, $0 otherwise.
      - Won:  payout = size, P&L = size - usd_value
      - Lost: payout = 0,    P&L = -usd_value

    SELL trades (rare in our alerts — we surface BUY-side flow) are
    treated symmetrically: the seller loses money if the position they
    sold ends up winning (they were short the winner). But since our
    detection signals all key off BUY-side flow, treat any non-BUY here
    as zero P&L rather than guessing — better to under-claim than mislead.
    """
    if (trade.get("side") or "").upper() != "BUY":
        return 0.0
    size = float(trade.get("size") or 0.0)
    usd_value = float(trade.get("usd_value") or 0.0)
    if won:
        return size - usd_value
    return -usd_value


def aggregate_result(trades: list[dict],
                     resolutions: dict[str, dict]) -> dict:
    """Compute the cluster's overall outcome.

    Args:
        trades: raw rows from alert_trades.
        resolutions: {condition_id: resolution_dict} for every market the
            tweet covered. Caller must ensure all markets are resolved
            before calling this.

    Returns a summary dict with both per-trade detail and aggregated
    figures the LLM can use to compose a follow-up.
    """
    per_trade: list[dict] = []
    total_invested = 0.0
    total_payout = 0.0
    n_won = 0
    n_lost = 0
    by_market: dict[str, dict] = {}
    for t in trades:
        cid = t.get("condition_id")
        res = resolutions.get(cid or "")
        if not res:
            continue
        outcome = (t.get("outcome") or "").strip()
        winning = (res.get("winning_outcome") or "").strip()
        won = bool(outcome) and outcome.lower() == winning.lower()
        usd_value = float(t.get("usd_value") or 0.0)
        pl = _compute_trade_pl(t, won)
        size = float(t.get("size") or 0.0)
        payout = size if won else 0.0
        total_invested += usd_value
        total_payout += payout
        if won:
            n_won += 1
        else:
            n_lost += 1
        per_trade.append({
            "alert_id": t.get("alert_id"),
            "wallet": t.get("wallet"),
            "condition_id": cid,
            "outcome": outcome,
            "winning_outcome": winning,
            "won": won,
            "usd_value": usd_value,
            "pl": pl,
        })
        m = by_market.setdefault(cid, {
            "winning_outcome": winning,
            "side_bet": outcome,
            "usd_invested": 0.0,
            "pl": 0.0,
            "won": won,
        })
        m["usd_invested"] += usd_value
        m["pl"] += pl

    return {
        "n_trades": len(per_trade),
        "n_won": n_won,
        "n_lost": n_lost,
        "total_invested_usd": total_invested,
        "total_payout_usd": total_payout,
        "net_pl_usd": total_payout - total_invested,
        "per_trade": per_trade,
        "by_market": by_market,
    }


# --- LLM compose ------------------------------------------------------------

SYSTEM_PROMPT_RESULT = """You write short result-update tweets for \
PolySpotter — a service that flags notable Polymarket bets. Earlier we \
posted a tweet about a cluster of bets; that market has now resolved \
and you write the follow-up.

You will receive:
- original_tweet: the tweet we shipped earlier (without the polyspotter URL).
- result: a structured summary of how the bets resolved. Fields:
    - n_won, n_lost: trade-level win/loss counts.
    - total_invested_usd: how much the cluster put in.
    - total_payout_usd: what the winning side cashed (0 if all lost).
    - net_pl_usd: payout minus invested.
    - by_market: per-market breakdown {winning_outcome, side_bet, usd_invested, pl, won}.

## Voice
Same voice as the original: short, factual, scoreboard-clear. NOT smug,
NOT meme-y, NOT analyst-speak. The reader should be able to tell at a
glance whether the sharps cashed or got burned.

## Required structure (2 sentences max)
1. Lead with the result. State who won the market and what the cluster
   was on. Round dollar figures: "$28k", "$6.2k". One sentence.
2. State the realized P&L in plain English: "Cashed +$31k", "Burned -$28k",
   or for split outcomes "Net +$4k across the two markets." One sentence.
3. No link. The scorecard image carries the brand — spend every character on the result.

## Rules
- Keep total under 270 characters. No URL — it would be stripped.
- Do NOT include any URL; links are stripped before posting.
- Reference the original event/team names — the reader should not need
  to remember the prior tweet to follow.
- No hashtags, no emojis, no @mentions.
- Banned phrases: "called it", "told you so", "as predicted", "nailed it",
  "rekt", "ngmi". Stay neutral whether the bet won or lost.
- If the cluster lost, do not soften it ("close one", "tough beat") —
  just state the loss. Credibility comes from honest scoreboarding.
- If net P&L is within +/- 1% of invested (true wash), say "broke even"
  rather than tiny dollar swings.

## Output (strict JSON only)
{
  "tweet": "<link-free result text>"
}
"""


def compose_result_tweet(llm_client, original_tweet: str, result: dict) -> str:
    """One LLM call to produce the follow-up tweet text. Returns the raw
    string the model emitted; caller is responsible for any further
    validation (currently we just print it)."""
    payload = {
        "original_tweet": original_tweet,
        "result": {
            "n_won": result["n_won"],
            "n_lost": result["n_lost"],
            "total_invested_usd": round(result["total_invested_usd"], 2),
            "total_payout_usd": round(result["total_payout_usd"], 2),
            "net_pl_usd": round(result["net_pl_usd"], 2),
            "by_market": [
                {"side_bet": v["side_bet"],
                 "winning_outcome": v["winning_outcome"],
                 "usd_invested": round(v["usd_invested"], 2),
                 "pl": round(v["pl"], 2),
                 "won": v["won"]}
                for v in result["by_market"].values()
            ],
        },
    }
    response = llm_client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT_RESULT,
        input=(
            f"{json.dumps(payload, default=str, indent=2)}\n\n"
            f"Reply with a JSON object matching the schema in the instructions."
        ),
        max_output_tokens=2000,
        reasoning={"effort": "low"},
        text={"format": {"type": "json_object"}},
    )
    content = response.output_text or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return ""
    return (parsed.get("tweet") or "").strip()


# --- Per-tweet processing ---------------------------------------------------

def _artifact_path(tweet_id: str) -> str:
    return os.path.join(_RUN_OUTPUT_DIR, f"result_{tweet_id}.json")


def _save_artifact(tweet_id: str, payload: dict) -> None:
    os.makedirs(_RUN_OUTPUT_DIR, exist_ok=True)
    with open(_artifact_path(tweet_id), "w") as f:
        json.dump(payload, f, default=str, indent=2)


def process_tweet(llm_client, tweet: dict) -> str:
    """Returns one of: 'skipped_dedup', 'skipped_unresolved',
    'skipped_no_trades', 'composed', 'composed_no_pl'."""
    tweet_id = str(tweet["tweet_id"])
    if os.path.exists(_artifact_path(tweet_id)):
        return "skipped_dedup"

    alert_ids = [int(i) for i in (tweet.get("alert_ids") or []) if i is not None]
    condition_ids = [c for c in (tweet.get("condition_ids") or []) if c]
    if not alert_ids or not condition_ids:
        return "skipped_no_trades"

    resolutions: dict[str, dict] = {}
    for cid in condition_ids:
        res = _resolution_for_market(cid)
        if res is None:
            return "skipped_unresolved"
        resolutions[cid] = res

    trades = fetch_alert_trades(alert_ids)
    if not trades:
        return "skipped_no_trades"

    aggregate = aggregate_result(trades, resolutions)
    if aggregate["n_trades"] == 0:
        return "skipped_no_trades"

    # Alert metadata feeds the artifact's event/market labels below.
    meta = fetch_alert_meta(alert_ids)
    primary = meta.get(alert_ids[0]) or {}

    result_tweet = compose_result_tweet(
        llm_client, tweet.get("tweet_text") or "", aggregate,
    )

    artifact = {
        "tweet_id": tweet_id,
        "tweeted_at": tweet.get("tweeted_at"),
        "original_tweet": tweet.get("tweet_text"),
        "alert_ids": alert_ids,
        "condition_ids": condition_ids,
        "primary_event_slug": primary.get("event_slug"),
        "primary_market_title": primary.get("market_title"),
        "resolutions": {
            cid: {"winning_outcome": r["winning_outcome"],
                  "question": r.get("question")}
            for cid, r in resolutions.items()
        },
        "aggregate": aggregate,
        "result_tweet": result_tweet,
        "composed_at": datetime.now(timezone.utc).isoformat(),
        "posted_to_twitter": False,
    }
    _save_artifact(tweet_id, artifact)

    print(f"\n--- Result for tweet {tweet_id} "
          f"(W{aggregate['n_won']}-L{aggregate['n_lost']}, "
          f"net ${aggregate['net_pl_usd']:+,.0f}) ---")
    print(f"Original: {tweet.get('tweet_text')}")
    print(f"Result:   {result_tweet or '<empty — LLM returned no tweet>'}")
    print()

    return "composed" if result_tweet else "composed_no_pl"


# --- Entry point ------------------------------------------------------------

def main() -> int:
    log("run_start", bot="result_pipeline", dry_run=DRY_RUN)

    if not DATABASE_URL:
        log("config_error", error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)

    t0 = time.monotonic()
    candidates = fetch_candidate_tweets()
    log("candidates_fetched", count=len(candidates),
        elapsed_ms=int((time.monotonic() - t0) * 1000))

    counters = {"composed": 0, "composed_no_pl": 0, "skipped_dedup": 0,
                "skipped_unresolved": 0, "skipped_no_trades": 0,
                "errors": 0}
    for tweet in candidates:
        tweet_id = str(tweet["tweet_id"])
        try:
            outcome = process_tweet(llm_client, tweet)
            counters[outcome] = counters.get(outcome, 0) + 1
            log("tweet_processed", tweet_id=tweet_id, outcome=outcome)
        except Exception as exc:
            counters["errors"] += 1
            log("tweet_error", tweet_id=tweet_id,
                error=f"{type(exc).__name__}: {exc}")

    log("run_end", elapsed_ms=int((time.monotonic() - t0) * 1000), **counters)
    return 0


if __name__ == "__main__":
    sys.exit(main())
