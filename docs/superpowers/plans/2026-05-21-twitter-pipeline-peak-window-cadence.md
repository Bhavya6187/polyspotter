# Twitter Pipeline Peak-Window Cadence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `twitter_pipeline.py` self-gate so it only drafts a tweet inside known peak ET windows, at most once per window and twice per ET day.

**Architecture:** Add four pure, unit-testable helper functions to `twitter_pipeline.py` (peak-window lookup, two post-count helpers, and a combining gate function). Wire the gate into `main()` before any seed fetch or LLM call, so most hourly wake-ups skip cheaply. Change the loop script to wake hourly instead of every 5 hours. No content/prompt changes.

**Tech Stack:** Python 3.13 (`zoneinfo` for DST-correct ET conversion), `pytest`, bash.

---

## Context for the engineer

`storybot/twitter_pipeline.py` is a 4-stage LLM bot that drafts one tweet per
run. `storybot/run_twitter_pipeline_loop.sh` runs it on a timer, then has
Claude edit the draft and `publish_tweet.py` post it.

The bot currently posts ~3–5 tweets/day at whatever hour the 5h timer fires.
The account has a reach problem: posts land in empty feeds at bad hours and
flop, which suppresses later posts. The fix is cadence, not wording — post
~1–2/day, only when the US audience is online.

`twitter_pipeline.py` already has `from datetime import datetime, timezone`
at the top, a working `_parse_iso(value)` helper (parses a timestamp string
or `datetime` into an aware `datetime`, or `None`), a module-level
`DRY_RUN` boolean, and a `log(event, **fields)` structured logger imported
from `bot_utils` inside `main()`. Reuse all of these — do not reimplement.

`fetch_recent_tweets(limit=10)` (from `storybot/tweet_utils.py`) returns the
last ~10 posted tweets as dicts: `{"tweet": str, "condition_ids": list,
"tweeted_at": iso-str-or-None}`, newest first.

Test import pattern (see `test/test_twitter_pipeline_quality_floor.py`):
```python
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402
```

Run all scanner tests with `pytest` from the repo root (venv activated:
`source venv/bin/activate`).

---

## Task 1: Peak-window constants and `_current_peak_window`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (add import + constants + function)
- Test: `test/test_twitter_pipeline_cadence.py` (create)

- [ ] **Step 1: Write the failing test**

Create `test/test_twitter_pipeline_cadence.py`:

```python
"""Tests for the peak-window cadence gate applied at the top of main().

The gate keeps the bot posting ~1-2 tweets/day, only inside peak ET windows,
at most once per window. All helpers are pure (now + recent_tweets in).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import twitter_pipeline  # noqa: E402


def _tw(iso):
    """A minimal recent-tweet row — only tweeted_at matters to the gate."""
    return {"tweet": "x", "condition_ids": [], "tweeted_at": iso}


# --- _current_peak_window -------------------------------------------------

def test_current_peak_window_morning_est():
    # Jan 15 2026 14:00 UTC = 09:00 ET (EST, UTC-5) — inside morning [8,10).
    now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_evening_est():
    # Jan 16 2026 00:00 UTC = 19:00 ET Jan 15 (EST) — inside evening [18,22).
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "evening"


def test_current_peak_window_outside_overnight():
    # Jan 15 2026 08:00 UTC = 03:00 ET — no window.
    now = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) is None


def test_current_peak_window_between_windows():
    # Jan 15 2026 16:00 UTC = 11:00 ET — between morning and midday.
    now = datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) is None


def test_current_peak_window_dst_discriminator_summer():
    # Jul 15 2026 12:30 UTC: EDT (UTC-4) = 08:30 ET -> morning.
    # A fixed UTC-5 impl would compute 07:30 ET -> None. Proves DST handling.
    now = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_dst_discriminator_winter():
    # Jan 15 2026 14:30 UTC: EST (UTC-5) = 09:30 ET -> morning.
    # A fixed UTC-4 impl would compute 10:30 ET -> None. Proves DST handling.
    now = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
    assert twitter_pipeline._current_peak_window(now) == "morning"


def test_current_peak_window_naive_treated_as_utc():
    now = datetime(2026, 1, 15, 14, 0)  # naive -> assumed UTC -> 09:00 ET
    assert twitter_pipeline._current_peak_window(now) == "morning"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_twitter_pipeline_cadence.py -v`
Expected: FAIL — `AttributeError: module 'twitter_pipeline' has no attribute '_current_peak_window'`

- [ ] **Step 3: Add the import**

In `storybot/twitter_pipeline.py`, find the line:
```python
from datetime import datetime, timezone
```
Add immediately below it:
```python
from zoneinfo import ZoneInfo
```

- [ ] **Step 4: Add constants and the function**

In `storybot/twitter_pipeline.py`, immediately after the `_parse_iso`
function (it ends with `return None` followed by a blank line), insert:

```python
# --- Cadence gate ---------------------------------------------------------
# The bot has a reach problem: posts that land in an empty feed at a bad
# hour flop, and flops suppress later posts. The fix is cadence — draft only
# inside peak ET windows, at most once per window and DAILY_POST_CAP per day.
# All helpers below are pure (now + recent_tweets in) so they unit-test
# cleanly; main() calls _cadence_skip_reason and skips before any LLM work.

# Audience is US sports/politics/crypto. Windows are defined in ET so DST
# shifts apply automatically via zoneinfo.
_AUDIENCE_TZ = ZoneInfo("America/New_York")

# Peak posting windows as half-open [start_hour, end_hour) ranges in ET.
PEAK_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (8, 10),
    "midday": (12, 14),
    "evening": (18, 22),
}

# Max tweets per ET calendar day. Three windows, cap of 2 -> at most two used.
DAILY_POST_CAP = 2


def _current_peak_window(now: datetime) -> str | None:
    """Return the PEAK_WINDOWS id `now` falls in (evaluated in ET), or None
    if `now` is outside every window.

    A naive `now` is assumed to be UTC. Conversion to ET goes through
    zoneinfo so daylight-saving shifts are handled correctly.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hour = now.astimezone(_AUDIENCE_TZ).hour
    for window_id, (start, end) in PEAK_WINDOWS.items():
        if start <= hour < end:
            return window_id
    return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest test/test_twitter_pipeline_cadence.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 6: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_cadence.py
git commit -m "$(cat <<'EOF'
twitter: add peak-window constants and _current_peak_window

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_posts_today`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (add function)
- Test: `test/test_twitter_pipeline_cadence.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `test/test_twitter_pipeline_cadence.py`:

```python
# --- _posts_today ---------------------------------------------------------

def test_posts_today_counts_same_et_day():
    # now = Jan 15 2026 18:00 UTC = 13:00 ET Jan 15.
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    recent = [
        _tw("2026-01-15T14:00:00+00:00"),  # 09:00 ET Jan 15 — today
        _tw("2026-01-15T20:00:00+00:00"),  # 15:00 ET Jan 15 — today
        _tw("2026-01-14T20:00:00+00:00"),  # 15:00 ET Jan 14 — yesterday
    ]
    assert twitter_pipeline._posts_today(recent, now) == 2


def test_posts_today_ignores_bad_or_missing_timestamp():
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    recent = [_tw(None), _tw("not-a-date"), {"tweet": "x"}]
    assert twitter_pipeline._posts_today(recent, now) == 0


def test_posts_today_empty():
    now = datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    assert twitter_pipeline._posts_today([], now) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_twitter_pipeline_cadence.py -k posts_today -v`
Expected: FAIL — `AttributeError: ... has no attribute '_posts_today'`

- [ ] **Step 3: Write the function**

In `storybot/twitter_pipeline.py`, immediately after `_current_peak_window`
(after its `return None`), insert:

```python
def _posts_today(recent_tweets: list[dict], now: datetime) -> int:
    """Count tweets in `recent_tweets` posted on the same ET calendar day as
    `now`. Rows with a missing or unparseable `tweeted_at` are ignored."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(_AUDIENCE_TZ).date()
    count = 0
    for row in recent_tweets or []:
        dt = _parse_iso(row.get("tweeted_at"))
        if dt is None:
            continue
        if dt.astimezone(_AUDIENCE_TZ).date() == today:
            count += 1
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_twitter_pipeline_cadence.py -k posts_today -v`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_cadence.py
git commit -m "$(cat <<'EOF'
twitter: add _posts_today ET-day post counter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `_posts_in_window`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (add function)
- Test: `test/test_twitter_pipeline_cadence.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `test/test_twitter_pipeline_cadence.py`:

```python
# --- _posts_in_window -----------------------------------------------------

def test_posts_in_window_counts_same_window_same_day():
    # now = Jan 16 00:00 UTC = 19:00 ET Jan 15 (evening).
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    recent = [_tw("2026-01-15T23:30:00+00:00")]  # 18:30 ET Jan 15 — evening
    assert twitter_pipeline._posts_in_window(recent, "evening", now) == 1


def test_posts_in_window_excludes_other_window():
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)  # 19:00 ET Jan 15
    recent = [_tw("2026-01-15T14:00:00+00:00")]  # 09:00 ET Jan 15 — morning
    assert twitter_pipeline._posts_in_window(recent, "evening", now) == 0


def test_posts_in_window_excludes_prior_day_same_window():
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)  # 19:00 ET Jan 15
    recent = [_tw("2026-01-15T00:00:00+00:00")]  # 19:00 ET Jan 14 — prior day
    assert twitter_pipeline._posts_in_window(recent, "evening", now) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_twitter_pipeline_cadence.py -k posts_in_window -v`
Expected: FAIL — `AttributeError: ... has no attribute '_posts_in_window'`

- [ ] **Step 3: Write the function**

In `storybot/twitter_pipeline.py`, immediately after `_posts_today`
(after its `return count`), insert:

```python
def _posts_in_window(recent_tweets: list[dict], window: str,
                     now: datetime) -> int:
    """Count tweets in `recent_tweets` posted inside `window`'s ET hour block
    on the same ET calendar day as `now`. `window` must be a PEAK_WINDOWS
    key. Rows with a missing or unparseable `tweeted_at` are ignored."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start, end = PEAK_WINDOWS[window]
    today = now.astimezone(_AUDIENCE_TZ).date()
    count = 0
    for row in recent_tweets or []:
        dt = _parse_iso(row.get("tweeted_at"))
        if dt is None:
            continue
        et = dt.astimezone(_AUDIENCE_TZ)
        if et.date() == today and start <= et.hour < end:
            count += 1
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_twitter_pipeline_cadence.py -k posts_in_window -v`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_cadence.py
git commit -m "$(cat <<'EOF'
twitter: add _posts_in_window per-window post counter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `_cadence_skip_reason`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (add function)
- Test: `test/test_twitter_pipeline_cadence.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `test/test_twitter_pipeline_cadence.py`:

```python
# --- _cadence_skip_reason -------------------------------------------------

def test_cadence_skip_reason_outside_window():
    now = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)  # 03:00 ET
    assert (twitter_pipeline._cadence_skip_reason(now, [])
            == "outside peak window")


def test_cadence_skip_reason_proceeds_when_clear():
    now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)  # 09:00 ET morning
    assert twitter_pipeline._cadence_skip_reason(now, []) is None


def test_cadence_skip_reason_daily_cap():
    now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)  # 09:00 ET morning
    recent = [
        _tw("2026-01-15T13:00:00+00:00"),  # 08:00 ET Jan 15
        _tw("2026-01-15T18:00:00+00:00"),  # 13:00 ET Jan 15
    ]
    assert (twitter_pipeline._cadence_skip_reason(now, recent)
            == "daily cap reached")


def test_cadence_skip_reason_window_already_used():
    now = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)  # 09:30 ET morning
    recent = [_tw("2026-01-15T13:30:00+00:00")]  # 08:30 ET Jan 15 — morning
    assert (twitter_pipeline._cadence_skip_reason(now, recent)
            == "already posted in morning")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_twitter_pipeline_cadence.py -k cadence_skip_reason -v`
Expected: FAIL — `AttributeError: ... has no attribute '_cadence_skip_reason'`

- [ ] **Step 3: Write the function**

In `storybot/twitter_pipeline.py`, immediately after `_posts_in_window`
(after its `return count`), insert:

```python
def _cadence_skip_reason(now: datetime,
                         recent_tweets: list[dict]) -> str | None:
    """Return a human-readable skip reason if the cadence gate should block
    this run, or None to proceed.

    Checks, in order: outside every peak window -> DAILY_POST_CAP reached
    for the ET day -> this window already used. DRY_RUN bypassing is the
    caller's responsibility, not this function's.
    """
    window = _current_peak_window(now)
    if window is None:
        return "outside peak window"
    if _posts_today(recent_tweets, now) >= DAILY_POST_CAP:
        return "daily cap reached"
    if _posts_in_window(recent_tweets, window, now) >= 1:
        return f"already posted in {window}"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest test/test_twitter_pipeline_cadence.py -v`
Expected: PASS — all 17 tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py test/test_twitter_pipeline_cadence.py
git commit -m "$(cat <<'EOF'
twitter: add _cadence_skip_reason gate combiner

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire the cadence gate into `main()`

**Files:**
- Modify: `storybot/twitter_pipeline.py` (`main()` — insert gate, relocate `recent_tweets` fetch)

This task moves the `recent_tweets` fetch earlier and adds the gate. There
is no new unit test — the gate logic is already covered by Task 4; this is
integration wiring, verified by the full suite plus a `DRY_RUN` smoke run.

- [ ] **Step 1: Insert the gate block**

In `main()`, find this block (it appears once, just before the `# Seed`
comment):

```python
    usage_totals: dict = {}
    run_start_t = time.monotonic()
    transcript: dict = {"run_id": run_id, "stages": {}}

    # Seed
    t = time.monotonic()
```

Replace it with:

```python
    usage_totals: dict = {}
    run_start_t = time.monotonic()
    transcript: dict = {"run_id": run_id, "stages": {}}

    # Cadence gate — draft only inside a peak ET window, at most once per
    # window and DAILY_POST_CAP times per ET day. Most hourly wake-ups skip
    # here, before the seed fetch and any LLM call. DRY_RUN bypasses the
    # gate so previews run at any hour. recent_tweets is fetched here (it
    # used to be fetched after the quality floor) and threaded into the
    # event picker and the stage-4 validator unchanged.
    now = datetime.now(timezone.utc)
    recent_tweets = fetch_recent_tweets(limit=10)
    log("recent_tweets_loaded", run_id=run_id, count=len(recent_tweets))
    if not DRY_RUN:
        skip_reason = _cadence_skip_reason(now, recent_tweets)
        log("cadence_gate", run_id=run_id,
            window=_current_peak_window(now),
            posts_today=_posts_today(recent_tweets, now),
            skip_reason=skip_reason)
        if skip_reason:
            log("skip", run_id=run_id, reason=skip_reason)
            log("run_end", run_id=run_id, drafted=False,
                elapsed_ms=int((time.monotonic() - run_start_t) * 1000))
            return 0

    # Seed
    t = time.monotonic()
```

- [ ] **Step 2: Remove the now-duplicate `recent_tweets` fetch**

Still in `main()`, find and delete this block (it sits between the
quality-floor `return 0` and the `# Stage 1` comment):

```python
    # Recent tweets — shown to the event picker (and validator) so we don't
    # re-cover an event we just tweeted. Pull this BEFORE stage 1 since the
    # picker needs it; the same list is reused by stage 4's validator.
    recent_tweets = fetch_recent_tweets(limit=10)
    log("recent_tweets_loaded", run_id=run_id, count=len(recent_tweets))

```

After deletion, the quality-floor block's `return 0` line is followed
directly by a blank line and then `    # Stage 1`.

- [ ] **Step 3: Verify no regressions in the full scanner suite**

Run: `pytest`
Expected: PASS — the whole suite green, including the existing
`test/test_twitter_pipeline_*.py` files and the new
`test/test_twitter_pipeline_cadence.py`.

- [ ] **Step 4: Smoke-test a DRY_RUN (gate bypassed)**

Run: `DRY_RUN=true python storybot/twitter_pipeline.py`
Expected: the run proceeds past the gate regardless of the current hour —
the log shows `recent_tweets_loaded` but no `cadence_gate` line and no
`skip` with a cadence reason. The run ends as it did before this change
(either a `skip` from the event picker / quality floor, or a drafted tweet).

- [ ] **Step 5: Commit**

```bash
git add storybot/twitter_pipeline.py
git commit -m "$(cat <<'EOF'
twitter: gate main() on peak-window cadence before LLM work

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Loop wakes hourly

**Files:**
- Modify: `storybot/run_twitter_pipeline_loop.sh`

- [ ] **Step 1: Change the interval default**

In `storybot/run_twitter_pipeline_loop.sh`, find:

```bash
INTERVAL_SECONDS="${INTERVAL_SECONDS:-18000}"  # 5 hours
```

Replace with:

```bash
INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"  # 1 hour
```

- [ ] **Step 2: Update the header comment**

In the same file, find this comment block near the top:

```bash
# Runs storybot/twitter_pipeline.py every 5 hours, then has Claude Code
# review/edit the draft, then publishes via storybot/publish_tweet.py.
# Five hours of wake-up gap yields ~4-5 wake-ups per day; with the picker
# skipping duplicate or weak-story windows, the actual ship rate lands in
# the 3-5 tweets/day target.
```

Replace it with:

```bash
# Runs storybot/twitter_pipeline.py hourly, then has Claude Code review/edit
# the draft, then publishes via storybot/publish_tweet.py.
# The pipeline self-gates on a cadence window (see _cadence_skip_reason in
# storybot/twitter_pipeline.py): it only drafts inside peak ET windows, at
# most once per window and twice per ET day. Most hourly wake-ups skip
# immediately, before any LLM call; the ship rate lands at ~1-2 tweets/day.
```

- [ ] **Step 3: Verify the script still parses**

Run: `bash -n storybot/run_twitter_pipeline_loop.sh`
Expected: no output, exit code 0 (syntax OK).

- [ ] **Step 4: Commit**

```bash
git add storybot/run_twitter_pipeline_loop.sh
git commit -m "$(cat <<'EOF'
twitter: loop wakes hourly so the cadence gate can pick peak windows

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done

After Task 6 the bot drafts only inside peak ET windows, at most once per
window and twice per ET day; the loop wakes hourly and most wake-ups skip
before any LLM call. Verify the whole suite once more with `pytest`.
