"""
Simple single-tweet bot for PolySpotter.

Fetches the same seed alerts as storybot (top alerts from the last ~3 hours,
Gamma-filtered to drop already-settled markets), then in ONE LLM call picks
the best story and writes a single tweet — or skips if nothing stands out.
No research tools, no thread, no two-stage pipeline.

Run via cron:
    python storybot/twitter_simple.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

from storybot import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    DATABASE_URL,
    MODEL,
    QUERY_TIMEOUT_SECONDS,
    TWEET_MAX_CHARS,
    TWEET_URL_CHARS,
    _BANNED_TWEET_PHRASES,
    _POLYSPOTTER_URL_RE,
    _accumulate_usage,
    _build_twitter_api_v1,
    _build_twitter_client,
    _compact_alert_for_picker,
    _tweet_length,
    fetch_seed_alerts,
    log,
    record_tweet,
)

import charts


load_dotenv()

DRY_RUN = os.environ.get("TWITTER_SIMPLE_DRY_RUN", "false").lower() == "true"

_POLYSPOTTER_URL_STRIP_RE = re.compile(
    r"\s*https://polyspotter\.com/(?:market|wallet|alert|tag)/\S+"
)


def _strip_polyspotter_url(tweet: str) -> str:
    """Remove polyspotter.com deep links (and any leading whitespace) before posting."""
    return _POLYSPOTTER_URL_STRIP_RE.sub("", tweet).rstrip()


def _already_tweeted_ids(alert_ids: list[int]) -> set[int]:
    """Return the subset of alert_ids that already have a row in tweeted_alerts."""
    if not alert_ids:
        return set()
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=QUERY_TIMEOUT_SECONDS)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT alert_id FROM tweeted_alerts WHERE alert_id = ANY(%s)",
            ([int(i) for i in alert_ids],),
        )
        rows = cur.fetchall()
        cur.close()
        return {int(r[0]) for r in rows}
    finally:
        conn.close()


def filter_posted_alerts(seed_alerts: list[dict]) -> list[dict]:
    """Drop seed alerts that have already been tweeted (by any bot).

    Scoped to twitter_simple — storybot intentionally re-evaluates the same
    alerts and lets the LLM judge dedup via the tweeted_dedup tool."""
    ids = [int(a["id"]) for a in seed_alerts if a.get("id") is not None]
    posted = _already_tweeted_ids(ids)
    return [a for a in seed_alerts if int(a.get("id") or 0) not in posted]


SYSTEM_PROMPT = f"""You are the social media voice for PolySpotter — a service \
that surfaces notable bets on Polymarket (whales, sharp wallets, coordinated \
flow, informed edge). You're triggered to look at the top alerts from the \
last ~3 hours and write ONE tweet about the best story — or skip if nothing \
stands out.

You see a compact list of up to 20 alerts, sorted by composite_score, each
with its top signals (strategy + severity + headline), market, wallet,
$ size, event, tags, and timing. Pick the single best **story** and write
one tweet that fits in {TWEET_MAX_CHARS} characters.

URLs count as {TWEET_URL_CHARS} chars regardless of length (Twitter wraps
every link via t.co), everything else counts as its literal length.

## Strategy primer (lead with the strongest)
- **wallet_clustering** / **concentrated_one_sided** → coordinated flow,
  multiple wallets (often shared funder) all hitting the same outcome.
- **timing_relative_resolution** → bet placed minutes before resolution.
  "SERIAL TIMER" wallets are the sharpest tier.
- **new_wallet_large_bet** → fresh account (<30 days) with conviction.
- **win_rate_tracking** → proven sharp wallet (>=75% win rate, 10+ bets,
  beating implied odds by 15%+).
- **pre_event_volume_spike** → sudden flood (10x+ normalized average).
- **price_impact** → a wallet just moved the market.
- **low_activity_large_bet** → big bet on a thinly-traded market.
- **correlated_cross_market** → cross-market thesis on one event.

## Audience
Write for a sports/markets-curious reader who has never heard of
PolySpotter and may not know Polymarket. They will not parse insider
shorthand. Every tweet must work as a self-contained sentence.

- Anchor the venue once: "on Polymarket", "Polymarket account",
  "prediction-market bettors". Don't make the reader guess where
  this is happening or that real money is at stake.
- Spell out what every bet is ON. Never leave a number naked:
  "Under 7.5 runs" (not "Under 7.5"), "Yes on Fed cuts in May"
  (not "Yes for $40k"), "buying No at 12c" (not "buying at 12c").
- When citing a win rate or record, say what it counts:
  "88% across 50+ Polymarket bets" / "178-20 on past markets",
  not "wins 88% of the time".
- Translate the strategy concept into plain behavior, not the label:
  - wallet_clustering / concentrated_one_sided →
    "three accounts sharing one funder", "a group of accounts
    moving in lockstep on the same side"
  - timing_relative_resolution → "buying with X minutes left",
    "an account that keeps showing up minutes before resolution"
  - new_wallet_large_bet → "a 12-day-old account dropping $80k"
  - win_rate_tracking → "an account hitting 88% of prior bets"
  - pre_event_volume_spike → "10x the usual flow into this market"
  - price_impact → "a single buy that pushed the line from 32c to 41c"

## Style
- Confident, punchy, human. Like a sharp friend explaining what they
  just spotted — NOT analyst-speak, NOT a press release, NOT scanner
  output.
- Lead with the SINGLE most surprising fact in the story — not the
  structural setup. Identify the one thing that makes a reader stop
  scrolling, and put it in the first clause; everything else is
  supporting context. The hook depends on what's actually surprising:
  - win_rate / sharp wallet → record-led: "An account that's gone
    29-4 on Polymarket just…"
  - new_wallet_large_bet → age-led: "A 12-day-old account just
    dropped $80k…"
  - timing_relative_resolution → timing-led: "With 4 minutes left,
    someone bought…"
  - price_impact → impact-led: "One buy just flipped this market
    from 32c to 41c…"
  - low_activity_large_bet → size-led: "$50k just landed on a
    market that's seen $4k all week…"
  - wallet_clustering / concentrated_one_sided → cluster-led only
    if the cluster IS the surprising thing; if one of the cluster
    wallets has a strong record, lead with the record and bring
    in the cluster as supporting context.
- Pacing: 2-3 short sentences beats one long clause-stack. Aim for
  ≤20 words per sentence. Punchy rhythm > polished prose.
- Round numbers for readability: "$78k" not "$78,131.61"; "$2.8M" not
  "$2,789,285.20". Win-rate records stay exact ("178-20"). Max 3 numbers.
- Refer to wallets by what makes them notable ("a 178-20 wallet", "a
  fresh account up $400k"), not by 0x address — unless that wallet is
  itself the thing the reader should track.
- The closing line earns its spot: a stake, a time pressure, or
  something concrete to watch. NOT vague chest-thumps like "Not
  random.", "Something's cooking.", "Eyes peeled.", "Worth a look.".
  If you don't have a real closer, end on the link.
- 0-1 emoji, only if it earns its spot. No hashtags. No @mentions.
- BANNED jargon — speak like a human, not a scanner: "deployed capital",
  "real size", "meaningful size", "conviction flow", "high-conviction",
  "scan window", "composite score", "alerted flow", "positioning",
  "near-resolution flag", "priced in", "coordinated burst", "pile-in",
  "counterpunch", "looked cleaner", "linked wallet(s)", "wallet trio",
  "wallet duo", "wallet squad", "informed flow", "smart money flow".
- Banned CTAs: "in bio", "full breakdown", "link below", "more at".

## Worked example
BAD (jargon-heavy, no context, vague closer):
  "A linked wallet trio just slammed Red Sox/Orioles Under 7.5 for
  $32k. One buyer wins 88% of the time. Not random baseball action."
Why it's bad: "linked wallet trio" is insider lingo, "Under 7.5"
omits the unit (runs), "wins 88%" omits what (Polymarket bets),
nothing tells the reader this is a prediction market, and the
closer adds no information.

OK (clear but buries the lede in a long opening clause):
  "Three Polymarket accounts sharing one funder just stacked $32k on
  Red Sox/Orioles staying under 7.5 runs tonight. One of them is 88%
  across 50+ prior bets on the site."
Why it's only OK: the strongest fact (the 88% record) shows up
second, and the opening sentence runs ~25 words.

GOOD (lead with the record, short sentences):
  "A Polymarket account with a 29-4 record just helped pile $65k on
  Red Sox/Orioles staying under 7.5 runs tonight. Two more accounts
  on the same funder rode along.
  https://polyspotter.com/alert/114781"

## Link (mandatory)
Include exactly one polyspotter.com deep link. Prefer the market page;
use a wallet link only when the story is about one specific wallet.
- market: https://polyspotter.com/market/<slug>
    <slug> = kebab-cased market_title (lowercase, non-alnum → single dash,
    trim leading/trailing dashes, max 80 chars) + "-" + first 7 chars of
    condition_id (i.e. "0x" + 5 hex chars).
    Example: "Will Trump win 2024?" + "0xc5300759dc..." →
    "will-trump-win-2024-0xc53007"
- wallet: https://polyspotter.com/wallet/<wallet_address>
- alert:  https://polyspotter.com/alert/<alert_id>
- tag:    https://polyspotter.com/tag/<tag-slug>

## Chart selection
You also pick the chart image that ships with the tweet. The chart should
prove the surprise the tweet's hook leads with. Pick the chart_type whose
visual carries the lead clause:

- Tweet leads with a price move ("flipped from 32c to 41c") → "price_sparkline"
- Tweet leads with a volume multiplier ("906× normal volume") → "volume_bar"
- Tweet leads with a wallet record ("178-20", "29-4") or wallet age ("12-day-old") → "wallet_record_card"
- Tweet leads with coordinated flow ("five accounts sharing a funder") AND no single wallet record dominates → "cluster_card"
- If nothing supports a chart cleanly → "none"

The chart fails silently if the underlying data isn't available — your job
is just to pick the visual that best matches the lead clause. Don't second-
guess data availability; the system handles fallbacks.

## When to skip
If all alerts are small, generic, or lack a clear story, skip the run.
Don't force a tweet.

## Output (strict JSON only)
{{
  "decision": "post" | "skip",
  "reason": "<one short sentence>",
  "tweet": "<tweet text>" | null,
  "alert_ids": [<int>, ...] | null,
  "chart_type": "price_sparkline" | "volume_bar" | "wallet_record_card" | "cluster_card" | "none"
}}

When decision=post, `tweet` must be present and ≤{TWEET_MAX_CHARS} chars
(URLs counted as {TWEET_URL_CHARS}). `alert_ids` must be 1+ real IDs from
the list shown to you — multiple is fine when they share an event.
When decision=post, `chart_type` must be one of the five enum values.
When decision=skip, `chart_type` is ignored (set to "none" or omit).
"""


def write_tweet(llm_client, seed_alerts: list[dict], *,
                usage: dict | None = None) -> dict:
    """Single-shot: pick best story + write one tweet (or skip). No tools."""
    compact = [_compact_alert_for_picker(a) for a in seed_alerts]
    user_msg = (
        f"Alerts from the last ~3 hours ({len(compact)} rows), sorted by "
        f"composite_score:\n\n{json.dumps(compact, default=str, indent=2)}"
    )
    response = llm_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=10000,
        reasoning_effort="high",
        response_format={"type": "json_object"},
    )
    if usage is not None:
        _accumulate_usage(usage, response)
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        return {"decision": "skip", "reason": f"invalid JSON: {exc}",
                "tweet": None, "alert_ids": None}


def validate_decision(decision: dict) -> tuple[bool, str]:
    d = decision.get("decision")
    if d == "skip":
        return True, ""
    if d != "post":
        return False, f"unknown decision: {d!r}"
    tweet = decision.get("tweet")
    if not isinstance(tweet, str) or not tweet.strip():
        return False, "tweet must be a non-empty string"
    tlen = _tweet_length(tweet)
    if tlen > TWEET_MAX_CHARS:
        return False, f"tweet length {tlen} exceeds {TWEET_MAX_CHARS}"
    lower = tweet.lower()
    for phrase in _BANNED_TWEET_PHRASES:
        if phrase in lower:
            return False, f"tweet contains banned CTA phrase {phrase!r}"
    if not _POLYSPOTTER_URL_RE.search(tweet):
        return False, "tweet must contain a polyspotter.com deep link (/market, /wallet, /alert, or /tag)"
    ids = decision.get("alert_ids") or []
    if not isinstance(ids, list) or not ids:
        return False, "alert_ids must be a non-empty list when posting"
    try:
        [int(i) for i in ids]
    except (TypeError, ValueError):
        return False, f"alert_ids must be integers, got {ids!r}"
    # chart_type validation (post-only)
    chart_type = decision.get("chart_type", "none")
    if chart_type is None:
        chart_type = "none"
    valid_chart_types = {"price_sparkline", "volume_bar", "wallet_record_card",
                         "cluster_card", "none"}
    if chart_type not in valid_chart_types:
        return False, f"unknown chart_type: {chart_type!r}"
    return True, ""


def prepare_chart(decision: dict, seed_alerts: list[dict]) -> bytes | None:
    """Resolve the alert and render the requested chart, with fallback to
    wallet_record_card. Returns PNG bytes or None. Never raises."""
    if decision.get("decision") != "post":
        return None
    alert_ids = decision.get("alert_ids") or []
    if not alert_ids:
        return None
    try:
        target_id = int(alert_ids[0])
    except (TypeError, ValueError):
        return None
    alert = next((a for a in seed_alerts if int(a.get("id") or 0) == target_id), None)
    if alert is None:
        return None
    chart_type = decision.get("chart_type") or "none"
    try:
        return charts.render_chart_for_alert(chart_type, alert)
    except Exception as exc:
        log("chart_render_error", error=f"{type(exc).__name__}: {exc}",
            chart_type=chart_type, alert_id=target_id)
        return None


def post_tweet(
    text: str,
    *,
    twitter_client,
    twitter_api_v1=None,
    media_png: bytes | None = None,
    dry_run: bool,
) -> str:
    """Post a single tweet, optionally with one PNG attached. Returns the tweet id."""
    if dry_run:
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    media_ids = None
    if media_png is not None and twitter_api_v1 is not None:
        from io import BytesIO
        media = twitter_api_v1.media_upload(filename="chart.png", file=BytesIO(media_png))
        media_id = getattr(media, "media_id", None) or getattr(media, "media_id_string", None)
        if media_id:
            media_ids = [media_id]

    if media_ids:
        resp = twitter_client.create_tweet(text=text, media_ids=media_ids)
    else:
        resp = twitter_client.create_tweet(text=text)
    data = getattr(resp, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {resp!r}")
    return tweet_id


def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    log("run_start", run_id=run_id, dry_run=DRY_RUN, bot="twitter_simple")

    if not DATABASE_URL:
        log("config_error", run_id=run_id, error="DATABASE_URL not set")
        return 1
    if not AZURE_OPENAI_API_KEY:
        log("config_error", run_id=run_id, error="AZURE_OPENAI_API_KEY not set")
        return 1

    llm_client = OpenAI(base_url=AZURE_OPENAI_ENDPOINT, api_key=AZURE_OPENAI_API_KEY)
    usage_totals: dict = {}
    run_start_t = time.monotonic()

    t_seed = time.monotonic()
    try:
        seed_alerts = fetch_seed_alerts()
    except Exception as exc:
        log("seed_fetch_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    seed_ms = int((time.monotonic() - t_seed) * 1000)
    log("seed_fetched", run_id=run_id, count=len(seed_alerts), elapsed_ms=seed_ms)

    if not seed_alerts:
        log("skip", run_id=run_id, reason="no alerts in the last 3 hours")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    pre_dedup_count = len(seed_alerts)
    try:
        seed_alerts = filter_posted_alerts(seed_alerts)
    except Exception as exc:
        log("dedup_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    log("dedup_filtered", run_id=run_id,
        before=pre_dedup_count, after=len(seed_alerts),
        dropped=pre_dedup_count - len(seed_alerts))

    if not seed_alerts:
        log("skip", run_id=run_id, reason="all seed alerts already tweeted")
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    t_llm = time.monotonic()
    try:
        decision = write_tweet(llm_client, seed_alerts, usage=usage_totals)
    except Exception as exc:
        log("llm_usage", run_id=run_id, **usage_totals)
        log("llm_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    llm_ms = int((time.monotonic() - t_llm) * 1000)

    log("llm_usage", run_id=run_id, **usage_totals)
    log("decision", run_id=run_id, decision=decision.get("decision"),
        alert_ids=decision.get("alert_ids"), reason=decision.get("reason"),
        elapsed_ms=llm_ms)

    ok, err = validate_decision(decision)
    if not ok:
        log("validation_error", run_id=run_id, error=err, decision=decision)
        return 1

    if decision["decision"] == "skip":
        log("skip", run_id=run_id, reason=decision.get("reason"))
        log("run_end", run_id=run_id, posted=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    tweet = _strip_polyspotter_url(decision["tweet"])
    alert_ids = [int(i) for i in decision["alert_ids"]]

    chart_png = prepare_chart(decision, seed_alerts)
    log("chart_selected", run_id=run_id,
        chart_type=decision.get("chart_type"),
        rendered=chart_png is not None,
        bytes_len=(len(chart_png) if chart_png else 0))

    if DRY_RUN and chart_png is not None:
        out_path = f"storybot/dry_runs/twitter_simple_{run_id}.png"
        try:
            with open(out_path, "wb") as f:
                f.write(chart_png)
            log("chart_saved_dryrun", run_id=run_id, path=out_path)
        except OSError as exc:
            log("chart_save_error", run_id=run_id, error=str(exc))

    try:
        twitter_client = _build_twitter_client()
        twitter_api_v1 = _build_twitter_api_v1() if chart_png is not None else None
        tweet_id = post_tweet(
            tweet,
            twitter_client=twitter_client,
            twitter_api_v1=twitter_api_v1,
            media_png=chart_png,
            dry_run=DRY_RUN,
        )
    except Exception as exc:
        log("post_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        return 1

    log("posted", run_id=run_id, tweet_id=tweet_id, alert_ids=alert_ids,
        tweet_length=len(tweet))
    print(f"\n--- Tweet ({len(tweet)} chars) ---\n{tweet}\n", flush=True)

    if DRY_RUN:
        log("run_end", run_id=run_id, posted=True, dry_run=True, tweet_id=tweet_id,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    try:
        record_tweet(alert_ids, tweet_id, tweet)
    except Exception as exc:
        log("record_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
        log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=False,
            elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
        return 0

    log("run_end", run_id=run_id, posted=True, tweet_id=tweet_id, recorded=True,
        elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
