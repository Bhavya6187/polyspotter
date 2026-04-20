# Twitter Bot — Agentic Composer Extension

**Date:** 2026-04-19
**Status:** Approved, pending implementation plan
**Supersedes section:** "LLM prompt" and step 5 of "Data flow" in [2026-04-19-twitter-bot-design.md](./2026-04-19-twitter-bot-design.md)

## Goal

Replace the current single-pass `call_llm()` step in the hourly Twitter bot with an **agentic composer** that can pull deeper context from the hosted API, Railway Postgres, local `polybot.db`, and the Gamma API before writing the tweet. The model acts like an investigative journalist: it sees the hour's top 5 alerts, decides what's worth digging into, makes up to 5 tool calls for context, then emits the same decision JSON the existing bot already consumes.

Every other part of the bot — fetch, dedup, top-5 sort, final validation, post, record, dry-run, logging — is unchanged.

## Non-goals

- No new API endpoints on the backend.
- No Postgres schema changes.
- No changes to the scanner or ingest path.
- No langchain / no multi-agent setup. Single agent, native OpenAI function calling.
- No write tools. All tools are read-only.

## Architecture

### New module: `backend/twitter_bot_agent.py`

Houses the tool definitions, the tool dispatcher, and the agentic loop. Exposes one public entry point:

```python
def compose_tweet(
    top5: list[dict],
    *,
    llm_client,
    db_conn_pg,        # psycopg2 connection to Railway Postgres
    db_conn_sqlite,    # sqlite3 connection to polybot.db
    http,              # requests-compatible
) -> dict
```

Returns the same decision dict the existing bot consumes:

```json
{
  "decision": "post" | "skip",
  "reason": "short string",
  "alert_ids": [<int>, ...] | null,
  "tweet": "<string ≤260 chars | null>",
  "is_composite": true | false
}
```

### Integration in `twitter_bot.py`

The existing [backend/twitter_bot.py](../../../backend/twitter_bot.py):

- Imports `compose_tweet` from `twitter_bot_agent`.
- Replaces the `call_llm(top5, llm_client=...)` call in `main()` with `compose_tweet(top5, llm_client=..., db_conn_pg=..., db_conn_sqlite=..., http=...)`.
- Constructs a `sqlite3` connection to `polybot.db` (via the existing `db.get_db()` helper) and passes it in.
- Updates `_build_user_message()` to include the fields the agent needs (see "Input-payload fix" below).

The 260-char validation + length retry logic stays where it is today — it wraps the whole agent call. `validate_decision()` is unchanged.

### File layout

| Path | Change |
|---|---|
| `backend/twitter_bot_agent.py` | **NEW** — 16 tool functions, `TOOL_SCHEMAS`, dispatch, loop, `compose_tweet()`, enriched system prompt |
| `backend/twitter_bot.py` | Update: import and call `compose_tweet`, wire SQLite connection, enrich `_build_user_message()` |
| `backend/test_twitter_bot_agent.py` | **NEW** — agent unit tests |
| `backend/test_twitter_bot.py` | Update: existing tests swap the LLM fake for an agent fake that returns a decision dict |
| `backend/requirements.txt` | Add `jmespath>=1.0` |

No changes to `backend/schema.sql` or `backend/database.py`.

## Agent loop

```
compose_tweet(top5):
  messages = [system_prompt, user_message_with_top5]
  tool_calls_used = 0
  MAX_TOOL_CALLS = 5
  MAX_ITERATIONS = 7   # 5 tool rounds + 1 forcing round + 1 safety

  for iteration in range(MAX_ITERATIONS):
    response = llm.chat.completions.create(
        model="gpt-5.4",
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto" if tool_calls_used < MAX_TOOL_CALLS else "none",
        response_format={"type": "json_object"} if final_round else None,
        temperature=0.7,
        max_completion_tokens=800,
    )
    msg = response.choices[0].message
    messages.append(msg)

    if msg.tool_calls and tool_calls_used < MAX_TOOL_CALLS:
        # Count every tool call toward the budget (including bad ones).
        for call in msg.tool_calls:
            tool_calls_used += 1
            result = dispatch(call.name, call.arguments)
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result)})
        continue

    if msg.tool_calls and tool_calls_used >= MAX_TOOL_CALLS:
        # Model tried more after budget — inject forcing message.
        messages.append({"role": "user", "content":
            "Tool budget exhausted. Return your final JSON decision now — no more tool calls."})
        final_round = True
        continue

    # No tool calls requested → this should be the final JSON.
    return parse_json_decision(msg.content)

  raise RuntimeError("agent failed to produce a final decision within MAX_ITERATIONS")
```

### Budget semantics

- **5 tool calls total per run**, whether successful, errored, or mistargeted. Incentivizes the model to be deliberate.
- Tool calls are counted before dispatch. If a single assistant message contains more tool calls than the remaining budget (e.g., already used 3, asks for 4 more in one turn), the dispatcher executes the first 2 normally and returns `{"error": "tool budget exhausted"}` for the 3rd and 4th — preserving the `tool_call_id` mapping so OpenAI's API stays happy. `tool_calls_used` then equals 5 and the next turn gets the forcing message.

### Final-output validation

After `compose_tweet` returns, the existing code path runs:
1. `validate_decision()` — alert_ids membership + composite invariant + length ≤ 260.
2. If length > 260, the existing one-shot length retry runs (at the `call_llm` level — preserved via a thin wrapper).

If the agent returns malformed JSON (not parseable, missing required fields), `compose_tweet` raises `AgentOutputError`, `twitter_bot.main()` catches it and logs `event=llm_error`, exit 1 (same behavior as today).

## Tool interface

### Standard shape

Every tool follows this contract:

```python
def tool_name(
    <tool-specific args>,
    *,
    projection: str | None = None,
    # injected deps (not exposed in the tool schema)
    http=None, db_conn_pg=None, db_conn_sqlite=None,
) -> dict
```

**Return envelope (success):**
```json
{"data": <result or projected result>, "truncated": false}
```
**Return envelope (error):**
```json
{"error": "<human-readable reason>"}
```

The LLM sees only the success/error envelope — injected deps are applied by the dispatcher.

### Response pipeline (per tool call)

1. Validate inputs (type coerce, reject unknown fields).
2. Execute the backing query (HTTP, Postgres, or SQLite).
3. If the query raises or returns an HTTP error, return `{"error": "<class>: <msg>"}`.
4. If `projection` is set:
   - Compile the JMESPath expression. On compile error → `{"error": "projection invalid: <msg>"}`.
   - Evaluate. On eval error → `{"error": "projection failed: <msg>"}`.
   - Use the projected value as the response body.
5. JSON-serialize the response body. If serialized length > 8192 bytes:
   - For arrays at the top level: trim to the first N items that fit.
   - For dicts: truncate stringified version to 8192 chars with `…` suffix.
   - Set `truncated: true`.
6. Return the envelope.

### JMESPath projection examples (included in system prompt)

| What the model wants | `projection` |
|---|---|
| How many bets has this wallet made? | `length(bet_history)` |
| Just win rate + P&L, no history | `{win_rate: win_rate, total_pnl: total_pnl, wins: wins, losses: losses}` |
| Only winning bets | `bet_history[?won==\`true\`]` |
| Avg entry price on wins | `avg(bet_history[?won==\`true\`].entry_price)` |
| Market titles in recent alerts | `recent_alerts[*].market_title` |
| Max volume in snapshot history | `max_by(snapshots, &volume_24h).volume_24h` |

**Bad projection handling:** if JMESPath compile/eval fails, the tool returns `{"error": "projection failed: ..."}` and counts as one of the 5 tool calls — so the model is incentivized to get expressions right. On a failed projection, the model can retry with a different expression (eats another call) or re-call without `projection` to see the raw shape.

## The 16 tools

All tools accept an optional `projection: str`. Args below exclude that.

### Backend API / Postgres (9)

| # | Name | Args | Backing |
|---|---|---|---|
| 1 | `get_wallet_profile` | `wallet: str` | `GET {POLYSPOTTER_API_URL}/api/wallets/{wallet}` — returns profile + `recent_alerts` (up to 10) + `bet_history` (up to 20) |
| 2 | `get_alert_detail` | `alert_id: int` | `GET /api/alerts/{alert_id}` — full trades + signals |
| 3 | `get_market_price_history` | `condition_id: str, hours: int = 24` | `GET /api/market/{condition_id}/price-history` |
| 4 | `get_market_holders` | `condition_id: str` | `GET /api/market/{condition_id}/holders` |
| 5 | `get_market_alerts` | `condition_id: str, limit: int = 10` | Postgres `SELECT id, composite_score, wallet, total_usd, llm_headline, created_at FROM alerts WHERE condition_id = %s ORDER BY composite_score DESC LIMIT %s` |
| 6 | `get_event_alerts` | `event_slug: str, limit: int = 20` | Postgres `SELECT ... FROM alerts WHERE event_slug = %s ORDER BY composite_score DESC LIMIT %s` |
| 7 | `get_live_market` | `condition_id: str` | `GET /api/market/{condition_id}/live` |
| 8 | `get_theses` | `wallet: str \| None, condition_id: str \| None, event_slug: str \| None` | Uses `GET /api/market/{condition_id}/theses` when `condition_id` is given; otherwise `GET /api/theses` and filters client-side by `wallet` or `event_slug`. **Exactly one** of the three filters must be provided — zero or multiple → `{"error": "exactly one of wallet/condition_id/event_slug required"}`, counts as a used call. |
| 9 | `search_alerts_by_tag` | `tag: str, hours: int = 24, limit: int = 20` | Postgres `SELECT id, composite_score, wallet, market_title, total_usd, llm_headline, created_at FROM alerts WHERE tags::jsonb @> %s::jsonb AND created_at >= NOW() - (%s \|\| ' hours')::interval ORDER BY composite_score DESC LIMIT %s`. The `tags` column is `TEXT` storing a JSON array; casting to `jsonb` on each row works because all ingested values are valid JSON. Argument is a single tag string; the query passes `json.dumps([tag])` for the JSONB containment check. |

### polybot.db SQLite (6)

| # | Name | Args | Backing |
|---|---|---|---|
| 10 | `get_wallet_pnl_positions` | `wallet: str, limit: int = 20` | `SELECT condition_id, outcome, avg_price, total_bought, realized_pnl, cur_price, position_type, end_date FROM wallet_pnl WHERE wallet = ? ORDER BY (total_bought) DESC LIMIT ?` |
| 11 | `get_wallet_timing_pattern` | `wallet: str` | Uses existing `db.get_wallet_timing_stats(wallet, min_market_duration_hours=1.0)` |
| 12 | `get_wallet_event_history` | `wallet: str, event_slug: str` | Uses existing `db.get_wallet_event_history(wallet, event_slug)` |
| 13 | `get_funder_cluster` | `wallet: str` | `SELECT funder FROM wallet_funders WHERE wallet = ?` then `SELECT wallet FROM wallet_funders WHERE funder = ?` — returns `{funder, wallets}` |
| 14 | `get_orderbook_snapshot` | `condition_id: str` | `SELECT token_id, outcome, best_bid, best_ask, spread, bid_depth, ask_depth, mid_price, snapshot_at FROM orderbook_snapshots WHERE condition_id = ? ORDER BY snapshot_at DESC` — returns one row per outcome token |
| 15 | `get_market_volume_history` | `condition_id: str, limit: int = 50` | `SELECT volume_24h, snapshot_at FROM market_volume_snapshots WHERE condition_id = ? ORDER BY snapshot_at DESC LIMIT ?` |

### External (1)

| # | Name | Args | Backing |
|---|---|---|---|
| 16 | `call_gamma_api` | `path: str, params: dict \| None = None` | `GET https://gamma-api.polymarket.com{path}`. `path` must start with one of: `/markets`, `/events`, `/trades`. Disallowed paths return `{"error": "path not allowed"}`. |

### Tool schemas passed to the LLM

One JSON-schema object per tool in the `tools` param of the chat completions call. Each includes:

- `name`
- `description` — 1-2 sentences, one usage example with `projection` where relevant.
- `parameters` — JSON schema for args including the optional `projection` string.

The system prompt references the projection contract and lists 4-5 worked examples. Individual tool descriptions do *not* repeat the JMESPath primer — that would bloat the prompt.

## Input-payload fix

The current `_build_user_message()` in [backend/twitter_bot.py:204](../../../backend/twitter_bot.py#L204) passes only 10 fields. Without `condition_id` and `event_slug`, the model cannot call most of the tools.

**New per-alert payload:**

```
alert_id, composite_score, llm_headline, llm_summary, llm_bullets,
llm_copy_action, market_title, market_description, condition_id,
event_slug, wallet, wallet_win_rate, wallet_total_pnl, total_usd,
trade_count, tags, end_date
```

Fields omitted: `market_url`, `market_image` (model can't use URLs or images), `scanned_at`, `alert_type`, `cluster_headline` (covered by `llm_headline`), `created_at`.

`llm_copy_action` is an object; it's passed as-is (typically `{outcome, side, entry_price, max_price}`).

## System prompt (new)

Extends the current system prompt with:

### New sections (added before "Tweet rules")

> **You have research tools.** You can call up to **5** tools before writing the tweet — use them when digging deeper would sharpen the story. A good tweet cites a *specific* fact the alert payload doesn't already contain (e.g., "bought the Under at 0.35 — market now at 0.62", "this wallet's timing pattern: 17 late-market bets in 3 weeks", "volume 12x'd in the last 4 hours"). You don't have to use all 5. Zero calls is fine if the alerts already tell a tight story.
>
> **Every tool accepts an optional `projection` parameter** — a JMESPath expression applied to the result before it reaches you. Use it to ask narrow questions without pulling large blobs into context. Examples:
> - `length(bet_history)` — just a count
> - `{win_rate: win_rate, total_pnl: total_pnl}` — pick fields
> - `bet_history[?won==\`true\`].pnl_usd` — filtered list
> - `avg(bet_history[?won==\`true\`].entry_price)` — computed aggregate
>
> Bad projections return `{"error": "projection failed: ..."}` and still cost a tool call — so get them right. If you want to explore a tool's shape first, call it once without `projection` to see the full (8KB-capped) response.
>
> **Fabrication rule (unchanged):** never invent numbers. Only cite facts that came from the input alerts or tool responses in this conversation.

The existing "Tweet rules", "Single vs composite", "Skip criteria", and "Output format" sections carry over verbatim.

## Error handling

Extends the existing table in the parent spec:

| Failure | Behavior |
|---|---|
| Tool dispatcher raises (bug, not HTTP error) | Caught, returned as `{"error": "..."}`; model continues; counts toward budget |
| HTTP timeout / 5xx | Returned as `{"error": "http: ..."}`; counts toward budget |
| SQL query raises | Returned as `{"error": "sql: ..."}`; counts toward budget |
| JMESPath compile/eval fails | `{"error": "projection failed: ..."}`; counts toward budget |
| Response > 8KB after projection | Truncated, `truncated: true` flag set |
| `call_gamma_api` path not in allowlist | `{"error": "path not allowed"}`; counts toward budget |
| Model makes a 6th tool call in one turn | Dispatcher fills results up to 5, returns `{"error": "budget exhausted"}` for the rest in the same turn; next turn gets a forcing message |
| Model exhausts 5 and still asks for more | Forcing message injected: "Return final JSON now"; `tool_choice="none"` set |
| Agent exceeds MAX_ITERATIONS (7) without final JSON | `compose_tweet` raises `AgentOutputError`; outer `main()` logs `event=llm_error`, exit 1 |
| Final JSON malformed | Same as today — `event=llm_error`, exit 1 |
| Final tweet > 260 chars | Same as today — single length retry at the `call_llm` wrapper layer, wrapping the whole agent loop |

## Timeouts & caps

| Knob | Value | Rationale |
|---|---|---|
| HTTP tool timeout | 5s | Enough for the hosted API; short enough that a stuck tool doesn't burn the run |
| SQLite query timeout | 2s | SQLite on local disk; anything longer means something's wrong |
| Postgres query timeout | 5s | Hosted DB, modest latency tolerance |
| Response size cap | 8KB serialized | Fits in context; big enough for real content |
| Max tool calls per run | 5 | Hard limit |
| Max LLM iterations | 7 | 5 tool rounds + 1 forcing + 1 safety |
| LLM `max_completion_tokens` | 800 | Enough for reasoning + tool args; tweet itself is small |
| Final-tweet length | ≤ 260 chars | Unchanged from parent spec |

## Logging (new events)

Added to the existing structured JSON logs:

- `agent_start` — at the top of `compose_tweet`, logs the 5 alert ids seen.
- `tool_call` — per dispatched tool: `{tool, args_digest, ok, truncated, duration_ms}`. Full args are *not* logged (can be large / contain PII-like wallet addresses only).
- `tool_budget_exhausted` — logged once if the forcing message fires.
- `agent_end` — logs `{tool_calls_used, iterations, decision}`.

## Testing

`backend/test_twitter_bot_agent.py` — pytest style, fakes for `llm_client`, `http`, `db_conn_pg`, `db_conn_sqlite`.

### Core cases

1. **Zero tool calls** — LLM emits final JSON immediately. Output matches existing format.
2. **One tool call, success** — LLM calls `get_wallet_profile`, fake returns a profile, LLM composes tweet referencing a field.
3. **Projection, success** — LLM calls `get_wallet_profile(projection="length(bet_history)")`, fake applies projection, model uses the scalar in tweet copy.
4. **Projection, bad JMESPath** — model sends `projection="invalid(`; tool returns error; model retries without projection.
5. **Tool returns error (e.g., HTTP timeout)** — model sees `{"error": ...}`, recovers with a different tool or proceeds with existing data.
6. **Budget exhaustion via single turn** — LLM emits 6 tool calls in one message; dispatcher fills first 5, 6th gets `budget exhausted` error.
7. **Budget exhaustion across turns** — 5 successful tool calls over multiple turns; 6th-turn tool call triggers forcing message; final JSON emitted.
8. **Max iterations reached** — fake LLM always wants more tools; `compose_tweet` raises `AgentOutputError`.
9. **Response truncation** — fake tool returns a 10KB blob; envelope is capped at 8KB with `truncated: true`; model can still use it.
10. **Allowlist violation** — LLM calls `call_gamma_api(path="/admin")`; returns `{"error": "path not allowed"}`.
11. **Parallel tool calls in one turn** — 3 tool calls in one assistant message; all dispatched; results appear in conversation in a single follow-up.
12. **SQL tool with good data** — fake SQLite returns rows; tool assembles envelope; model uses it.

### Integration case (in `test_twitter_bot.py`)

- Existing end-to-end tests (1–12 in the parent spec) keep passing — the agent is swapped in for the LLM fake. One representative test explicitly exercises the "agent returns decision dict" shape to ensure `main()` is wired correctly.

### What we do NOT test here

- No live calls to Azure OpenAI, the hosted API, or Gamma.
- No real Postgres / SQLite — fakes only.
- No real Twitter calls — dry-run covers that per the parent spec.

## Rollout

1. Merge implementation to `main`.
2. Run on the local machine in dry-run mode (`TWITTER_BOT_DRY_RUN=true`) for 24 hours. Confirm tweets look good and tool-call patterns are reasonable.
3. Flip to live posting (`TWITTER_BOT_DRY_RUN=false`).

No Railway changes — per the parent spec update, the bot already runs as a local cron.

## Open questions

None — design locked.
