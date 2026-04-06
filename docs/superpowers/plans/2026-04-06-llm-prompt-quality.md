# LLM Prompt Quality Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce false positives and eliminate formulaic LLM output by enriching prompt data (wallet flag history, category-specific win rates, volume trends) and overhauling the system prompt with anti-patterns and few-shot examples.

**Architecture:** Single-pass LLM filter stays. Three files change: `db.py` (new helpers + schema migration), `detection_strategies/win_rate_tracking.py` (pass category at write time), and `llm_filter.py` (enriched prompt data + overhauled system prompt + cache version bump).

**Tech Stack:** Python 3.13, SQLite, OpenAI API (Azure GPT-5.4)

**Spec:** `docs/superpowers/specs/2026-04-03-llm-prompt-quality-design.md`

---

### Task 1: Add `category` column to `tracked_bets` schema

**Files:**
- Modify: `db.py:42-54` (table schema)
- Test: `test/test_win_rate_tracking.py`

- [ ] **Step 1: Write the failing test**

Add a test that inserts a tracked bet with a category and reads it back.

In `test/test_win_rate_tracking.py`, add to `TestWinRateTrackingHelpers`:

```python
@patch("db.get_db")
def test_record_trade_stores_category(self, mock_get_db):
    # Recreate table with category column
    self.conn.execute("DROP TABLE tracked_bets")
    self.conn.execute("""
        CREATE TABLE tracked_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            side TEXT NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            won INTEGER DEFAULT NULL,
            category TEXT DEFAULT NULL
        )
    """)
    self.conn.commit()
    mock_get_db.return_value = self.conn
    trade = self._make_trade()
    record_tracked_bet(trade, category="Sports")
    row = self.conn.execute("SELECT category FROM tracked_bets").fetchone()
    self.assertEqual(row[0], "Sports")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py::TestWinRateTrackingHelpers::test_record_trade_stores_category -v`

Expected: FAIL — `record_tracked_bet()` does not accept `category` parameter.

- [ ] **Step 3: Update schema and `record_tracked_bet()` in db.py**

In `db.py`, update the `tracked_bets` CREATE TABLE statement (around line 43) to add the column:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracked_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            side TEXT NOT NULL,
            usd_value REAL NOT NULL,
            trade_timestamp REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            won INTEGER DEFAULT NULL,
            category TEXT DEFAULT NULL
        )
    """)
```

Update `record_tracked_bet()` (around line 277) to accept and store category:

```python
def record_tracked_bet(trade: dict, category: str | None = None) -> None:
    """Insert a trade into tracked_bets for win/loss tracking."""
    wallet = trade.get("proxyWallet", "").lower()
    if not wallet:
        return
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO tracked_bets
           (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, category)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            wallet,
            trade.get("conditionId", ""),
            trade.get("outcome", ""),
            trade.get("side", ""),
            float(trade.get("_usd_value", 0)),
            trade.get("timestamp", 0),
            datetime.now(timezone.utc).isoformat(),
            category,
        ),
    )
    conn.commit()
```

Add the migration for existing databases. In `get_db()`, after the existing table creation block, add:

```python
    # Migrations
    # Add category column to tracked_bets if it doesn't exist
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tracked_bets)").fetchall()}
    if "category" not in cols:
        conn.execute("ALTER TABLE tracked_bets ADD COLUMN category TEXT DEFAULT NULL")
        conn.commit()
```

- [ ] **Step 4: Update the in-memory table in `setUp` of existing tests**

In `test/test_win_rate_tracking.py`, update the `setUp` method's CREATE TABLE to include the `category` column:

```python
        self.conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL,
                category TEXT DEFAULT NULL
            )
        """)
```

And the new test no longer needs to drop/recreate — simplify it:

```python
@patch("db.get_db")
def test_record_trade_stores_category(self, mock_get_db):
    mock_get_db.return_value = self.conn
    trade = self._make_trade()
    record_tracked_bet(trade, category="Sports")
    row = self.conn.execute("SELECT category FROM tracked_bets").fetchone()
    self.assertEqual(row[0], "Sports")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py -v`

Expected: ALL PASS including the new `test_record_trade_stores_category`.

- [ ] **Step 6: Commit**

```bash
git add db.py test/test_win_rate_tracking.py
git commit -m "feat: add category column to tracked_bets schema"
```

---

### Task 2: Pass category from `win_rate_tracking` to `record_tracked_bet`

**Files:**
- Modify: `detection_strategies/win_rate_tracking.py:248`
- Modify: `detection_strategies/win_rate_tracking.py` (imports)

- [ ] **Step 1: Update the import and call site**

In `detection_strategies/win_rate_tracking.py`, add to the existing imports at the top:

```python
from gamma_cache import get_market_category
```

Note: `get_market_by_condition` is already imported in this file from `gamma_cache` (check if it is — if not, this is a new import).

Update `check_trade()` around line 248 to pass category:

```python
        record_tracked_bet(trade, category=get_market_category(trade.get("conditionId", "")))
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py -v`

Expected: ALL PASS. Existing tests mock `get_db` and don't call `get_market_category` since they mock the strategy's external dependencies.

- [ ] **Step 3: Commit**

```bash
git add detection_strategies/win_rate_tracking.py
git commit -m "feat: store market category when recording tracked bets"
```

---

### Task 3: Add `get_wallet_flag_summary()` helper to db.py

**Files:**
- Modify: `db.py` (add new function)
- Test: `test/test_win_rate_tracking.py`

- [ ] **Step 1: Write the failing test**

Add a new test class in `test/test_win_rate_tracking.py`:

```python
from db import get_wallet_flag_summary

class TestGetWalletFlagSummary(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE flagged_wallets (
                wallet TEXT PRIMARY KEY,
                times_flagged INTEGER NOT NULL DEFAULT 1,
                total_usd_flagged REAL NOT NULL DEFAULT 0,
                first_flagged_at TEXT NOT NULL,
                last_flagged_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @patch("db.get_db")
    def test_returns_none_for_unknown_wallet(self, mock_get_db):
        mock_get_db.return_value = self.conn
        result = get_wallet_flag_summary("0xunknown")
        self.assertIsNone(result)

    @patch("db.get_db")
    def test_returns_flag_data(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self.conn.execute(
            "INSERT INTO flagged_wallets VALUES (?, ?, ?, ?, ?)",
            ("0xabc123", 42, 890000.0, "2026-01-15T00:00:00Z", "2026-03-20T00:00:00Z"),
        )
        self.conn.commit()
        result = get_wallet_flag_summary("0xabc123")
        self.assertEqual(result["times_flagged"], 42)
        self.assertAlmostEqual(result["total_usd_flagged"], 890000.0)
        self.assertEqual(result["first_flagged_at"], "2026-01-15T00:00:00Z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py::TestGetWalletFlagSummary -v`

Expected: FAIL — `get_wallet_flag_summary` does not exist.

- [ ] **Step 3: Implement `get_wallet_flag_summary()` in db.py**

Add after the existing `flagged_wallets` operations section (around line 400, or wherever the flagged_wallets helpers are):

```python
def get_wallet_flag_summary(wallet: str) -> dict | None:
    """Return flag history for a wallet, or None if never flagged."""
    conn = get_db()
    row = conn.execute(
        "SELECT times_flagged, total_usd_flagged, first_flagged_at FROM flagged_wallets WHERE wallet = ?",
        (wallet.lower(),),
    ).fetchone()
    if not row:
        return None
    return {
        "times_flagged": row[0],
        "total_usd_flagged": row[1],
        "first_flagged_at": row[2],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py::TestGetWalletFlagSummary -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add db.py test/test_win_rate_tracking.py
git commit -m "feat: add get_wallet_flag_summary() helper"
```

---

### Task 4: Add `get_wallet_category_win_rates()` helper to db.py

**Files:**
- Modify: `db.py` (add new function)
- Test: `test/test_win_rate_tracking.py`

- [ ] **Step 1: Write the failing test**

Add a new test class in `test/test_win_rate_tracking.py`:

```python
from db import get_wallet_category_win_rates

class TestGetWalletCategoryWinRates(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE tracked_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                side TEXT NOT NULL,
                usd_value REAL NOT NULL,
                trade_timestamp REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                won INTEGER DEFAULT NULL,
                category TEXT DEFAULT NULL
            )
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _insert_bet(self, wallet, category, resolved=1, won=1):
        self.conn.execute(
            """INSERT INTO tracked_bets
               (wallet, condition_id, outcome, side, usd_value, trade_timestamp, recorded_at, resolved, won, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (wallet, "cid_1", "Yes", "BUY", 1000, 1700000000, "2026-01-01", resolved, won, category),
        )
        self.conn.commit()

    @patch("db.get_db")
    def test_empty_for_unknown_wallet(self, mock_get_db):
        mock_get_db.return_value = self.conn
        result = get_wallet_category_win_rates("0xunknown")
        self.assertEqual(result, {})

    @patch("db.get_db")
    def test_groups_by_category(self, mock_get_db):
        mock_get_db.return_value = self.conn
        for _ in range(8):
            self._insert_bet("0xwallet", "Sports", resolved=1, won=1)
        for _ in range(2):
            self._insert_bet("0xwallet", "Sports", resolved=1, won=0)
        for _ in range(3):
            self._insert_bet("0xwallet", "Crypto", resolved=1, won=1)
        for _ in range(1):
            self._insert_bet("0xwallet", "Crypto", resolved=1, won=0)
        result = get_wallet_category_win_rates("0xwallet")
        self.assertIn("Sports", result)
        self.assertEqual(result["Sports"]["wins"], 8)
        self.assertEqual(result["Sports"]["losses"], 2)
        self.assertEqual(result["Sports"]["closed"], 10)
        self.assertAlmostEqual(result["Sports"]["win_rate"], 0.8)
        self.assertIn("Crypto", result)
        self.assertEqual(result["Crypto"]["wins"], 3)
        self.assertEqual(result["Crypto"]["closed"], 4)

    @patch("db.get_db")
    def test_skips_null_category(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self._insert_bet("0xwallet", None, resolved=1, won=1)
        self._insert_bet("0xwallet", "Sports", resolved=1, won=1)
        result = get_wallet_category_win_rates("0xwallet")
        self.assertNotIn(None, result)
        self.assertIn("Sports", result)

    @patch("db.get_db")
    def test_skips_unresolved(self, mock_get_db):
        mock_get_db.return_value = self.conn
        self._insert_bet("0xwallet", "Sports", resolved=0, won=None)
        result = get_wallet_category_win_rates("0xwallet")
        self.assertEqual(result, {})

    @patch("db.get_db")
    def test_limits_to_top_5(self, mock_get_db):
        mock_get_db.return_value = self.conn
        categories = ["Sports", "Crypto", "Politics", "Science", "Business", "Pop Culture"]
        for i, cat in enumerate(categories):
            for _ in range(10 - i):  # Sports=10, Crypto=9, ..., Pop Culture=5
                self._insert_bet("0xwallet", cat, resolved=1, won=1)
        result = get_wallet_category_win_rates("0xwallet")
        self.assertEqual(len(result), 5)
        self.assertNotIn("Pop Culture", result)  # fewest bets, excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py::TestGetWalletCategoryWinRates -v`

Expected: FAIL — `get_wallet_category_win_rates` does not exist.

- [ ] **Step 3: Implement `get_wallet_category_win_rates()` in db.py**

Add near `get_wallet_flag_summary()`:

```python
def get_wallet_category_win_rates(wallet: str) -> dict[str, dict]:
    """Return win rates broken down by market category.

    Returns {category: {wins, losses, closed, win_rate}} for top 5
    categories by number of closed positions.  Only includes resolved
    bets with a non-NULL category.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT category,
                  SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) AS wins,
                  SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END) AS losses,
                  COUNT(*) AS closed
           FROM tracked_bets
           WHERE wallet = ? AND resolved = 1 AND category IS NOT NULL
           GROUP BY category
           ORDER BY closed DESC
           LIMIT 5""",
        (wallet.lower(),),
    ).fetchall()
    result = {}
    for cat, wins, losses, closed in rows:
        result[cat] = {
            "wins": wins,
            "losses": losses,
            "closed": closed,
            "win_rate": wins / closed if closed > 0 else 0.0,
        }
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest test/test_win_rate_tracking.py::TestGetWalletCategoryWinRates -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add db.py test/test_win_rate_tracking.py
git commit -m "feat: add get_wallet_category_win_rates() helper"
```

---

### Task 5: Enrich `_build_prompt()` with flag history, category win rates, and volume trend

**Files:**
- Modify: `llm_filter.py:22` (imports)
- Modify: `llm_filter.py:296-461` (`_build_prompt`)

- [ ] **Step 1: Add imports**

In `llm_filter.py`, update the import from `db` (line 22) to include the new helpers:

```python
from db import get_llm_evaluation, get_wallet_market_positions, get_wallet_pnl_summary, save_llm_evaluation, get_wallet_flag_summary, get_wallet_category_win_rates
```

- [ ] **Step 2: Add volume trend to market context**

In `_build_prompt()`, find the volume section (around line 356-363) and add `volume1wk` and `volume1mo`. Replace the existing volume block:

```python
            # Volume & liquidity
            vol_total = mkt.get("volumeNum")
            vol_24h = mkt.get("volume24hr")
            vol_1wk = mkt.get("volume1wk")
            vol_1mo = mkt.get("volume1mo")
            liquidity = mkt.get("liquidityNum")
            vol_parts = []
            if vol_total is not None:
                vol_parts.append(f"total ${vol_total:,.0f}")
            if vol_24h is not None:
                vol_parts.append(f"24h ${vol_24h:,.0f}")
            if vol_1wk is not None:
                vol_parts.append(f"1wk ${vol_1wk:,.0f}")
            if vol_1mo is not None:
                vol_parts.append(f"1mo ${vol_1mo:,.0f}")
            if vol_parts:
                parts.append(f"  Volume: {', '.join(vol_parts)}")
            if liquidity is not None:
                parts.append(f"  Liquidity: ${liquidity:,.0f}")
```

- [ ] **Step 3: Add flag history and category win rates to wallet profiles**

In `_build_prompt()`, find the wallet profiles section (around line 413-438). After the existing profile line is built (after `profile_lines.append(line)` around line 434), add flag history and category win rates. Replace the wallet loop body:

```python
        for w in sorted(wallets)[:10]:  # cap to keep prompt reasonable
            pnl = get_wallet_pnl_summary(w)
            closed = pnl.get("closed_positions", 0)
            if closed == 0:
                profile_lines.append(f"  - {w[:8]}...{w[-6:]}: no resolved positions")
                continue
            wins = pnl.get("wins", 0)
            losses = pnl.get("losses", 0)
            win_rate = wins / closed
            total_pnl = pnl.get("total_pnl") or 0
            total_invested = pnl.get("total_invested") or 0
            avg_win_price = pnl.get("avg_win_price")
            line = (
                f"  - {w[:8]}...{w[-6:]}: {win_rate:.0%} win rate "
                f"({wins}W/{losses}L on {closed} resolved), "
                f"P&L ${total_pnl:+,.0f} on ${total_invested:,.0f} invested"
            )
            if avg_win_price is not None:
                line += f", avg win price {avg_win_price:.2f}"
            # Flag history
            flags = get_wallet_flag_summary(w)
            if flags:
                line += f", flagged {flags['times_flagged']}x (${flags['total_usd_flagged']:,.0f} total)"
            # Category win rates
            cat_rates = get_wallet_category_win_rates(w)
            if cat_rates:
                cat_strs = [f"{cat} {d['win_rate']:.0%} ({d['closed']})" for cat, d in cat_rates.items()]
                line += f" — {', '.join(cat_strs)}"
            profile_lines.append(line)
```

- [ ] **Step 4: Manually verify prompt output**

Run a quick sanity check to see the enriched prompt format:

```bash
source venv/bin/activate && python -c "
from llm_filter import _build_prompt
from unittest.mock import patch

alert = {
    'market_title': 'Test Market',
    'alert_type': 'composite',
    'composite_score': 8.0,
    'total_usd': 5000,
    'trade_count': 1,
    'wallet': '0x0000000000000000000000000000000000000001',
}
# Patch out Gamma API calls
with patch('llm_filter.invalidate_market'), \
     patch('llm_filter.get_market_by_condition', return_value=None), \
     patch('llm_filter.get_wallet_pnl_summary', return_value={'closed_positions': 0}), \
     patch('llm_filter.get_wallet_flag_summary', return_value=None), \
     patch('llm_filter.get_wallet_category_win_rates', return_value={}):
    print(_build_prompt(alert))
"
```

Expected: Output should include market title, score, USD, wallet profile line. No errors.

- [ ] **Step 5: Commit**

```bash
git add llm_filter.py
git commit -m "feat: enrich LLM prompt with flag history, category rates, volume trend"
```

---

### Task 6: Overhaul the system prompt

**Files:**
- Modify: `llm_filter.py:45-211` (`SYSTEM_PROMPT`)

- [ ] **Step 1: Add anti-pattern rules**

In `llm_filter.py`, find the end of the "Bullet style rules" section in `SYSTEM_PROMPT` (the "Good bullet examples" block ending around line 210). Append the anti-pattern section right after it:

```python
    "## Anti-patterns — DO NOT do these\n\n"
    "- Never use the phrase 'repeatable edge' or 'suggesting a repeatable edge'\n"
    "- Don't start every first bullet with 'This bettor wins X%% of...'\n"
    "- Don't use the same 3-bullet template for every alert "
    "(win rate → market breadth → trade details)\n"
    "- Don't describe signal mechanics — users don't know what "
    "'concentrated_one_sided' means\n"
    "- Don't repeat the market name in the headline\n"
    "- Vary headline structure — '[X%%] win-rate [sport] sharp' cannot be "
    "the default for every alert\n"
    "- Don't say 'suggesting informed momentum' or similar hedging — be direct\n\n"
```

- [ ] **Step 2: Add "what makes this one different" framing**

Append after the anti-pattern rules:

```python
    "## Differentiation\n\n"
    "Before writing your output, ask: 'If this user has already seen 50 alerts "
    "today about sharp bettors with high win rates, what makes THIS one worth "
    "stopping on?'\n\n"
    "Lead with the surprising or unusual detail — the stat that doesn't fit the "
    "pattern, the context that changes the interpretation, the timing that's "
    "uncanny. If there's nothing surprising, it's probably not interesting.\n\n"
```

- [ ] **Step 3: Add cluster-specific filtering rules**

Find the "NOT interesting (discard)" list in `SYSTEM_PROMPT` (around line 160-168). Append these items to that list:

```python
    "- Clusters where only one wallet has a strong track record and that wallet "
    "would be flagged individually by win_rate_tracking — the individual alert "
    "surfaces the sharp bettor already; the cluster adds noise, not signal\n"
    "- A cluster is interesting when the COORDINATION is the signal: linked "
    "wallets via shared funder, unusual convergence of multiple independently-"
    "strong wallets, or significant capital from wallets that don't usually "
    "trade this category\n\n"
```

- [ ] **Step 4: Add few-shot examples**

Append the good/bad example pairs after the "Differentiation" section. These are the most important lever for fixing formulaic output:

```python
    "## Examples of good vs bad output\n\n"
    "BAD (formulaic — do not produce output like this):\n"
    '{"headline": "90%% win-rate sports bettor", '
    '"bullets": ["This bettor wins 90%% of their resolved trades and is up '
    '$43.5k overall.", "They have placed 71 bets across 68 events, which '
    'points to a repeatable edge.", "They bought Islanders at 58¢ from a '
    'trader whose average winning entry is 55¢."]}\n\n'
    "GOOD (insightful — lead with what makes this trade different):\n"
    '{"headline": "90%% winner loads up on underdog", '
    '"bullets": ["Bought Islanders at 58¢ — their average winning entry '
    "is 55¢, so paying above their usual threshold signals extra conviction."
    '", "90%% win rate on 71 bets with $43k profit, and most of that edge '
    'comes from hockey specifically."]}\n\n'

    "BAD cluster (should be discarded — only one standout wallet):\n"
    '{"interesting": true, "headline": "6-wallet Tigers cluster", '
    '"bullets": ["Six wallets put $10.5k on Detroit Tigers, covering most '
    "of this market's daily volume."
    '", "One wallet in the group wins 96%% of bets with $201k in profit.", '
    '"The cluster bought between 58-63¢, showing coordinated conviction."]}\n\n'
    "GOOD (discard it — the sharp wallet gets its own individual alert):\n"
    '{"interesting": false, "summary": "Mixed-quality 6-wallet cluster where '
    "the only standout (96%% winner) would be flagged individually. The other "
    '5 wallets have mediocre records. Not coordinated conviction."}\n\n'

    "BAD serial timer:\n"
    '{"headline": "Serial timer with $16.3M profit", '
    '"bullets": ["This bettor has won 74%% of 1,024 resolved bets and is up '
    '$16.3M lifetime.", "The trade came 1.4 minutes before resolution with a '
    'documented edge.", "They put $51.5k on No at 44¢ while volume was '
    '116x normal."]}\n\n'
    "GOOD serial timer (lead with the action, not the resume):\n"
    '{"headline": "$51k No bet 84 seconds before close", '
    '"bullets": ["Dropped $51.5k on No at 44¢ with just 84 seconds left — '
    "this wallet has a pattern of last-minute bets and is up $16.3M lifetime "
    'on 1,024 trades.", "Market volume was running 116x normal when the trade '
    'hit, suggesting other informed money was already moving."]}\n'
```

- [ ] **Step 5: Add wallet flag and category context to the strategy descriptions**

Find the "## Alert structure" section (around line 59). After the line about market context, add a note about the new wallet data so the LLM knows to use it:

```python
    "Each alert also includes **wallet profile data**: historical win rate, P&L, "
    "number of times the wallet has been flagged by the scanner, and "
    "category-specific win rates (e.g., 'Sports 87%% (120), Crypto 52%% (45)'). "
    "Use category-specific win rates to judge whether the wallet's edge is "
    "relevant to this specific market's category.\n\n"
```

- [ ] **Step 6: Verify prompt compiles without syntax errors**

Run: `source venv/bin/activate && python -c "from llm_filter import SYSTEM_PROMPT; print(f'System prompt: {len(SYSTEM_PROMPT)} chars')"`

Expected: Prints character count without errors. Should be roughly 4000-5000 chars (up from ~3500).

- [ ] **Step 7: Commit**

```bash
git add llm_filter.py
git commit -m "feat: overhaul system prompt with anti-patterns and few-shot examples"
```

---

### Task 7: Add `PROMPT_VERSION` cache key prefix

**Files:**
- Modify: `llm_filter.py:27-29` (constants)
- Modify: `llm_filter.py:550` (cache key in `filter_alerts`)

- [ ] **Step 1: Add the version constant**

In `llm_filter.py`, after the `MODEL = "gpt-5.4"` line (around line 29), add:

```python
PROMPT_VERSION = "v2"
```

- [ ] **Step 2: Prefix cache keys with version**

In `filter_alerts()`, find the cache key computation (around line 550):

```python
        cache_key = alert.get("llm_cache_key") or alert.get("dedup_key", "")
```

Add the version prefix right after:

```python
        cache_key = alert.get("llm_cache_key") or alert.get("dedup_key", "")
        if cache_key:
            cache_key = f"{PROMPT_VERSION}:{cache_key}"
```

- [ ] **Step 3: Verify old cache entries won't match**

Run: `source venv/bin/activate && python -c "
from db import get_llm_evaluation
# Old keys don't have the v2: prefix, so they should miss
result = get_llm_evaluation('v2:some_old_key')
print(f'Cache lookup for v2 prefixed key: {result}')  # Should be None
"`

Expected: `None` — confirms old entries don't match new versioned keys.

- [ ] **Step 4: Commit**

```bash
git add llm_filter.py
git commit -m "feat: add PROMPT_VERSION to cache key for prompt change invalidation"
```

---

### Task 8: End-to-end verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `source venv/bin/activate && python -m pytest test/ -v`

Expected: ALL PASS. No regressions.

- [ ] **Step 2: Verify prompt builds correctly with real data**

Run against the live database to confirm enriched prompts work with actual wallet data:

```bash
source venv/bin/activate && python -c "
from llm_filter import _build_prompt

# Build a prompt for a wallet we know has data
alert = {
    'market_title': 'Test verification',
    'alert_type': 'composite',
    'composite_score': 8.0,
    'total_usd': 5000,
    'trade_count': 1,
    'wallet': '0x50b1db131a28e5f87b72f2b91b26bf27690e1a90',  # most-flagged wallet
}
prompt = _build_prompt(alert)
print(prompt)
# Look for: flagged Nx, category win rates
assert 'flagged' in prompt, 'Flag history missing from prompt'
print('\nVerification passed: enriched prompt includes flag history')
"
```

Expected: Prompt includes "flagged 116x" for this wallet and any available category win rates.

- [ ] **Step 3: Verify system prompt is valid**

```bash
source venv/bin/activate && python -c "
from llm_filter import SYSTEM_PROMPT, PROMPT_VERSION
print(f'Prompt version: {PROMPT_VERSION}')
print(f'System prompt length: {len(SYSTEM_PROMPT)} chars')
assert 'Anti-patterns' in SYSTEM_PROMPT, 'Anti-patterns section missing'
assert 'repeatable edge' in SYSTEM_PROMPT, 'Anti-pattern rule missing'
assert 'Differentiation' in SYSTEM_PROMPT, 'Differentiation section missing'
assert 'GOOD' in SYSTEM_PROMPT, 'Few-shot examples missing'
assert PROMPT_VERSION == 'v2', 'Version not bumped'
print('All system prompt checks passed')
"
```

Expected: All assertions pass.

- [ ] **Step 4: Commit any final fixes if needed, then verify branch state**

```bash
git log --oneline
```

Expected: 7 new commits on `llm-prompt-quality` branch covering schema, helpers, prompt enrichment, system prompt overhaul, and cache versioning.
