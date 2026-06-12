# Twitter Receipts Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live accountability loop's receipts visible and measurable: result tweets quote-tweet the original flag, flag tweets carry a track-record closer, the curated record converges to the 0.8 win bias, a weekly scoreboard tweet ships Sundays, and follower count is snapshotted daily.

**Architecture:** Five small deltas to the existing storybot pipelines (`twitter_pipeline.py` flag bot, `result_pipeline.py` + `publish_result.py` settle bot). Two new Postgres tables (`weekly_scoreboards`, `follower_snapshots`) accessed through `result_store.py`'s `_run` seam. No new daemons — everything rides the existing hourly screen-session loops.

**Tech Stack:** Python 3.13, tweepy 4.16 (X API v2 writes, free tier), psycopg2/Postgres (Railway, `DATABASE_URL` in `.env`), matplotlib via `charts.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-twitter-receipts-visibility-design.md`

**Conventions for every task:**
- Work from repo root `/home/bhavya/git/polybot` with `source venv/bin/activate`.
- Scanner/storybot tests run as plain `pytest test/<file> -v` from repo root (test files do `sys.path.insert` of `storybot/` themselves).
- All storybot modules import each other flat (`import result_store`, not `import storybot.result_store`).
- `bot_utils.log(event, **fields)` emits one JSON line; use it for all new logging.

---

### Task 0: Branch

**Files:** none

- [ ] **Step 1: Create the feature branch**

```bash
cd /home/bhavya/git/polybot
git checkout main && git pull
git checkout -b feat/twitter-receipts-visibility
```

---

### Task 1: New Postgres tables (schema + apply)

**Files:**
- Modify: `backend/schema.sql` (append after the `idx_result_tweets_posted_at` index, around line 223)

- [ ] **Step 1: Append the two table definitions to `backend/schema.sql`**

Add directly below the `CREATE INDEX IF NOT EXISTS idx_result_tweets_posted_at ...;` statement:

```sql
-- weekly_scoreboards: one row per ISO week we've posted a Sunday scoreboard
-- tweet for. PK doubles as the once-per-week dedup guard.
CREATE TABLE IF NOT EXISTS weekly_scoreboards (
    iso_week    TEXT PRIMARY KEY,            -- e.g. '2026-W24'
    tweet_id    TEXT,
    n_cashed    INTEGER NOT NULL DEFAULT 0,
    n_burned    INTEGER NOT NULL DEFAULT 0,
    net_pl_usd  NUMERIC NOT NULL DEFAULT 0,
    posted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- follower_snapshots: one row per ET calendar day; free-tier get_me() read.
-- Gives the follower trend line the growth work is judged against.
CREATE TABLE IF NOT EXISTS follower_snapshots (
    snapshot_date    DATE PRIMARY KEY,       -- ET calendar date
    followers_count  INTEGER NOT NULL,
    tweet_count      INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Apply the two tables to the Railway Postgres**

```bash
source venv/bin/activate
python - <<'EOF'
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS weekly_scoreboards (
    iso_week    TEXT PRIMARY KEY,
    tweet_id    TEXT,
    n_cashed    INTEGER NOT NULL DEFAULT 0,
    n_burned    INTEGER NOT NULL DEFAULT 0,
    net_pl_usd  NUMERIC NOT NULL DEFAULT 0,
    posted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS follower_snapshots (
    snapshot_date    DATE PRIMARY KEY,
    followers_count  INTEGER NOT NULL,
    tweet_count      INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")
conn.commit()
cur.execute("SELECT to_regclass('weekly_scoreboards'), to_regclass('follower_snapshots')")
print("created:", cur.fetchone())
conn.close()
EOF
```

Expected output: `created: ('weekly_scoreboards', 'follower_snapshots')`

- [ ] **Step 3: Commit**

```bash
git add backend/schema.sql
git commit -m "feat(schema): weekly_scoreboards + follower_snapshots tables"
```

---

### Task 2: `result_store` follower-snapshot helpers (Delta 5, storage)

**Files:**
- Modify: `storybot/result_store.py` (append at end of file)
- Test: `test/test_result_store.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_result_store.py`:

```python
def test_follower_snapshot_exists_true_when_row(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [{"?column?": 1}])
    from datetime import date
    assert rs.follower_snapshot_exists(date(2026, 6, 11)) is True


def test_follower_snapshot_exists_false_when_empty(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [])
    from datetime import date
    assert rs.follower_snapshot_exists(date(2026, 6, 11)) is False


def test_record_follower_snapshot_uses_conflict_do_nothing(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    from datetime import date
    rs.record_follower_snapshot(snapshot_date=date(2026, 6, 11),
                                followers_count=73, tweet_count=385)
    assert "ON CONFLICT (snapshot_date) DO NOTHING" in captured["query"]
    assert captured["params"] == (date(2026, 6, 11), 73, 385)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_result_store.py -v`
Expected: the three new tests FAIL with `AttributeError: ... has no attribute 'follower_snapshot_exists'`

- [ ] **Step 3: Implement in `storybot/result_store.py`**

Append at end of file (note: `date` is needed — extend the existing datetime import line `from datetime import datetime, timedelta, timezone` to `from datetime import date, datetime, timedelta, timezone`):

```python
# --- Follower snapshots (free-tier growth measurement) ----------------------

def follower_snapshot_exists(snapshot_date: date) -> bool:
    """True if we've already snapshotted follower count for this ET date."""
    rows = _run(
        "SELECT 1 FROM follower_snapshots WHERE snapshot_date = %s LIMIT 1",
        (snapshot_date,), fetch=True,
    )
    return bool(rows)


def record_follower_snapshot(*, snapshot_date: date, followers_count: int,
                             tweet_count: int) -> None:
    """Insert (or no-op on duplicate) one daily follower-count snapshot."""
    _run(
        """
        INSERT INTO follower_snapshots
            (snapshot_date, followers_count, tweet_count)
        VALUES (%s, %s, %s)
        ON CONFLICT (snapshot_date) DO NOTHING
        """,
        (snapshot_date, int(followers_count), int(tweet_count)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_result_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/result_store.py test/test_result_store.py
git commit -m "feat(result_store): follower_snapshots helpers"
```

---

### Task 3: Daily follower snapshot in the result loop (Delta 5, wiring)

**Files:**
- Modify: `storybot/result_pipeline.py`
- Test: `test/test_follower_snapshot.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `test/test_follower_snapshot.py`:

```python
"""Tests for result_pipeline.maybe_snapshot_followers (Delta 5)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_pipeline as rp  # noqa: E402

NOW = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)  # 2pm ET


def _fake_client(followers=73, tweets=385):
    metrics = {"followers_count": followers, "tweet_count": tweets}
    return SimpleNamespace(
        get_me=lambda user_fields: SimpleNamespace(
            data=SimpleNamespace(public_metrics=metrics)))


def test_snapshot_skips_when_row_exists(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: True)
    called = {"client": False}
    monkeypatch.setattr(rp, "_build_twitter_client",
                        lambda: called.__setitem__("client", True))
    rp.maybe_snapshot_followers(NOW)
    assert called["client"] is False  # no API call when already snapshotted


def test_snapshot_records_on_first_run_of_day(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: False)
    monkeypatch.setattr(rp, "_build_twitter_client", _fake_client)
    captured = {}
    monkeypatch.setattr(rp.result_store, "record_follower_snapshot",
                        lambda **kw: captured.update(kw))
    rp.maybe_snapshot_followers(NOW)
    assert captured["followers_count"] == 73
    assert captured["tweet_count"] == 385
    assert str(captured["snapshot_date"]) == "2026-06-11"


def test_snapshot_never_raises(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: False)

    def boom():
        raise RuntimeError("api down")
    monkeypatch.setattr(rp, "_build_twitter_client", boom)
    rp.maybe_snapshot_followers(NOW)  # must not raise


def test_snapshot_noop_in_dry_run(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", True)
    called = {"exists": False}
    monkeypatch.setattr(rp.result_store, "follower_snapshot_exists",
                        lambda d: called.__setitem__("exists", True) or False)
    rp.maybe_snapshot_followers(NOW)
    assert called["exists"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_follower_snapshot.py -v`
Expected: FAIL with `AttributeError: module 'result_pipeline' has no attribute 'maybe_snapshot_followers'`

- [ ] **Step 3: Implement in `storybot/result_pipeline.py`**

3a. Extend the datetime import (line 27) from
`from datetime import datetime, timezone` to:

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
```

3b. Below the imports from `bot_utils` (after line 51), add the tweet_utils import (mirrors `publish_result.py`):

```python
from tweet_utils import _build_twitter_api_v1, _build_twitter_client, post_tweet
```

3c. Below the `DRY_RUN = ...` block (after line 58), add:

```python
_AUDIENCE_TZ = ZoneInfo("America/New_York")
```

3d. Add the function just above `def main() -> int:` (the `# --- Entry point ---` marker):

```python
def maybe_snapshot_followers(now: datetime) -> None:
    """Once per ET day, snapshot the account's follower count via the
    free-tier get_me() read. Never raises — measurement must not break
    the settle run. No-op in DRY_RUN (no API call, no DB write)."""
    try:
        if DRY_RUN:
            return
        today_et = now.astimezone(_AUDIENCE_TZ).date()
        if result_store.follower_snapshot_exists(today_et):
            return
        me = _build_twitter_client().get_me(user_fields=["public_metrics"])
        pm = getattr(me.data, "public_metrics", None) or {}
        followers = int(pm.get("followers_count") or 0)
        result_store.record_follower_snapshot(
            snapshot_date=today_et,
            followers_count=followers,
            tweet_count=int(pm.get("tweet_count") or 0))
        log("follower_snapshot", date=str(today_et), followers=followers)
    except Exception as exc:
        log("follower_snapshot_error", error=f"{type(exc).__name__}: {exc}")
```

3e. Wire into `main()`: directly after the line `now = datetime.now(timezone.utc)` (just before `posted_today = result_store.todays_posted_outcomes(now)`), add:

```python
    maybe_snapshot_followers(now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_follower_snapshot.py test/test_result_selection.py test/test_result_pl_and_validation.py -v`
Expected: all PASS (the latter two confirm the new imports didn't break the module)

- [ ] **Step 5: Commit**

```bash
git add storybot/result_pipeline.py test/test_follower_snapshot.py
git commit -m "feat(result_pipeline): daily follower snapshot via free-tier get_me"
```

---

### Task 4: `post_tweet` learns `quote_tweet_id` (Delta 1, transport)

**Files:**
- Modify: `storybot/tweet_utils.py:488-517` (`post_tweet`)
- Test: `test/test_post_tweet_quote.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `test/test_post_tweet_quote.py`:

```python
"""post_tweet quote_tweet_id plumbing (Delta 1)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import tweet_utils as tu  # noqa: E402


class FakeClient:
    def __init__(self):
        self.kwargs = None

    def create_tweet(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(data={"id": "555"})


def test_quote_tweet_id_passed_through():
    fc = FakeClient()
    tid = tu.post_tweet("hello", twitter_client=fc, twitter_api_v1=None,
                        media_png=None, quote_tweet_id="123", dry_run=False)
    assert tid == "555"
    assert fc.kwargs["quote_tweet_id"] == "123"
    assert fc.kwargs["text"] == "hello"


def test_quote_tweet_id_omitted_when_none():
    fc = FakeClient()
    tu.post_tweet("hello", twitter_client=fc, twitter_api_v1=None,
                  media_png=None, dry_run=False)
    assert "quote_tweet_id" not in fc.kwargs


def test_dry_run_skips_client_entirely():
    tid = tu.post_tweet("hello", twitter_client=None, twitter_api_v1=None,
                        media_png=None, quote_tweet_id="123", dry_run=True)
    assert tid.startswith("dryrun-")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_post_tweet_quote.py -v`
Expected: FAIL with `TypeError: post_tweet() got an unexpected keyword argument 'quote_tweet_id'`

- [ ] **Step 3: Replace the body of `post_tweet` in `storybot/tweet_utils.py`**

Replace the whole function (currently lines 488-517) with:

```python
def post_tweet(
    text: str,
    *,
    twitter_client,
    twitter_api_v1=None,
    media_png: bytes | None = None,
    quote_tweet_id: str | None = None,
    dry_run: bool,
) -> str:
    """Post a single tweet, optionally with one PNG attached and/or quoting
    another tweet (quote_tweet_id). Returns the tweet id."""
    import uuid
    if dry_run:
        return f"dryrun-{uuid.uuid4().hex[:12]}"

    media_ids = None
    if media_png is not None and twitter_api_v1 is not None:
        from io import BytesIO
        media = twitter_api_v1.media_upload(filename="chart.png", file=BytesIO(media_png))
        media_id = getattr(media, "media_id", None) or getattr(media, "media_id_string", None)
        if media_id:
            media_ids = [media_id]

    kwargs: dict = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids
    if quote_tweet_id:
        kwargs["quote_tweet_id"] = quote_tweet_id
    resp = twitter_client.create_tweet(**kwargs)
    data = getattr(resp, "data", None) or {}
    tweet_id = str(data.get("id") or "")
    if not tweet_id:
        raise RuntimeError(f"create_tweet returned no id: {resp!r}")
    return tweet_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_post_tweet_quote.py test/test_publish_tweet.py test/test_publish_result.py -v`
Expected: all PASS (existing callers unaffected — new kwarg defaults to None)

- [ ] **Step 5: Commit**

```bash
git add storybot/tweet_utils.py test/test_post_tweet_quote.py
git commit -m "feat(tweet_utils): post_tweet supports quote_tweet_id"
```

---

### Task 5: Result tweets quote the original flag (Delta 1, publish)

**Files:**
- Modify: `storybot/publish_result.py:96-98`
- Test: `test/test_publish_result.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `test/test_publish_result.py`:

```python
def test_publish_quotes_the_original_flag_tweet(monkeypatch):
    # The receipt mechanic: the result must post as a quote-tweet of the
    # original flag so the timestamped call is visible.
    monkeypatch.setattr(pub.result_store, "result_exists", lambda tid: False)
    monkeypatch.setattr(pub.result_store, "record_result", lambda **kw: None)
    captured = {}

    def fake_post(text, **kwargs):
        captured.update(kwargs)
        return "tid-1"
    monkeypatch.setattr(pub, "post_tweet", fake_post)
    rc = pub.publish(original_tweet_id="987", artifact={
        "result_tweet": "Flagged 14h out: Knicks won. Burned -$24k.",
        "result_draft_path": None, "scorecard_png_path": None,
        "alert_ids": [1], "condition_ids": ["0x"],
        "aggregate": {"n_won": 0, "n_lost": 3, "net_pl_usd": -24000.0,
                      "total_invested_usd": 24000.0},
        "outcome": "burned", "event_label": "E",
    }, dry_run=True)
    assert rc == 0
    assert captured["quote_tweet_id"] == "987"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_publish_result.py -v`
Expected: new test FAILS with `KeyError: 'quote_tweet_id'`

- [ ] **Step 3: Implement**

In `storybot/publish_result.py`, change the `post_tweet` call (lines 96-98) from:

```python
        result_tweet_id = post_tweet(
            text, twitter_client=client, twitter_api_v1=api_v1,
            media_png=media_png, dry_run=dry_run)
```

to:

```python
        result_tweet_id = post_tweet(
            text, twitter_client=client, twitter_api_v1=api_v1,
            media_png=media_png, quote_tweet_id=original_tweet_id,
            dry_run=dry_run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_publish_result.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/publish_result.py test/test_publish_result.py
git commit -m "feat(publish_result): post results as quote-tweets of the original flag"
```

---

### Task 6: Composer leads with the time delta (Delta 1, composition)

**Files:**
- Modify: `storybot/result_pipeline.py` (`SYSTEM_PROMPT_RESULT` ~line 380, `compose_result_tweet` line 428, `process_tweet` lines 544-552 and artifact dict ~line 560)
- Modify: `storybot/run_result_pipeline_loop.sh` (claude prompt, ~line 57)
- Test: `test/test_result_compose_timedelta.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `test/test_result_compose_timedelta.py`:

```python
"""compose_result_tweet must thread flagged_hours_before to the LLM (Delta 1)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import result_pipeline as rp  # noqa: E402


class _FakeResponses:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.kwargs = kwargs
        return SimpleNamespace(output_text='{"tweet": "ok tweet. Cashed +$1k."}')


class FakeLLM:
    def __init__(self):
        self.kwargs = None
        self.responses = _FakeResponses(self)


RESULT = {"n_won": 2, "n_lost": 0, "total_invested_usd": 100.0,
          "total_payout_usd": 150.0, "net_pl_usd": 50.0, "by_market": {}}


def test_payload_includes_flagged_hours_before():
    llm = FakeLLM()
    out = rp.compose_result_tweet(llm, "orig tweet", RESULT,
                                  flagged_hours_before=14)
    assert out == "ok tweet. Cashed +$1k."
    payload = json.loads(llm.kwargs["input"].split("\n\nReply with")[0])
    assert payload["flagged_hours_before"] == 14


def test_payload_flagged_hours_none_by_default():
    llm = FakeLLM()
    rp.compose_result_tweet(llm, "orig tweet", RESULT)
    payload = json.loads(llm.kwargs["input"].split("\n\nReply with")[0])
    assert payload["flagged_hours_before"] is None


def test_prompt_mentions_quote_tweet_and_time_delta():
    p = rp.SYSTEM_PROMPT_RESULT
    assert "quote-tweet" in p
    assert "flagged_hours_before" in p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_result_compose_timedelta.py -v`
Expected: FAIL with `TypeError: compose_result_tweet() got an unexpected keyword argument 'flagged_hours_before'`

- [ ] **Step 3: Implement the composer changes in `storybot/result_pipeline.py`**

3a. In `SYSTEM_PROMPT_RESULT`, make three edits.

In the "You will receive" list, after the `original_tweet` line, add:

```
- flagged_hours_before: integer hours between our flag tweet and this
  result being composed (null when unknown).
```

Replace required-structure item 1 (currently `1. Lead with the result. State who won the market and what the cluster was on. Round dollar figures: "$28k", "$6.2k". One sentence.`) with:

```
1. Lead with the time delta, then the result: open with how far ahead the
   flag was ("Flagged 14h before the close:", "Flagged 3 days out:"),
   then who won the market and what the cluster was on. Use hours when
   flagged_hours_before <= 48, whole days above that; skip the time-delta
   opener entirely when flagged_hours_before is null. Round dollar
   figures: "$28k", "$6.2k". One sentence.
```

Replace the rule `- Reference the original event/team names — the reader should not need to remember the prior tweet to follow.` with:

```
- This posts as a quote-tweet of the original flag, so the reader can see
  the original claim right below. Still name the event/teams (people
  search them), but don't re-describe the original bet mechanics — the
  quoted tweet carries that.
```

3b. Change `compose_result_tweet`'s signature and payload (line 428):

```python
def compose_result_tweet(llm_client, original_tweet: str, result: dict, *,
                         flagged_hours_before: int | None = None) -> str:
```

and in its `payload` dict, add the field right after `"original_tweet"`:

```python
    payload = {
        "original_tweet": original_tweet,
        "flagged_hours_before": flagged_hours_before,
        "result": {
```

3c. In `process_tweet`, replace the `flagged_days_ago` block (lines 544-548) with:

```python
    flagged_days_ago = 0
    flagged_hours_before: int | None = None
    ta = tweet.get("tweeted_at")
    if hasattr(ta, "tzinfo"):
        when = ta if ta.tzinfo else ta.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - when
        flagged_days_ago = delta.days
        flagged_hours_before = max(1, int(delta.total_seconds() // 3600))
```

and change the `compose_result_tweet` call (line 550) to:

```python
    result_tweet = compose_result_tweet(
        llm_client, tweet.get("tweet_text") or "", aggregate,
        flagged_hours_before=flagged_hours_before,
    )
```

3d. In the `artifact` dict in `process_tweet`, add after `"tweeted_at"`:

```python
        "flagged_hours_before": flagged_hours_before,
```

- [ ] **Step 4: Update the claude-edit prompt in `storybot/run_result_pipeline_loop.sh`**

In the `prompt="Review and edit the result tweet draft..."` string, after the sentence `Verify every dollar and W-L number in the tweet matches the artifact's aggregate,` insert:

```
if the tweet's lead states a time delta ('Flagged 14h before…') it must match the artifact's flagged_hours_before field (state hours when <= 48, whole days above that),
```

(keep it inside the same double-quoted shell string, same comma-separated style as the neighboring clauses).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest test/test_result_compose_timedelta.py test/test_result_pl_and_validation.py -v && bash -n storybot/run_result_pipeline_loop.sh`
Expected: all PASS; `bash -n` exits 0 (shell syntax intact)

- [ ] **Step 6: Commit**

```bash
git add storybot/result_pipeline.py storybot/run_result_pipeline_loop.sh test/test_result_compose_timedelta.py
git commit -m "feat(result_pipeline): result tweets lead with flag-to-resolution time delta"
```

---

### Task 7: Raise the loss-notability floor (Delta 3)

**Files:**
- Modify: `storybot/result_pipeline.py:76`
- Test: `test/test_result_selection.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_result_selection.py` (the file already does `import result_pipeline as rp`):

```python
def test_routine_loss_not_eligible_at_new_floor():
    # A $30k loss was "notable" at the old $20k floor; at $50k it must not
    # force its way into the feed.
    cand = {"is_win": False, "net_pl_usd": -30000.0, "notability": 30000.0}
    assert rp.select_results([cand], posted_today=[]) == []


def test_big_loss_still_always_eligible():
    # The honesty floor survives: a $60k loss always posts.
    cand = {"is_win": False, "net_pl_usd": -60000.0, "notability": 60000.0}
    chosen = rp.select_results([cand], posted_today=[])
    assert chosen == [cand]
```

- [ ] **Step 2: Run tests to verify the first fails**

Run: `pytest test/test_result_selection.py -v`
Expected: `test_routine_loss_not_eligible_at_new_floor` FAILS (the $30k loss is selected at the current $20k floor); `test_big_loss_still_always_eligible` PASSES

- [ ] **Step 3: Implement**

In `storybot/result_pipeline.py` line 76, change:

```python
RESULT_LOSS_NOTABLE_USD = 20000.0  # a loss this big is ALWAYS eligible
```

to:

```python
# Raised 20k -> 50k (2026-06-11): at $20k nearly every cluster loss
# qualified, so the honesty floor admitted losses as fast as wins and the
# public record pinned at ~50% instead of converging to RESULT_WIN_BIAS.
RESULT_LOSS_NOTABLE_USD = 50000.0  # a loss this big is ALWAYS eligible
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_result_selection.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/result_pipeline.py test/test_result_selection.py
git commit -m "feat(result_pipeline): raise loss-notable floor to \$50k so win bias materializes"
```

---

### Task 8: `result_store.recent_record` (Delta 2, storage)

**Files:**
- Modify: `storybot/result_store.py` (append)
- Test: `test/test_result_store.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_result_store.py`:

```python
def test_recent_record_maps_outcome_counts(monkeypatch):
    monkeypatch.setattr(rs, "_run",
                        lambda q, p, fetch=True: [{"n_cashed": 11, "n_burned": 4}])
    assert rs.recent_record() == (11, 4)


def test_recent_record_empty_table(monkeypatch):
    monkeypatch.setattr(rs, "_run",
                        lambda q, p, fetch=True: [{"n_cashed": 0, "n_burned": 0}])
    assert rs.recent_record(days=30) == (0, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_result_store.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'recent_record'`

- [ ] **Step 3: Implement in `storybot/result_store.py`**

Append:

```python
def recent_record(days: int = 30) -> tuple[int, int]:
    """(n_cashed, n_burned) over publicly posted results in the last `days`.

    Counts result_tweets rows (one per settled flag tweet), not trade-level
    n_won/n_lost. 'wash' rows are excluded from both sides.
    """
    rows = _run(
        """
        SELECT COUNT(*) FILTER (WHERE outcome = %s)        AS n_cashed,
               COUNT(*) FILTER (WHERE outcome = 'burned')  AS n_burned
        FROM result_tweets
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - (%s * INTERVAL '1 day')
        """,
        (WIN_OUTCOME, int(days)), fetch=True,
    ) or [{}]
    row = rows[0]
    return int(row.get("n_cashed") or 0), int(row.get("n_burned") or 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_result_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/result_store.py test/test_result_store.py
git commit -m "feat(result_store): recent_record() rolling 30d public W-L"
```

---

### Task 9: Track-record closer formatting (Delta 2, pure logic)

**Files:**
- Modify: `storybot/tweet_utils.py` (add near the other tweet-text helpers, after `check_tweet_closer`)
- Test: `test/test_track_record_closer.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `test/test_track_record_closer.py`:

```python
"""format_track_record_closer guards + formatting (Delta 2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import tweet_utils as tu  # noqa: E402


def test_formats_winning_record():
    assert tu.format_track_record_closer(11, 4) == "Recent flags: 11-4."


def test_none_below_min_sample():
    assert tu.format_track_record_closer(6, 3) is None  # 9 settled < 10


def test_none_when_not_winning():
    assert tu.format_track_record_closer(8, 8) is None
    assert tu.format_track_record_closer(4, 12) is None


def test_min_settled_override():
    assert tu.format_track_record_closer(4, 1, min_settled=5) == "Recent flags: 4-1."


def test_closer_passes_flag_tweet_validation():
    # Appended as the final sentence of a flag tweet, the closer must not
    # trip validate_tweet (banned-closer phrases, record-opener regex, etc.).
    import twitter_pipeline as tp
    body = ("Volume on Mariners-Orioles just spiked to 6.8x its usual flow "
            "with $70k on Seattle. Mariners edge or Orioles value?")
    ok, err = tp.validate_tweet(f"{body}\n\nRecent flags: 11-4.")
    assert ok, err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_track_record_closer.py -v`
Expected: FAIL with `AttributeError: ... no attribute 'format_track_record_closer'`

- [ ] **Step 3: Implement in `storybot/tweet_utils.py`**

Add directly after `check_tweet_closer` (after line 140):

```python
# Track-record closer (Delta 2 of the receipts-visibility work). Appended
# deterministically by twitter_pipeline.main() — never composed by the LLM —
# so the public record line always matches the result_tweets table exactly.
TRACK_RECORD_MIN_SETTLED = 10


def format_track_record_closer(n_cashed: int, n_burned: int,
                               min_settled: int = TRACK_RECORD_MIN_SETTLED,
                               ) -> str | None:
    """One-line public track record for flag tweets, or None.

    None when the sample is too small (an early streak shouldn't be
    amplified) or the record isn't winning (the honesty lives in the
    result feed, which still posts notable losses).
    """
    total = int(n_cashed) + int(n_burned)
    if total < min_settled or int(n_cashed) <= int(n_burned):
        return None
    return f"Recent flags: {int(n_cashed)}-{int(n_burned)}."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_track_record_closer.py -v`
Expected: all PASS (including the validate_tweet integration test)

- [ ] **Step 5: Commit**

```bash
git add storybot/tweet_utils.py test/test_track_record_closer.py
git commit -m "feat(tweet_utils): format_track_record_closer with sample/winning guards"
```

---

### Task 10: Attach the closer in the flag pipeline (Delta 2, wiring)

**Files:**
- Modify: `storybot/twitter_pipeline.py` (new helper + `main()` wiring)
- Modify: `storybot/run_twitter_pipeline_loop.sh` (claude prompt)
- Test: `test/test_track_record_closer.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_track_record_closer.py`:

```python
def test_attach_appends_when_it_fits():
    import twitter_pipeline as tp
    text, attached = tp._attach_track_record_closer(
        "Short tweet body. Reply-bait question?", "Recent flags: 11-4.")
    assert attached is True
    assert text.endswith("\n\nRecent flags: 11-4.")


def test_attach_skips_when_over_budget():
    import twitter_pipeline as tp
    body = "x" * 270 + "?"  # 271 chars; closer would push past 280
    text, attached = tp._attach_track_record_closer(body, "Recent flags: 11-4.")
    assert attached is False
    assert text == body


def test_attach_noop_when_no_closer():
    import twitter_pipeline as tp
    text, attached = tp._attach_track_record_closer("Body. Question?", None)
    assert attached is False
    assert text == "Body. Question?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_track_record_closer.py -v`
Expected: the three new tests FAIL with `AttributeError: ... no attribute '_attach_track_record_closer'`

- [ ] **Step 3: Implement the helper in `storybot/twitter_pipeline.py`**

Add directly above `def _write_draft(run_id: str, tweet: str) -> str:` (line 1878):

```python
def _attach_track_record_closer(tweet: str, closer: str | None) -> tuple[str, bool]:
    """Append the deterministic track-record closer when it fits the
    twitter-counted budget. Returns (text, attached)."""
    from tweet_utils import TWEET_MAX_CHARS, _tweet_length
    if not closer:
        return tweet, False
    candidate = f"{tweet}\n\n{closer}"
    if _tweet_length(candidate) <= TWEET_MAX_CHARS:
        return candidate, True
    return tweet, False
```

- [ ] **Step 4: Wire into `main()`**

In `main()`, directly after these two lines (~line 2103):

```python
    tweet = strip_polyspotter_url(decision["tweet"])
    log("tweet_drafted", run_id=run_id, attempts=attempts, length=len(tweet))
```

insert:

```python
    track_closer = None
    try:
        from result_store import recent_record
        from tweet_utils import format_track_record_closer
        track_closer = format_track_record_closer(*recent_record())
    except Exception as exc:
        log("closer_fetch_error", run_id=run_id,
            error=f"{type(exc).__name__}: {exc}")
    tweet, closer_attached = _attach_track_record_closer(tweet, track_closer)
    log("closer_decision", run_id=run_id, attached=closer_attached,
        closer=track_closer)
```

Then in the `transcript["publish_meta"] = {` dict (~line 2141), add after `"recent_tweets": recent_tweets,`:

```python
        "track_record_closer": track_closer if closer_attached else None,
```

- [ ] **Step 5: Update the claude-edit prompt in `storybot/run_twitter_pipeline_loop.sh`**

In the `prompt=` heredoc-style string, after numbered item `4. OPENER FRESHNESS...`, add a fifth item:

```
5. TRACK RECORD CLOSER. The draft may end with a standalone line like 'Recent flags: 11-4.' — that line is computed from our results database (see publish_meta.track_record_closer in the transcript), NOT by the writer, and its numbers are not in the facts_bundle. Leave it exactly as-is: don't reword it, don't delete it, and keep it as the final line. If you shorten the body, the closer still counts toward the 280-char limit.
```

- [ ] **Step 6: Run tests and shell syntax check**

Run: `pytest test/test_track_record_closer.py test/test_twitter_pipeline_validation.py test/test_twitter_pipeline_draft.py -v && bash -n storybot/run_twitter_pipeline_loop.sh`
Expected: all PASS; bash -n exits 0

- [ ] **Step 7: Commit**

```bash
git add storybot/twitter_pipeline.py storybot/run_twitter_pipeline_loop.sh test/test_track_record_closer.py
git commit -m "feat(twitter_pipeline): append 30d track-record closer to flag tweets"
```

---

### Task 11: `result_store` weekly-scoreboard helpers (Delta 4, storage)

**Files:**
- Modify: `storybot/result_store.py` (append)
- Test: `test/test_result_store.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_result_store.py`:

```python
def test_weekly_scoreboard_exists(monkeypatch):
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [{"?column?": 1}])
    assert rs.weekly_scoreboard_exists("2026-W24") is True
    monkeypatch.setattr(rs, "_run", lambda q, p, fetch=True: [])
    assert rs.weekly_scoreboard_exists("2026-W24") is False


def test_record_weekly_scoreboard_conflict_do_nothing(monkeypatch):
    captured = {}

    def fake_run(query, params, fetch=False):
        captured["query"] = query
        captured["params"] = params
        return None

    monkeypatch.setattr(rs, "_run", fake_run)
    rs.record_weekly_scoreboard(iso_week="2026-W24", tweet_id="999",
                                n_cashed=11, n_burned=4, net_pl_usd=58000.0)
    assert "ON CONFLICT (iso_week) DO NOTHING" in captured["query"]
    assert captured["params"] == ("2026-W24", "999", 11, 4, 58000.0)


def test_weekly_aggregate_maps_row(monkeypatch):
    monkeypatch.setattr(
        rs, "_run",
        lambda q, p, fetch=True: [{"n_cashed": 5, "n_burned": 2,
                                   "net_pl_usd": 12345.6}])
    agg = rs.weekly_aggregate()
    assert agg == {"n_cashed": 5, "n_burned": 2, "net_pl_usd": 12345.6}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_result_store.py -v`
Expected: new tests FAIL with `AttributeError`

- [ ] **Step 3: Implement in `storybot/result_store.py`**

Append:

```python
# --- Weekly scoreboard (Component B of the accountability layer) -------------

def weekly_scoreboard_exists(iso_week: str) -> bool:
    """True if this ISO week's scoreboard tweet was already posted."""
    rows = _run(
        "SELECT 1 FROM weekly_scoreboards WHERE iso_week = %s LIMIT 1",
        (str(iso_week),), fetch=True,
    )
    return bool(rows)


def record_weekly_scoreboard(*, iso_week: str, tweet_id: str | None,
                             n_cashed: int, n_burned: int,
                             net_pl_usd: float) -> None:
    """Insert (or no-op on duplicate) one weekly scoreboard row."""
    _run(
        """
        INSERT INTO weekly_scoreboards
            (iso_week, tweet_id, n_cashed, n_burned, net_pl_usd)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (iso_week) DO NOTHING
        """,
        (str(iso_week), str(tweet_id) if tweet_id else None,
         int(n_cashed), int(n_burned), float(net_pl_usd)),
    )


def weekly_aggregate(days: int = 7) -> dict:
    """{n_cashed, n_burned, net_pl_usd} over results posted in the last
    `days`. Row-level outcomes; 'wash' rows count toward neither side but
    their net P&L (≈0 by definition) is included in the sum."""
    rows = _run(
        """
        SELECT COUNT(*) FILTER (WHERE outcome = %s)        AS n_cashed,
               COUNT(*) FILTER (WHERE outcome = 'burned')  AS n_burned,
               COALESCE(SUM(net_pl_usd), 0)                AS net_pl_usd
        FROM result_tweets
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - (%s * INTERVAL '1 day')
        """,
        (WIN_OUTCOME, int(days)), fetch=True,
    ) or [{}]
    row = rows[0]
    return {"n_cashed": int(row.get("n_cashed") or 0),
            "n_burned": int(row.get("n_burned") or 0),
            "net_pl_usd": float(row.get("net_pl_usd") or 0.0)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_result_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/result_store.py test/test_result_store.py
git commit -m "feat(result_store): weekly scoreboard helpers"
```

---

### Task 12: Weekly scoreboard renderer (Delta 4, chart)

**Files:**
- Modify: `storybot/charts.py` (add after `render_result_scorecard`, line 192)
- Test: `test/test_weekly_scoreboard.py` (create)

- [ ] **Step 1: Write the failing test**

Create `test/test_weekly_scoreboard.py`:

```python
"""Weekly scoreboard renderer + result_pipeline weekly posting (Delta 4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def _data(n_cashed=11, n_burned=4, net=58000.0):
    return {"n_cashed": n_cashed, "n_burned": n_burned,
            "net_pl_usd": net, "week_label": "Week of Jun 8"}


def test_weekly_scoreboard_renders_png_bytes():
    for net in (58000.0, -12000.0, 0.0):
        png = charts.render_weekly_scoreboard(_data(net=net))
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_weekly_scoreboard_handles_zero_results():
    png = charts.render_weekly_scoreboard(_data(n_cashed=0, n_burned=0, net=0.0))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest test/test_weekly_scoreboard.py -v`
Expected: FAIL with `AttributeError: module 'charts' has no attribute 'render_weekly_scoreboard'`

- [ ] **Step 3: Implement in `storybot/charts.py`**

Add after `render_result_scorecard` (line 192):

```python
# ----------------------- weekly_scoreboard -----------------------

class WeeklyScoreboardData(TypedDict):
    n_cashed: int            # settled flag tweets that cashed this week
    n_burned: int            # settled flag tweets that burned this week
    net_pl_usd: float        # signed sum across the week's settles
    week_label: str          # "Week of Jun 8"


def _draw_weekly_scoreboard(ax, data: WeeklyScoreboardData) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    n_c = int(data.get("n_cashed") or 0)
    n_b = int(data.get("n_burned") or 0)
    net = float(data.get("net_pl_usd") or 0.0)
    color = ACCENT if net >= 0 else LOSS

    ax.text(0.5, 0.88, "THIS WEEK'S SETTLED FLAGS", color=MUTED, fontsize=22,
            ha="center", va="center")
    ax.text(0.5, 0.60, f"{n_c}-{n_b}", color=color, fontsize=110,
            ha="center", va="center", fontweight="bold")
    sign = "+" if net > 0 else ("-" if net < 0 else "")
    ax.text(0.5, 0.34, f"net {sign}{_format_usd(abs(net))}", color=color,
            fontsize=40, ha="center", va="center", fontweight="bold")

    total = n_c + n_b
    if total:
        share = n_c / total
        bar_y, bar_h = 0.18, 0.05
        ax.add_patch(Rectangle((0.1, bar_y), 0.8 * share, bar_h,
                               color=ACCENT, transform=ax.transAxes))
        ax.add_patch(Rectangle((0.1 + 0.8 * share, bar_y),
                               0.8 * (1 - share), bar_h,
                               color=LOSS, transform=ax.transAxes))

    ax.text(0.5, 0.07, f"PolySpotter · {data.get('week_label') or ''}",
            color=MUTED, fontsize=18, ha="center", va="center")


def render_weekly_scoreboard(data: WeeklyScoreboardData) -> bytes:
    fig, ax = _new_figure()
    _draw_weekly_scoreboard(ax, data)
    return _figure_to_png_bytes(fig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_weekly_scoreboard.py test/test_charts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/charts.py test/test_weekly_scoreboard.py
git commit -m "feat(charts): weekly scoreboard renderer"
```

---

### Task 13: Post the weekly scoreboard from the result loop (Delta 4, wiring)

**Files:**
- Modify: `storybot/result_pipeline.py`
- Test: `test/test_weekly_scoreboard.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test/test_weekly_scoreboard.py`:

```python
from datetime import datetime, timezone  # noqa: E402

import result_pipeline as rp  # noqa: E402

# 2026-06-14 is a Sunday. 22:00 UTC == 18:00 ET (EDT, UTC-4) — in-window.
SUNDAY_EVENING = datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc)
SUNDAY_AFTERNOON = datetime(2026, 6, 14, 18, 0, tzinfo=timezone.utc)  # 2pm ET
THURSDAY = datetime(2026, 6, 11, 22, 0, tzinfo=timezone.utc)


def test_window_open_sunday_evening_et():
    assert rp._weekly_scoreboard_window(SUNDAY_EVENING) == "2026-W24"


def test_window_closed_outside_hours_and_days():
    assert rp._weekly_scoreboard_window(SUNDAY_AFTERNOON) is None
    assert rp._weekly_scoreboard_window(THURSDAY) is None


def test_week_label_is_monday_of_week():
    assert rp._week_label(SUNDAY_EVENING) == "Week of Jun 8"


def test_weekly_tweet_text_passes_validation():
    import twitter_pipeline as tp
    for n_c, n_b, net in [(11, 4, 58000.0), (2, 5, -12000.0), (3, 0, 900.0)]:
        text = rp.format_weekly_scoreboard_tweet(n_c, n_b, net)
        ok, err = tp.validate_tweet(text)
        assert ok, f"{text!r}: {err}"


def test_maybe_post_skips_when_already_posted(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: True)
    called = {"agg": False}
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: called.__setitem__("agg", True) or {})
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert called["agg"] is False


def test_maybe_post_skips_below_min_results(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: False)
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: {"n_cashed": 1, "n_burned": 1,
                                 "net_pl_usd": 100.0})
    posted = {"called": False}
    monkeypatch.setattr(rp, "post_tweet",
                        lambda *a, **k: posted.__setitem__("called", True) or "x")
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert posted["called"] is False


def test_maybe_post_happy_path(monkeypatch):
    monkeypatch.setattr(rp, "DRY_RUN", False)
    monkeypatch.setattr(rp.result_store, "weekly_scoreboard_exists",
                        lambda w: False)
    monkeypatch.setattr(rp.result_store, "weekly_aggregate",
                        lambda: {"n_cashed": 11, "n_burned": 4,
                                 "net_pl_usd": 58000.0})
    monkeypatch.setattr(rp, "_build_twitter_client", lambda: object())
    monkeypatch.setattr(rp, "_build_twitter_api_v1", lambda: object())
    monkeypatch.setattr(rp, "post_tweet", lambda *a, **k: "tid-77")
    captured = {}
    monkeypatch.setattr(rp.result_store, "record_weekly_scoreboard",
                        lambda **kw: captured.update(kw))
    rp.maybe_post_weekly_scoreboard(SUNDAY_EVENING)
    assert captured["iso_week"] == "2026-W24"
    assert captured["tweet_id"] == "tid-77"
    assert captured["n_cashed"] == 11 and captured["n_burned"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test/test_weekly_scoreboard.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute '_weekly_scoreboard_window'`

- [ ] **Step 3: Implement in `storybot/result_pipeline.py`**

Add below `maybe_snapshot_followers` (still above `def main()`):

```python
# --- Weekly scoreboard (Component B) -----------------------------------------

WEEKLY_SCOREBOARD_MIN_RESULTS = 3   # don't post a scoreboard over a tiny week


def _weekly_scoreboard_window(now: datetime) -> str | None:
    """ISO-week key ('2026-W24') when `now` falls inside the Sunday
    17:00-22:00 ET posting window, else None."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(_AUDIENCE_TZ)
    if et.weekday() != 6 or not (17 <= et.hour < 22):
        return None
    iso = et.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _week_label(now: datetime) -> str:
    """Human label for the scorecard footer: 'Week of Jun 8' (ISO Monday)."""
    et = now.astimezone(_AUDIENCE_TZ)
    monday = et.date() - timedelta(days=et.weekday())
    return f"Week of {monday.strftime('%b')} {monday.day}"


def format_weekly_scoreboard_tweet(n_cashed: int, n_burned: int,
                                   net_pl_usd: float) -> str:
    """Deterministic weekly tweet text — no LLM, validated by tests against
    twitter_pipeline.validate_tweet."""
    sign = "+" if net_pl_usd > 0 else ("-" if net_pl_usd < 0 else "")
    net_str = f"{sign}{charts._format_usd(abs(net_pl_usd))}"
    return (f"Settled flags this week: {n_cashed}-{n_burned}, net {net_str}. "
            f"Every result quote-tweets the original call.")


def maybe_post_weekly_scoreboard(now: datetime) -> None:
    """Post the Sunday-evening weekly scoreboard at most once per ISO week.
    Never raises — a scoreboard failure must not break the settle run.
    Does not count against RESULT_DAILY_CAP (it summarizes, it doesn't
    settle) and is skipped entirely in DRY_RUN (a dryrun row would block
    the real post for the week)."""
    try:
        if DRY_RUN:
            return
        iso_week = _weekly_scoreboard_window(now)
        if not iso_week:
            return
        if result_store.weekly_scoreboard_exists(iso_week):
            return
        agg = result_store.weekly_aggregate()
        n_cashed = int(agg["n_cashed"])
        n_burned = int(agg["n_burned"])
        if n_cashed + n_burned < WEEKLY_SCOREBOARD_MIN_RESULTS:
            log("weekly_scoreboard_skip", iso_week=iso_week,
                reason="too few settled results", count=n_cashed + n_burned)
            return
        net = float(agg["net_pl_usd"])
        text = format_weekly_scoreboard_tweet(n_cashed, n_burned, net)
        png = charts.render_weekly_scoreboard({
            "n_cashed": n_cashed, "n_burned": n_burned, "net_pl_usd": net,
            "week_label": _week_label(now)})
        tweet_id = post_tweet(text,
                              twitter_client=_build_twitter_client(),
                              twitter_api_v1=_build_twitter_api_v1(),
                              media_png=png, dry_run=False)
        result_store.record_weekly_scoreboard(
            iso_week=iso_week, tweet_id=tweet_id,
            n_cashed=n_cashed, n_burned=n_burned, net_pl_usd=net)
        log("weekly_scoreboard_posted", iso_week=iso_week, tweet_id=tweet_id,
            record=f"{n_cashed}-{n_burned}", net_pl_usd=net)
    except Exception as exc:
        log("weekly_scoreboard_error", error=f"{type(exc).__name__}: {exc}")
```

Wire into `main()`: directly before the final `log("run_end", ...)` line, add:

```python
    maybe_post_weekly_scoreboard(datetime.now(timezone.utc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test/test_weekly_scoreboard.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add storybot/result_pipeline.py test/test_weekly_scoreboard.py
git commit -m "feat(result_pipeline): Sunday-evening weekly scoreboard tweet"
```

---

### Task 14: Full verification, PR, rollout notes

**Files:** none (verification only)

- [ ] **Step 1: Run the full scanner/storybot suite**

Run: `pytest`
Expected: all tests pass, zero failures. If anything fails, fix before proceeding.

- [ ] **Step 2: Run the backend suite (guards against schema.sql regressions)**

Run: `cd backend && pytest && cd ..`
Expected: all pass.

- [ ] **Step 3: Smoke-test both pipelines in DRY_RUN**

```bash
DRY_RUN=true python storybot/result_pipeline.py
DRY_RUN=true python storybot/twitter_pipeline.py
```

Expected: both exit 0. result_pipeline logs `run_start`/`run_end` JSON without `*_error` events (except possibly `results_selected ... chosen: 0`, which is normal). twitter_pipeline either drafts (DRY_RUN bypasses the cadence gate) or skips cleanly; if it drafts, the log should include a `closer_decision` event.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/twitter-receipts-visibility
gh pr create --title "Twitter receipts visibility: quote-tweet results, track-record closer, weekly scoreboard, follower tracking" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-06-11-twitter-receipts-visibility-design.md

- Result tweets now post as quote-tweets of the original flag (the receipt is visible)
- Result tweets lead with the flag-to-resolution time delta
- Flag tweets append a deterministic 'Recent flags: X-Y.' closer (>=10 settled, winning record, fits 280)
- RESULT_LOSS_NOTABLE_USD 20k -> 50k so the public record converges to the 0.8 win bias
- Sunday-evening weekly scoreboard tweet (new weekly_scoreboards table + chart renderer)
- Daily follower snapshot via free-tier get_me (new follower_snapshots table)

Both new tables are already applied to the Railway Postgres (CREATE TABLE IF NOT EXISTS, idempotent).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Post-merge rollout (manual, after PR merges)**

These are operator steps — record them in the PR or tell Bhavya:

1. On the host, restart both screen sessions so the loops pick up the new code:
   `screen -r results` → Ctrl-C → `./storybot/run_result_pipeline_loop.sh` → detach;
   same for the twitter pipeline session (`screen -r twitter_pipeline` or wherever `run_twitter_pipeline_loop.sh` runs).
2. One-time manual actions from the spec: follow ~50 relevant accounts from @polyspotter; pin the best receipt quote-tweet once one exists.
3. After ~2 weeks, check the trend: `SELECT * FROM follower_snapshots ORDER BY snapshot_date;`
