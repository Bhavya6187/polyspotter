# Twitter Bot — Two-Stage Alert Selection

**Date:** 2026-04-19
**Status:** Approved, pending implementation plan
**Supersedes section:** "Architecture" section of [2026-04-19-twitter-bot-agentic-composer-design.md](./2026-04-19-twitter-bot-agentic-composer-design.md) — specifically the single-call flow in `compose_tweet`.

## Goal

Split the composer's work into two LLM calls. Stage 1 reads all top-20 alerts and picks 2-4 worth turning into a tweet (or decides to skip the hour); stage 2 researches only the shortlisted alerts and writes the tweet. Same total tool budget, sharper focus per tool call, skipped hours don't pay for research.

## Motivation

In the current single-stage flow, the agent juggles 20 alerts and 10 tool calls at once. Observed in a dry-run trace (run `5779fa25`, 2026-04-19):

- Tool calls spread across two unrelated alerts (#96820 and #96829) — the agent investigated both before committing, wasting ~20% of its budget on the alert it ultimately didn't feature.
- The tweet featured alert #96820 (ranked 4th by score), not #96830 (ranked 1st). That's a legitimate editorial choice, but the agent had to both *make* that choice and *verify* its facts in one pass.

Two-stage separates the editorial decision (which alert tells the best story) from the investigative work (verifying and sharpening the story).

## Non-goals

- No fact-grounding / hallucination check — covered in a separate spec.
- No media / chart attachments — covered in a separate spec.
- No new endpoints, no schema changes, no new models.
- No change to the hourly cron cadence, fetch logic, dedup, or post/record paths.
- No env flag, no shadow mode. Straight replacement; the fallback path preserves "always get a tweet out" semantics.
- No change to total tool budget (stays at 10).

## Architecture

### New flow

```
fetch → dedup → top-20 by composite_score
  → select_shortlist (1 LLM call, no tools)
     ├── decision=skip       → exit, log llm_skip(stage=1)
     ├── decision=shortlist  → compose_tweet(shortlist)
     └── error/invalid       → fallback shortlist, log stage1_fallback
                                → compose_tweet(fallback)
  → compose_tweet (1 LLM loop, up to 10 tool calls, unchanged shape)
     ├── decision=skip   → exit, log llm_skip(stage=2)
     └── decision=post   → validate → post → record
```

### Stage 1 — `select_shortlist`

New public function in `backend/twitter_bot_agent.py`:

```python
def select_shortlist(top_alerts: list[dict], *, llm_client) -> ShortlistDecision
```

Pure function. No tools, no `ToolDeps`, no projection. Single `chat.completions.create` call with `response_format={"type": "json_object"}`.

**Input payload** (slimmer than stage-2's — stage 1 doesn't need trade details or copy actions):

- `alert_id`, `composite_score`, `llm_headline`, `llm_summary`, `wallet`, `wallet_win_rate`, `total_usd`, `market_title`, `tags`, `condition_id`, `event_slug`.
- Drops `llm_bullets`, `llm_copy_action`, `market_description`, `end_date`.

**Output** (validated JSON):

```json
{
  "decision": "shortlist" | "skip",
  "reason": "short string",
  "mode": "single" | "composite" | null,
  "shortlist": [
    {"alert_id": 96820, "angle": "20-0 wallet just sized up 25× their average bet"},
    {"alert_id": 96830, "angle": "new sharp wallet timing-clustered with two known whales"}
  ] | null
}
```

**Validation** (new function `validate_shortlist_decision`):

- `decision="skip"` → no other fields required. Skip the hour.
- `decision="shortlist"` requires `mode` ∈ {`single`, `composite`} and `shortlist` of length 2-4.
- Every `alert_id` in `shortlist` must appear in the input set.
- `composite` requires ≥2 shortlist items (reject size 1).
- `single` allows 2-4 (extras act as backups — stage 2 may pivot).
- Each `angle` must be a non-empty string.
- Violations raise `ShortlistValidationError`.

**System prompt** — editorial framing. Key points:

- "You're picking the 2-4 alerts most likely to make a great tweet, not just the highest-scoring."
- "Pick the fewest that work — 2 if one clear story plus one backup, 3-4 if torn."
- "Only choose `mode=composite` if the alerts share a wallet, market, event, or tight thematic link. Never force synthesis."
- "An `angle` is one short sentence: the *story* you'd tell, not a recap of the headline."
- "If nothing is compelling, return `decision=skip` with a short reason."

`max_completion_tokens=400` (output is small), `temperature=0.7`, same model `gpt-5.4`.

### Stage 2 — `compose_tweet` (modified)

Existing function gains one required kwarg:

```python
def compose_tweet(
    top_alerts: list[dict],
    *,
    llm_client,
    deps: ToolDeps,
    shortlist_decision: ShortlistDecision,
    on_tool_call=None,
) -> dict
```

**Behavior changes:**

1. Filters `top_alerts` down to shortlisted IDs before building the user message.
2. User message gains a new top-level field: `selection: {"mode": "single"|"composite", "angles": {"<alert_id>": "<angle>", ...}}`.
3. System prompt is trimmed (see below).
4. Tool budget unchanged at 10. With fewer alerts to research, per-alert depth naturally increases.

**System prompt edits:**

- Remove the "Single vs composite" section — that decision is now made upstream.
- Add a "Selection context" paragraph: *"Stage 1 shortlisted these alerts and suggested an angle for each. Verify and sharpen those angles via tools, or pivot to a stronger one you discover during research. If `mode=composite`, your tweet must reference all shortlisted alerts. If `mode=single`, pick one to feature — the others are backups."*

**Validation (`validate_decision`)** — signature changes from `validate_decision(decision, top_alert_ids)` to `validate_decision(decision, shortlisted_ids, mode)`:

- `top_alert_ids` is replaced by `shortlisted_ids` — posted `alert_ids` must be drawn from the shortlist only, not the full top-20.
- If `mode=composite`: posted `alert_ids` set must equal `shortlisted_ids` (order-insensitive), and `decision["is_composite"]` must be `true`.
- If `mode=single`: posted `alert_ids` must have length 1, must be ∈ `shortlisted_ids`, and `decision["is_composite"]` must be `false`.
- Skip decisions short-circuit as today (no ID/mode check).
- Violations return `(False, error_message)` as today.

### Orchestration — `twitter_bot.py`

`call_llm()`'s return shape changes from `dict` to `tuple[ShortlistDecision, dict]`. It now:

1. Calls `select_shortlist(top_alerts, llm_client=...)`. Emits `stage1_start` and `stage1_result` events.
2. On `decision=skip` → returns `(shortlist_decision, {"decision": "skip", "reason": shortlist_decision.reason})`. `main()`'s existing skip branch handles the outer dict; stage 1's skip reason is preserved for logging.
3. On validation failure or exception → emits `stage1_invalid` (if validation) and `stage1_fallback`, builds a fallback `ShortlistDecision`, proceeds.
4. Calls `compose_tweet(top_alerts, llm_client=..., deps=..., shortlist_decision=..., on_tool_call=...)`.
5. Applies the existing 260-char length retry (unchanged).
6. Returns `(shortlist_decision, compose_decision)`.

`main()`:

- Unpacks the tuple.
- Passes `shortlist_decision.mode` and the shortlisted ID set into `validate_decision`.
- Logs `stage1_mode` and `stage1_fallback` in `run_end` (see Telemetry).

### Fallback shortlist

On any stage-1 failure — non-JSON output, `ShortlistValidationError`, LLM exception, `alert_ids` not in input:

- Top 3 alerts by `composite_score` from the input.
- `mode = "single"`, empty `angles: {}`.
- Stage 2 sees no angles and treats it as "investigate from scratch" — its prompt covers that case already via the pivot clause.
- Logged as `stage1_fallback` with the truncated error string.

If fewer than 3 alerts are in the input (edge case — dedup removed most), fallback shortlists whatever is there with `mode=single`.

## Telemetry

New `log_event` events in `twitter_bot.py`:

- `stage1_start` — `run_id`, `input_count`.
- `stage1_result` — `run_id`, `decision`, `mode`, `shortlist_ids`, `reason`.
- `stage1_fallback` — `run_id`, `error` (truncated to 500 chars).
- `stage1_invalid` — `run_id`, `validation_error`, `raw_output` (truncated to 500 chars). Emitted *before* `stage1_fallback`.

Existing events:

- `llm_skip` gains a `stage: 1 | 2` field.
- `llm_error` gains a `stage: 1 | 2` field.
- `run_end` gains two fields: `stage1_mode` (value from the `ShortlistDecision` — `"single"` | `"composite"` | `"skip"`; on fallback this is `"single"` since the fallback decision is single-mode) and `stage1_fallback: bool` (distinguishes a real skip/shortlist from a fallback-constructed one).

## Dry-run output

Between the existing "Top N candidates" block and the tool-call trace, insert:

```
--- Stage 1 selection: composite (3 alerts) ---
  → reason: 3-wallet cluster all loaded the same tennis market in the last 40 min
  #96827  0x...c003  $6,096  tennis cluster — 3 shared-funder wallets loaded in
  #96820  0xad2b...  $52k    verify 20-0 record and lifetime PnL against profile
  #96830  0x7a8f...  $1,035  new wallet under 24h old, 5-min window before close
```

On skip: `--- Stage 1 skip: <reason> ---` and no further output.
On fallback: `--- Stage 1 fallback: <error> — using top-3 by score ---` then the fallback shortlist.

## Testing

Extend the existing `backend/test_twitter_bot_agent.py` and `backend/test_twitter_bot.py`:

**`backend/test_twitter_bot_agent.py` — stage 1:**
- `select_shortlist` happy paths with stubbed `llm_client`: skip, single-mode 2/3/4 items, composite-mode 2/3 items.
- Validation errors: invalid JSON, mode missing on `shortlist`, shortlist size 1 (composite), shortlist size 5, `alert_id` not in input, empty `angle`.
- `compose_tweet` with injected `ShortlistDecision`: user message contains `selection.mode` + angles, only shortlisted alerts are included.

**`backend/test_twitter_bot.py` — orchestration:**
- `main()` with stubbed LLM returning stage-1 skip: exits 0, no stage-2 call, no post, `llm_skip` event has `stage=1`.
- `main()` with stage-1 throwing: `stage1_fallback` logged, stage 2 runs, tweet posted.
- `main()` happy path (stage 1 shortlists → stage 2 posts): verify `run_end` has `stage1_mode` and `stage1_fallback=false`.
- `validate_decision` composite mode: rejects when posted `alert_ids` != shortlisted set.
- `validate_decision` single mode: rejects when posted `alert_ids` not in shortlisted set.

## Files changed

- `backend/twitter_bot_agent.py` — add `select_shortlist`, `ShortlistDecision` dataclass, `validate_shortlist_decision`, `ShortlistValidationError`, stage-1 system prompt. Update `build_user_message` to accept optional `selection`. Update `compose_tweet` signature. Trim stage-2 system prompt.
- `backend/twitter_bot.py` — update `call_llm` to orchestrate stage 1 → stage 2. Update `validate_decision` to accept `mode`. Update `main` to pass mode into validation and log new fields. Update dry-run output block.
- `backend/test_twitter_bot_agent.py` — extended.
- `backend/test_twitter_bot.py` — extended.

## Open questions

None — all resolved in brainstorming session 2026-04-19.
