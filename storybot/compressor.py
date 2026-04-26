"""
Per-tool-call compressor pipeline for the storybot.

The orchestrator emits a single tool call — `query({intent, hint?})` — and this
module turns that intent into a concrete backend query, runs it, then compresses
the result before it reaches the orchestrator.

Pipeline
    1. build    — GPT turns `intent` into {backend, query}.
    2. execute  — dispatches to the existing backend (sqlite / postgres / gamma / data_api / clob).
    3. route    — GPT picks a compression method (passthrough / python / llm).
    4. compress — runs the chosen method.

The python DSL is a closed set of deterministic operations — no code eval, exact
values preserved. LLM summarization is reserved for free-text fields where
paraphrase is acceptable (market descriptions, FAQs, long prose).
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable


PASSTHROUGH_BYTES = 2048
PREVIEW_BYTES = 600
SHAPE_DEPTH = 3


def _log(event: str, **fields: Any) -> None:
    """Emit one JSON log line (mirrors storybot.log format), plus a compact
    human-readable companion line for live tailing."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)
    pretty = _format_console(event, fields)
    if pretty:
        print(pretty, flush=True)


def _fmt_bytes(n: Any) -> str:
    if n is None:
        return "?"
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _estimate_tokens(n_chars: Any) -> int | None:
    """Rough token estimate for a payload of `n_chars` characters (chars / 4).
    Not exact — meant for logging the order-of-magnitude savings, not billing."""
    if n_chars is None:
        return None
    return max(1, int(n_chars) // 4) if n_chars else 0


def _fmt_tok_count(n: Any) -> str:
    if n is None:
        return "?"
    if n < 1000:
        return f"{n}"
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


def _fmt_tokens(f: dict) -> str:
    parts = []
    if f.get("prompt_tokens"):
        parts.append(f"prompt={f['prompt_tokens']}")
    if f.get("completion_tokens"):
        parts.append(f"completion={f['completion_tokens']}")
    if f.get("reasoning_tokens"):
        parts.append(f"reasoning={f['reasoning_tokens']}")
    if f.get("cached_prompt_tokens"):
        parts.append(f"cached={f['cached_prompt_tokens']}")
    return " ".join(parts)


def _format_console(event: str, f: dict) -> str:
    ms = f.get("ms") or f.get("total_ms")
    ms_s = f" {ms}ms" if ms is not None else ""
    toks = _fmt_tokens(f)
    toks_s = f"  {toks}" if toks else ""

    if event == "compressor_start":
        intent = (f.get("intent") or "")
        hint = f.get("hint")
        hint_s = f"  hint={hint!r}" if hint else ""
        return f"  [compressor] ▸ start  {intent!r}{hint_s}"

    if event == "compressor_build":
        repair = "  (repair)" if f.get("repair") else ""
        return f"  [compressor] ▸ build     backend={f.get('backend')}{repair}{ms_s}{toks_s}"

    if event == "compressor_execute":
        if f.get("error"):
            return (f"  [compressor] ✗ execute   backend={f.get('backend')}"
                    f"  ERROR: {f['error']}{ms_s}")
        retry = "  (retry)" if f.get("repair") else ""
        raw_tok = f.get("input_tokens_est")
        tok_s = f"  ~{_fmt_tok_count(raw_tok)}tok" if raw_tok is not None else ""
        return (f"  [compressor] ▸ execute   {f.get('backend')}{retry}  "
                f"{f.get('input_rows')} rows / {_fmt_bytes(f.get('input_bytes'))}{tok_s}{ms_s}")

    if event == "compressor_route":
        method = f.get("method")
        dsl = f"/{f.get('dsl_op')}" if f.get("dsl_op") else ""
        short = "  (short-circuit, no LLM)" if f.get("short_circuit") else ""
        return f"  [compressor] ▸ route     {method}{dsl}{short}{ms_s}{toks_s}"

    if event == "compressor_summarize":
        in_tok = f.get("input_tokens_est")
        out_tok = f.get("output_tokens_est")
        payload_s = ""
        if in_tok is not None and out_tok is not None:
            payload_s = f"  payload ~{_fmt_tok_count(in_tok)}→~{_fmt_tok_count(out_tok)}tok"
        return (f"  [compressor] ▸ summarize {_fmt_bytes(f.get('input_bytes'))} "
                f"→ {f.get('output_chars')} chars{payload_s}{ms_s}{toks_s}")

    if event == "compressor_done":
        if not f.get("ok"):
            return f"  [compressor] ✗ done      ERROR: {f.get('error')}{ms_s}"
        pipeline = f"{f.get('backend')}/{f.get('compression')}"
        if f.get("dsl_op"):
            pipeline += f"/{f['dsl_op']}"
        in_b = f.get("input_bytes", 0) or 0
        out_b = f.get("output_bytes", 0) or 0
        ratio_s = f" ({f['ratio']}x)" if f.get("ratio") is not None else ""
        in_tok = f.get("input_tokens_est")
        out_tok = f.get("output_tokens_est")
        saved_tok = f.get("saved_tokens_est")
        payload_s = ""
        if in_tok is not None and out_tok is not None:
            saved_part = f", saved ~{_fmt_tok_count(saved_tok)}" if saved_tok else ""
            payload_s = (f"  payload ~{_fmt_tok_count(in_tok)}→"
                         f"~{_fmt_tok_count(out_tok)}tok{saved_part}")
        total_toks = (f.get("prompt_tokens") or 0) + (f.get("completion_tokens") or 0)
        tok_breakdown = f"{f.get('prompt_tokens', 0)}/{f.get('completion_tokens', 0)}"
        extras = []
        if f.get("reasoning_tokens"):
            extras.append(f"reasoning={f['reasoning_tokens']}")
        if f.get("cached_prompt_tokens"):
            extras.append(f"cached={f['cached_prompt_tokens']}")
        extras_s = f"  [{' '.join(extras)}]" if extras else ""
        return (f"  [compressor] ✓ done      {pipeline}  "
                f"{f.get('input_rows')} rows, {_fmt_bytes(in_b)}→{_fmt_bytes(out_b)}{ratio_s}"
                f"{payload_s}{ms_s}  llm_tokens={total_toks} ({tok_breakdown}){extras_s}")

    return ""


def _extract_usage(response) -> dict:
    """Pull token counts out of one OpenAI response. Empty dict if no usage attached."""
    u = getattr(response, "usage", None)
    if u is None:
        return {}
    out: dict[str, int] = {
        "requests": 1,
        "prompt_tokens": u.prompt_tokens or 0,
        "completion_tokens": u.completion_tokens or 0,
        "total_tokens": u.total_tokens or 0,
    }
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        out["cached_prompt_tokens"] = getattr(details, "cached_tokens", 0) or 0
    cd = getattr(u, "completion_tokens_details", None)
    if cd is not None:
        out["reasoning_tokens"] = getattr(cd, "reasoning_tokens", 0) or 0
    return out


def _merge_usage(into: dict, delta: dict) -> None:
    for k, v in delta.items():
        into[k] = into.get(k, 0) + v


# --- Shared schema docs -----------------------------------------------------
#
# Used by the builder here AND by storybot.py's SYSTEM_PROMPT so the orchestrator
# and the builder share one source of truth. Literal braces (no f-string).

SCHEMA_DOCS = """## Column types you WILL get wrong if you're not careful
Some timestamp-shaped columns are unix-epoch **doubles**, not
TIMESTAMPTZ / TEXT. `NOW() - INTERVAL ...` will error against them. Handle
them like this:
  - Postgres `price_candles.t`                   → double (unix seconds).
    Filter with `t >= EXTRACT(EPOCH FROM NOW()) - 7200` for 'last 2 hours'.
  - SQLite `price_candles.t`                     → double (unix seconds).
    Filter with `t >= strftime('%s','now') - 7200`.
  - SQLite `wallet_event_history.trade_timestamp` → double (unix seconds, same pattern).
  - SQLite `wallet_pnl.api_timestamp`             → bigint (unix seconds).
  - SQLite `tracked_bets.trade_timestamp`         → double (unix seconds).

TIMESTAMPTZ / ISO-8601 text columns (use `NOW() - INTERVAL` / `datetime(...)` freely):
  - Postgres `alerts.scanned_at`, `alerts.created_at`, `alert_trades.trade_timestamp`,
    `tweeted_alerts.tweeted_at`, `price_candles.created_at`.
  - SQLite `*.recorded_at`, `*.snapshot_at`, `*.discovered_at` (all ISO-8601 text).

## Railway Postgres schema (key tables)
- alerts — one row per composite/cluster alert
    id, alert_type ('composite'|'cluster'), composite_score,
    market: market_title, condition_id, event_slug, market_url,
            market_image, market_description, tags (TEXT JSON-array, e.g. '["Sports","NBA"]'),
    wallet (NULL for cluster alerts),
    aggregates: total_usd, trade_count, cluster_headline,
    timing:  end_date, game_start_time, event_end_estimate
             (event_end_estimate = game_start_time if set else end_date;
              use this to rank "resolving soon"),
    llm: llm_headline, llm_summary,
         llm_bullets (TEXT JSON-array of strings),
         llm_copy_action (TEXT JSON-object: {outcome, side, entry_price, max_price}),
    seo: seo_title, seo_description, seo_summary,
         seo_faqs (TEXT JSON-array of {question, answer}), seo_generated_at,
    timestamps: scanned_at, created_at,
    dedup_key (UNIQUE)
- alert_trades — individual trades attached to an alert (FK alerts.id, cascades)
    id, alert_id, transaction_hash, wallet, condition_id, outcome,
    side ('BUY'|'SELL'), usd_value, size, price, trade_timestamp
    UNIQUE(alert_id, transaction_hash)
- alert_signals — detection signals that fired for an alert (FK alerts.id)
    id, alert_id, strategy (e.g. 'new_wallet_large_bet'), severity, headline
- wallet_profiles — per-wallet cached stats (PK=wallet)
    total_positions, closed_positions, wins, losses,
    total_pnl, total_invested, avg_win_price, win_rate,
    times_flagged, current_streak, first_seen_at, updated_at
- wallet_theses — cross-market thesis groupings (UNIQUE wallet+event_slug)
    id, wallet, event_slug, thesis_headline,
    markets (JSONB array), total_usd, composite_score, created_at, updated_at
- tweeted_alerts — dedup log for the Twitter bot (PK=alert_id)
    alert_id, wallet, condition_id, tweet_id, tweet_text, tweeted_at
    (composite tweets share tweet_id/tweet_text across multiple rows)
- price_candles — sparkline data, mirrored from SQLite
    id, condition_id, token_id, outcome, t (unix secs, DOUBLE), p, created_at
    UNIQUE(token_id, t)

JSON-in-TEXT columns: alerts.tags, alerts.llm_bullets, alerts.llm_copy_action,
alerts.seo_faqs. Parse with `(col)::jsonb` in Postgres to use `->`, `->>`,
`jsonb_array_elements`, etc. wallet_theses.markets is already JSONB.

## polybot.db (SQLite) schema (key tables)
Wallet P&L and track record (written by win_rate_tracking):
- wallet_pnl — one row per closed position (UNIQUE wallet+condition_id+asset+position_type)
    wallet, condition_id, asset, outcome, avg_price, total_bought,
    realized_pnl, cur_price, event_slug, end_date (TEXT),
    position_type, recorded_at, api_timestamp (BIGINT unix secs)
- tracked_bets — raw tracked trades for win/loss attribution
    (UNIQUE wallet+condition_id+outcome+side+trade_timestamp)
    wallet, condition_id, outcome, side, usd_value,
    trade_timestamp (REAL unix secs), recorded_at,
    resolved (0/1), won (0/1/NULL)

Wallet clustering & flags:
- wallet_funders — shared-funder cluster detection (PK=wallet)
    wallet, funder, discovered_at
- wallet_event_history — cross-run event history per wallet
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, event_slug, condition_id, outcome, side, usd_value,
    trade_timestamp (REAL unix secs), recorded_at, price, market_title
- flagged_wallets — per-wallet rollup of large-bet flags (PK=wallet)
    wallet, times_flagged, total_usd_flagged,
    first_flagged_at, last_flagged_at
- flagged_trade_events — per-trade dedup behind flagged_wallets
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, condition_id, trade_timestamp (REAL), usd_value, recorded_at
- timing_flags — bets placed close to resolution
    (UNIQUE wallet+condition_id+trade_timestamp)
    wallet, condition_id, minutes_to_resolution, usd_value,
    trade_timestamp (REAL), recorded_at, market_duration_hours

Market price/volume/orderbook state:
- market_volume_snapshots — 24h volume samples
    condition_id, volume_24h, snapshot_at
- price_history — per-trade price observations for price_impact
    (UNIQUE condition_id+outcome+trade_timestamp)
    condition_id, outcome, price, trade_timestamp (REAL), recorded_at
- price_candles — CLOB historical price time-series for sparklines
    (UNIQUE token_id+t)
    condition_id, token_id, outcome,
    t (REAL unix secs), p, recorded_at
- orderbook_snapshots — CLOB order book depth samples
    condition_id, token_id, outcome, best_bid, best_ask, spread,
    bid_depth, ask_depth, mid_price, snapshot_at

## Gamma API (https://gamma-api.polymarket.com)
Useful paths (all GET; allowlist = /markets, /events):
  /markets?condition_ids=...             market(s) by conditionId (comma-sep for many)
  /markets?slug=...                      market by slug
  /markets?tag_id=...&active=true        filter by tag + state (active/closed/archived)
  /markets?volume_num_min=...&order=...  filter/sort by volume, liquidity, end_date
  /markets/{id}                          single market by numeric id
  /markets/slug/{slug}                   single market by slug
  /markets/{id}/tags                     tags on a market
  /events?slug=...                       event(s) by slug (nested markets[])
  /events?tag_id=...&closed=false        filter events by tag + state
  /events/{id}                           single event by id
  /events/slug/{slug}                    single event by slug
  /events/{id}/tags                      tags on an event

## Data API (https://data-api.polymarket.com)
Trade data lives here, NOT on Gamma. Allowlist = /trades.
  /trades?market=<conditionId>&limit=...  recent trades on a market
  /trades?user=<wallet>&limit=...         recent trades by a wallet
Response: list of trade objects with fields like proxyWallet, side, outcome,
size, price, timestamp, conditionId, asset (token_id), title, slug, eventSlug.

Common query params:
  limit, offset                 pagination (default limit ~100, cap 500)
  active, closed, archived      boolean state filters
  order, ascending              sort field + direction (e.g. order=volume)
  end_date_min, end_date_max    ISO-8601 bounds on resolution time
  volume_num_min, liquidity_num_min  numeric floors

Notable response fields:
  market: conditionId, slug, question, endDate, outcomes, outcomePrices,
          volume, volumeNum, volume24hr, liquidity, active, closed, negRisk,
          clobTokenIds, bestBid, bestAsk, lastTradePrice, events[{id,slug}]
  event:  id, slug, title, endDate, negRisk, volume, liquidity,
          markets[] (nested, same shape as above), tags[{id,label,slug}]
  tag:    id, label, slug   (e.g. id="1" = Sports, "3" = Politics, "4" = Crypto)

## CLOB API (https://clob.polymarket.com)
The canonical source for price history and order book state. Prefer this over
`price_candles` / `orderbook_snapshots` for any claim that ends up in the tweet —
those tables are sampled, can be stale, and may be truncated.

/prices-history — historical price time-series for one outcome token
  Required: market=<CLOB token_id>                 (NOT conditionId!)
  Pick ONE windowing form:
    interval=1h|6h|1d|1w|max            relative window ending now
    startTs=<unix>&endTs=<unix>         explicit window (both required together)
  Optional: fidelity=<minutes>                     granularity (1 = minute candles)
  Response: {"history": [{"t": <unix_seconds>, "p": <price>}, ...]}  — full series,
  no 200-row cap, no LIMIT truncation risk.

  To get a token_id:
    1. Gamma /markets with condition_ids=<conditionId>
    2. response[0]["clobTokenIds"] is a JSON string of [yes_token, no_token]
       (or [token_for_outcome_0, token_for_outcome_1] — match by index to
       market["outcomes"]).

  For a "price moved from X to Y in the last hour" claim: use interval=1h +
  fidelity=1, then read `history[0].p` (earliest) and `history[-1].p` (latest)
  — and/or min/max across the full array. Do NOT trust price_candles for this.

/book — current order book for a token
  Required: token_id=<CLOB token_id>
  Response: {"bids": [...], "asks": [...], "timestamp": ...}
"""


# --- Builder ----------------------------------------------------------------

BUILDER_SYSTEM_PROMPT = f"""You turn a natural-language `intent` into one concrete query against one of
four backends. A downstream executor runs what you emit.

## Backends
- "sqlite"   → scanner's local polybot.db. Read-only SELECT/WITH only.
- "postgres" → Railway Postgres. Read-only SELECT/WITH only.
- "gamma"    → https://gamma-api.polymarket.com (allowlist: /markets, /events).
- "data_api" → https://data-api.polymarket.com (allowlist: /trades). Use this for
               recent trades by wallet or by market — Gamma does NOT serve trades.
- "clob"     → https://clob.polymarket.com (allowlist: /prices-history, /book).

## SQL dialect notes
Postgres: `NOW() - INTERVAL '1 hour'`, jsonb ops (`->`, `->>`, `jsonb_array_elements`), ILIKE.
SQLite:   no jsonb, LIKE is case-insensitive by default, `datetime('now','-1 hour')`.
Queries MUST be a single SELECT or WITH. Prefer narrow SELECT lists + LIMITs over SELECT *.

## Scope (mandatory when present)
The user message may include a `scope:` block — these are session constants the
orchestrator is researching (the picked event, alerts, wallets). Apply them as
hard filters on every query that touches a matching column / endpoint:

- `scope.event_slug`     → WHERE event_slug = '<slug>' on any table with that column.
                           Gamma: prefer /events?slug=<slug> or /markets?event_slug=…
- `scope.condition_ids`  → WHERE condition_id = ANY(...) similarly.
                           Gamma: /markets?condition_ids=<comma-sep>.
- `scope.wallets`        → WHERE wallet = ANY(...) on tables with a wallet column.
                           Data API: /trades?user=… (one wallet at a time).
- `scope.alert_ids`      → WHERE id = ANY(...) on alerts; WHERE alert_id = ANY(...)
                           on alert_trades / alert_signals.

Exception: when the intent EXPLICITLY asks for cross-scope data (e.g. "what
OTHER events did these wallets bet on"), drop only the scope field the intent
overrides — keep the rest.

{SCHEMA_DOCS}

## Output
Return exactly one JSON object and nothing else:

{{
  "backend": "sqlite" | "postgres" | "gamma" | "data_api" | "clob",
  "query": <backend-specific>
}}

For sqlite/postgres:        query = {{"sql": "SELECT ..."}}
For gamma/data_api/clob:    query = {{"path": "/markets", "params": {{...}} | null}}

If the intent names a specific wallet / condition_id / event_slug / token_id /
alert_id, use it verbatim. Default to `LIMIT 200` on list queries. Pick the
backend that most directly answers the intent; if an intent touches multiple
backends, pick the one holding the primary fact (the orchestrator can chain
follow-up queries for the rest).
"""


REPAIR_INSTRUCTION = """Your previous plan failed when executed. Same intent — \
try a different approach. Common causes: wrong backend, banned SQL keyword, \
invalid path / params, missing required param, referenced a table in the wrong \
database.

Error: {error}

Previous plan:
{plan}
"""


def build_query(llm_client, *, intent: str, hint: str | None, model: str,
                scope: dict | None = None,
                prior_plan: dict | None = None,
                prior_error: str | None = None,
                usage: dict | None = None) -> dict:
    parts = [f"intent: {intent}"]
    if hint:
        parts.append(f"hint: {hint}")
    if scope:
        parts.append(f"scope: {json.dumps(scope, default=str)}")
    if prior_error and prior_plan:
        parts.append(REPAIR_INSTRUCTION.format(
            error=prior_error,
            plan=json.dumps(prior_plan, default=str),
        ))
    user_msg = "\n\n".join(parts)

    t0 = time.monotonic()
    response = llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": BUILDER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=2000,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    ms = int((time.monotonic() - t0) * 1000)
    delta = _extract_usage(response)
    if usage is not None:
        _merge_usage(usage, delta)

    content = response.choices[0].message.content or "{}"
    try:
        plan = json.loads(content)
    except json.JSONDecodeError as exc:
        _log("compressor_build", ok=False, repair=prior_error is not None,
             error=f"invalid JSON: {exc}", ms=ms, **delta)
        raise

    valid = (plan.get("backend") in ("sqlite", "postgres", "gamma", "data_api", "clob")
             and isinstance(plan.get("query"), dict))
    _log("compressor_build",
         ok=valid,
         backend=plan.get("backend"),
         repair=prior_error is not None,
         ms=ms,
         **delta)
    if plan.get("backend") not in ("sqlite", "postgres", "gamma", "data_api", "clob"):
        raise ValueError(f"builder returned invalid backend: {plan.get('backend')!r}")
    if not isinstance(plan.get("query"), dict):
        raise ValueError(f"builder returned invalid query: {plan.get('query')!r}")
    return plan


# --- Execute ----------------------------------------------------------------

def execute_query(plan: dict, backends: dict[str, Callable]) -> Any:
    backend = plan["backend"]
    q = plan["query"]
    fn = backends[backend]
    if backend in ("sqlite", "postgres"):
        return fn(q["sql"])
    if backend in ("gamma", "data_api", "clob"):
        return fn(q["path"], q.get("params"))
    raise ValueError(f"unknown backend: {backend!r}")


# --- Router -----------------------------------------------------------------

ROUTER_SYSTEM_PROMPT = """You pick a compression method for one tool response.

Inputs:
  intent     — what the upstream agent wanted.
  sample     — {"shape": <structural fingerprint>, "preview": <truncated JSON>}.
               `shape` shows types and nesting with no content; a non-empty list
               appears as `[<shape-of-first-element>]`; strings carry length as
               `str[N]` so you can spot prose fields. Use `shape` as the source
               of truth for what fields exist (especially nested ones). The
               `preview` is only a flavor sample — don't assume fields absent
               from it don't exist.
  row_count  — number of rows/records.
  byte_size  — serialized JSON size.

Pick ONE of:
  "passthrough" — payload is already useful as-is; return unchanged.
  "python"      — deterministic DSL op. DEFAULT. Preserves every value byte-for-byte.
                  Use for anything involving numbers, IDs, timestamps, prices — any
                  field a downstream tweet might quote.
  "llm"         — LLM summarization. Allowed when the payload is dominated by
                  prose (long `str[N]` fields like descriptions, FAQs, HTML).
                  The summarizer is instructed to preserve every number, ID,
                  timestamp, and address verbatim, so mixed prose+numeric
                  payloads are fine. Prefer "python" when the payload is mostly
                  numeric/identifier data — it costs no extra tokens and
                  guarantees byte-for-byte fidelity.

## Python DSL — pick ONE op, fill the named keys. `cols` names must match keys in sample.

{"op": "top_k",     "k": <int>, "sort_by": "<col>", "direction": "desc"|"asc", "cols": ["<col>", ...] | null}
{"op": "project",   "cols": ["<col>", ...], "nested": {"<col>": ["<subcol>", ...], ...} | null}
{"op": "aggregate", "group_by": ["<col>", ...] | null, "metrics": [{"op": "sum"|"count"|"avg"|"min"|"max", "col": "<col>", "as": "<alias>"}]}
{"op": "filter",    "where": [{"col": "<col>", "op": "eq"|"ne"|"gt"|"lt"|"gte"|"lte"|"contains", "value": <any>}]}

### Nested projection (project.nested)
When a column holds a dict or a list of dicts and you only need some of its
sub-fields, put the column in `nested` with the sub-fields to keep. Nested keys
are implicitly kept, so you don't need to repeat them in `cols`. Example for a
Gamma event with a heavy nested `markets[]` array:

{"op": "project",
 "cols": ["title", "endDate", "volume", "liquidity"],
 "nested": {"markets": ["question", "conditionId", "clobTokenIds",
                        "bestBid", "bestAsk", "lastTradePrice", "volume24hr"],
            "tags":    ["label", "slug"]}}

This is the right tool for any payload whose `shape` shows a big
`list-of-dicts` value — use it instead of falling back to passthrough.

## Output
Return exactly one JSON object and nothing else:

{"method": "passthrough" | "python" | "llm", "spec": <DSL object> | null}

`spec` is required when method="python", otherwise null.
"""


def _shape(obj: Any, depth: int = SHAPE_DEPTH) -> Any:
    """Structural fingerprint: types and nesting, no content. Non-empty lists
    collapse to `[<shape-of-first-element>]`. Strings carry their length so the
    router can spot prose-heavy fields (e.g. `str[1840]` vs `str[12]`)."""
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return f"str[{len(obj)}]"
    if isinstance(obj, list):
        if not obj:
            return []
        if depth <= 0:
            return ["..."]
        return [_shape(obj[0], depth - 1)]
    if isinstance(obj, dict):
        if depth <= 0:
            return "{...}"
        return {k: _shape(v, depth - 1) for k, v in obj.items()}
    return type(obj).__name__


def _sample_and_size(data: Any) -> tuple[Any, int, int]:
    serialized = json.dumps(data, default=str)
    size = len(serialized)
    if isinstance(data, list):
        count = len(data)
        first = data[0] if data else None
    else:
        count = 1 if data is not None else 0
        first = data
    shape = _shape(first)
    preview_s = json.dumps(first, default=str)
    preview = preview_s if len(preview_s) <= PREVIEW_BYTES else preview_s[:PREVIEW_BYTES] + "…"
    sample = {"shape": shape, "preview": preview}
    return sample, count, size


def route_compression(llm_client, *, intent: str, data: Any, model: str,
                      usage: dict | None = None) -> dict:
    sample, count, size = _sample_and_size(data)
    if size <= PASSTHROUGH_BYTES:
        _log("compressor_route", method="passthrough", short_circuit=True,
             input_rows=count, input_bytes=size)
        return {"method": "passthrough", "spec": None}

    user_msg = json.dumps({
        "intent": intent,
        "sample": sample,
        "row_count": count,
        "byte_size": size,
    }, default=str)

    t0 = time.monotonic()
    response = llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=800,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    ms = int((time.monotonic() - t0) * 1000)
    delta = _extract_usage(response)
    if usage is not None:
        _merge_usage(usage, delta)

    content = response.choices[0].message.content or "{}"
    route = json.loads(content)
    method = route.get("method")
    dsl_op = (route.get("spec") or {}).get("op") if method == "python" else None
    _log("compressor_route",
         method=method,
         dsl_op=dsl_op,
         input_rows=count,
         input_bytes=size,
         ms=ms,
         **delta)
    if method not in ("passthrough", "python", "llm"):
        raise ValueError(f"router returned invalid method: {method!r}")
    return route


# --- Python DSL -------------------------------------------------------------

def _as_rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _project_row(row: dict, cols: list[str], nested: dict | None) -> dict:
    """Project a single dict. `cols` lists top-level keys to keep; `nested` maps
    a key → list of sub-columns to keep when that key holds a dict or a list of
    dicts. Keys that appear only in `nested` are implicitly kept."""
    nested = nested or {}
    order = list(cols) + [k for k in nested if k not in cols]
    out: dict = {}
    for k in order:
        if k not in row:
            continue
        v = row[k]
        if k in nested:
            sub = nested[k]
            if isinstance(v, list):
                out[k] = [_project_row(item, sub, None) for item in v if isinstance(item, dict)]
            elif isinstance(v, dict):
                out[k] = _project_row(v, sub, None)
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _apply_project(data: Any, spec: dict) -> Any:
    cols = spec["cols"]
    nested = spec.get("nested")
    if isinstance(data, dict) and not (len(data) == 1 and isinstance(next(iter(data.values())), list)):
        return _project_row(data, cols, nested)
    return [_project_row(r, cols, nested) for r in _as_rows(data)]


def _apply_top_k(data: Any, spec: dict) -> Any:
    rows = _as_rows(data)
    k = int(spec["k"])
    sort_by = spec["sort_by"]
    reverse = spec.get("direction", "desc") == "desc"
    with_val = [r for r in rows if r.get(sort_by) is not None]
    without = [r for r in rows if r.get(sort_by) is None]
    with_val.sort(key=lambda r: r[sort_by], reverse=reverse)
    top = (with_val + without)[:k]
    cols = spec.get("cols")
    if cols:
        top = [{c: r[c] for c in cols if c in r} for r in top]
    return top


def _metric(rows: list[dict], op: str, col: str) -> Any:
    vals = [r[col] for r in rows if col in r and r[col] is not None]
    if op == "count":
        return len(vals)
    if not vals:
        return None
    if op == "sum":
        return sum(vals)
    if op == "avg":
        return sum(vals) / len(vals)
    if op == "min":
        return min(vals)
    if op == "max":
        return max(vals)
    raise ValueError(f"unknown metric op: {op!r}")


def _apply_aggregate(data: Any, spec: dict) -> Any:
    rows = _as_rows(data)
    group_by = spec.get("group_by") or []
    metrics = spec["metrics"]

    def compute(bucket: list[dict], key_vals: tuple) -> dict:
        out = {gb: kv for gb, kv in zip(group_by, key_vals)}
        for m in metrics:
            out[m["as"]] = _metric(bucket, m["op"], m["col"])
        return out

    if not group_by:
        return [compute(rows, ())]

    buckets: dict[tuple, list[dict]] = {}
    for r in rows:
        key = tuple(r.get(g) for g in group_by)
        buckets.setdefault(key, []).append(r)
    return [compute(bucket, key_vals) for key_vals, bucket in buckets.items()]


_FILTER_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "lt": lambda a, b: a is not None and a < b,
    "gte": lambda a, b: a is not None and a >= b,
    "lte": lambda a, b: a is not None and a <= b,
    "contains": lambda a, b: (
        isinstance(a, str) and isinstance(b, str) and b.lower() in a.lower()
    ),
}


def _apply_filter(data: Any, spec: dict) -> Any:
    where = spec.get("where") or []
    rows = _as_rows(data)
    out: list[dict] = []
    for r in rows:
        if all(_FILTER_OPS[w["op"]](r.get(w["col"]), w["value"]) for w in where):
            out.append(r)
    return out


_DSL: dict[str, Callable[[Any, dict], Any]] = {
    "top_k": _apply_top_k,
    "project": _apply_project,
    "aggregate": _apply_aggregate,
    "filter": _apply_filter,
}


def apply_dsl(data: Any, spec: dict) -> Any:
    op = spec.get("op")
    fn = _DSL.get(op)
    if fn is None:
        raise ValueError(f"unknown DSL op: {op!r}")
    return fn(data, spec)


# --- LLM summarizer ---------------------------------------------------------

SUMMARIZER_SYSTEM_PROMPT = """You compress a free-text data payload for an upstream agent.

The agent's `intent` describes what they wanted from this data. Produce a tight,
factual summary answering the intent. Preserve exact values (numbers, dates, IDs)
verbatim when they appear. Drop prose the intent doesn't need.
"""


def summarize(llm_client, *, intent: str, data: Any, model: str,
              usage: dict | None = None) -> str:
    user_msg = json.dumps({"intent": intent, "data": data}, default=str)
    t0 = time.monotonic()
    response = llm_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=1,
        max_completion_tokens=2000,
        reasoning_effort="medium",
    )
    ms = int((time.monotonic() - t0) * 1000)
    delta = _extract_usage(response)
    if usage is not None:
        _merge_usage(usage, delta)
    out = response.choices[0].message.content or ""
    _log("compressor_summarize",
         input_bytes=len(user_msg),
         output_chars=len(out),
         input_tokens_est=_estimate_tokens(len(user_msg)),
         output_tokens_est=_estimate_tokens(len(out)),
         ms=ms,
         **delta)
    return out


# --- Compose ----------------------------------------------------------------

def compress(llm_client, *, intent: str, data: Any, route: dict,
             model: str, usage: dict | None = None) -> Any:
    method = route["method"]
    if method == "passthrough":
        return data
    if method == "python":
        spec = route.get("spec") or {}
        return apply_dsl(data, spec)
    if method == "llm":
        return summarize(llm_client, intent=intent, data=data,
                         model=model, usage=usage)
    raise ValueError(f"unknown method: {method!r}")


# --- Top-level --------------------------------------------------------------

def run_query(llm_client, *, intent: str, hint: str | None, model: str,
              backends: dict[str, Callable],
              scope: dict | None = None,
              usage: dict | None = None) -> dict:
    """Run the full compressor pipeline for one orchestrator tool call.

    `scope` (optional) is a dict of session-level constants the orchestrator is
    researching — typically {event_slug, condition_ids[], alert_ids[], wallets[]}.
    Set once by the caller from the picker's output; threaded through to the
    builder as a hard-filter rule so every query is auto-scoped.

    Returns an envelope:
        {"data": <compressed>, "backend": "...", "compression": "...",
         "input_rows": int, "input_bytes": int}
        or
        {"error": "<stage>: <message>"}
    """
    t_start = time.monotonic()
    call_usage: dict = {}
    _log("compressor_start", intent=intent[:160], hint=(hint or None),
         scope=(scope or None))

    def _finish_error(stage: str, err: str) -> dict:
        _log("compressor_done",
             intent=intent[:160],
             ok=False,
             error=f"{stage}: {err}",
             total_ms=int((time.monotonic() - t_start) * 1000),
             **call_usage)
        if usage is not None:
            _merge_usage(usage, call_usage)
        return {"error": f"{stage}: {err}"}

    try:
        plan = build_query(llm_client, intent=intent, hint=hint,
                           model=model, scope=scope, usage=call_usage)
    except Exception as exc:
        return _finish_error("builder", f"{type(exc).__name__}: {exc}")

    t_exec = time.monotonic()
    try:
        raw = execute_query(plan, backends)
        exec_ms = int((time.monotonic() - t_exec) * 1000)
        _, probe_rows, probe_bytes = _sample_and_size(raw)
        _log("compressor_execute",
             backend=plan.get("backend"),
             input_rows=probe_rows,
             input_bytes=probe_bytes,
             input_tokens_est=_estimate_tokens(probe_bytes),
             ms=exec_ms)
    except Exception as exc:
        repair_err = f"{type(exc).__name__}: {exc}"
        _log("compressor_execute",
             backend=plan.get("backend"),
             error=repair_err,
             ms=int((time.monotonic() - t_exec) * 1000))
        try:
            plan = build_query(llm_client, intent=intent, hint=hint,
                               model=model, scope=scope, usage=call_usage,
                               prior_plan=plan, prior_error=repair_err)
            t_exec = time.monotonic()
            raw = execute_query(plan, backends)
            exec_ms = int((time.monotonic() - t_exec) * 1000)
            _, probe_rows, probe_bytes = _sample_and_size(raw)
            _log("compressor_execute",
                 backend=plan.get("backend"),
                 input_rows=probe_rows,
                 input_bytes=probe_bytes,
                 input_tokens_est=_estimate_tokens(probe_bytes),
                 repair=True,
                 ms=exec_ms)
        except Exception as exc2:
            return _finish_error("executor", f"{type(exc2).__name__}: {exc2}")

    try:
        route = route_compression(llm_client, intent=intent, data=raw,
                                  model=model, usage=call_usage)
    except Exception as exc:
        route = {"method": "passthrough", "spec": None,
                 "_router_error": f"{type(exc).__name__}: {exc}"}

    try:
        compressed = compress(llm_client, intent=intent, data=raw,
                              route=route, model=model, usage=call_usage)
        method = route["method"]
    except Exception as exc:
        compressed = raw
        method = "passthrough"
        route = {"method": "passthrough", "spec": None,
                 "_compress_error": f"{type(exc).__name__}: {exc}"}

    _, in_rows, in_bytes = _sample_and_size(raw)
    out_bytes = len(json.dumps(compressed, default=str))
    in_tok_est = _estimate_tokens(in_bytes)
    out_tok_est = _estimate_tokens(out_bytes)
    saved_tok_est = (
        max(0, in_tok_est - out_tok_est)
        if in_tok_est is not None and out_tok_est is not None
        else None
    )
    _log("compressor_done",
         intent=intent[:160],
         ok=True,
         backend=plan.get("backend"),
         compression=method,
         dsl_op=(route.get("spec") or {}).get("op") if method == "python" else None,
         input_rows=in_rows,
         input_bytes=in_bytes,
         output_bytes=out_bytes,
         input_tokens_est=in_tok_est,
         output_tokens_est=out_tok_est,
         saved_tokens_est=saved_tok_est,
         ratio=round(out_bytes / in_bytes, 3) if in_bytes else None,
         router_error=route.get("_router_error"),
         compress_error=route.get("_compress_error"),
         total_ms=int((time.monotonic() - t_start) * 1000),
         **call_usage)

    if usage is not None:
        _merge_usage(usage, call_usage)

    result: dict = {
        "data": compressed,
        "backend": plan.get("backend"),
        "compression": method,
        "input_rows": in_rows,
        "input_bytes": in_bytes,
    }
    if route.get("_router_error"):
        result["router_error"] = route["_router_error"]
    if route.get("_compress_error"):
        result["compress_error"] = route["_compress_error"]
    return result


# --- Usage tracking ---------------------------------------------------------

def _accumulate_usage(usage: dict, response) -> None:
    _merge_usage(usage, _extract_usage(response))
