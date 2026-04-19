# PolySpotter Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop `/` Home surface with the PolySpotter redesign and ship three mobile-first routes (`/signals`, `/discover`, `/watchlist`), backed by new signal-shaped FastAPI endpoints.

**Architecture:** Single Next.js 15 app with responsive routes (Tailwind `md:` breakpoint). New FastAPI endpoints wrap the existing `alerts` table with server-side derivation of the canonical `Signal` shape (rating/tier/topic/returnPct) so frontend avoids N+1 fetches. localStorage-only watchlist; 5s-polling live ticker; no WebSocket.

**Tech Stack:** Next.js 15 + React 19 + Tailwind 4 (frontend); FastAPI + PostgreSQL + psycopg2 (backend). `DM Sans` + `JetBrains Mono` already loaded via `next/font/google` in [layout.jsx](../../../frontend/src/app/layout.jsx).

**Spec:** [docs/superpowers/specs/2026-04-17-polyspotter-redesign-design.md](../specs/2026-04-17-polyspotter-redesign-design.md)

**Design reference:** [design_handoff_polyspotter/](../../../design_handoff_polyspotter/) — working React prototype; inline styles map 1:1 to the spec's tokens. Cite file+line ranges from here for visual detail.

**Conventions used throughout this plan:**

- All paths are relative to repo root `/Users/bhavya/git/polybot/`.
- Backend tasks follow strict TDD (write failing test → verify fail → implement → verify pass → commit).
- Frontend tasks use "implement → lint clean → verify visually" because there is no component test framework in the repo (this is intentional; see spec §8.2). Each frontend task names the screenshot region or reference-JSX lines to match.
- Every task ends in a single commit. Commit messages use Conventional Commits: `feat:`, `fix:`, `refactor:`, `style:`, `test:`, `docs:`.
- Run all commands from repo root unless noted.

---

## Phase 0 — Foundation

### Task 1: Extend design tokens in globals.css

**Files:**
- Modify: [frontend/src/app/globals.css](../../../frontend/src/app/globals.css) (lines 1–80)

- [ ] **Step 1: Read current token layout**

Open [frontend/src/app/globals.css](../../../frontend/src/app/globals.css) lines 1–80. Current `:root` holds light tokens; `.dark` holds dark-mode overrides. Keep both blocks; update dark values and add missing tokens.

- [ ] **Step 2: Edit `.dark` block (lines 41–58)**

Replace the entire `.dark { ... }` block with the exact palette from [spec §6](../specs/2026-04-17-polyspotter-redesign-design.md#6-design-tokens):

```css
.dark {
  --surface-0:      #05080f;
  --surface-1:      #0a0f1c;
  --surface-2:      #111827;
  --surface-card:   #0f1624;
  --surface-card-hover: #141c2e;

  --border:         rgba(255,255,255,0.08);
  --border-subtle:  rgba(255,255,255,0.05);
  --border-strong:  rgba(255,255,255,0.14);

  --text-primary:   #f5f7fa;
  --text-secondary: rgba(235,235,245,0.6);
  --text-muted:     rgba(235,235,245,0.38);

  --accent:         #00c26a;
  --accent-hover:   #00a85c;
  --accent-subtle:  rgba(0,194,106,0.14);
  --accent-glow:    rgba(0,194,106,0.25);
  --bullish:        #00c26a;
  --bearish:        #ef4444;
  --warning:        #f59e0b;
  --info:           #3b82f6;
  --violet:         #8b5cf6;

  --glow-strong: 0 0 20px rgba(0,194,106,0.2), 0 0 40px rgba(0,194,106,0.05);
  --glow-medium: 0 0 16px rgba(0,194,106,0.18);
}
```

- [ ] **Step 3: Add missing tokens to `:root` (light mode)**

In `:root`, add these lines after `--info`:

```css
  --violet: #8b5cf6;
  --border-strong: #c8ccd6;
  --accent-hover: #00a85c;
  --accent-glow: rgba(0,194,106,0.25);
```

Add radius tokens at the end of `:root`:

```css
  --radius-sm: 6px;
  --radius:    10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --shadow-card: 0 4px 14px rgba(0,0,0,0.25);

  --font-mono: var(--font-display);
```

- [ ] **Step 4: Update body background (the radial gradient)**

Find the `body { ... }` rule (around line 61). Replace with:

```css
body {
  font-family: var(--font-body);
  background:
    radial-gradient(ellipse at 20% 0%, rgba(0,194,106,0.08), transparent 55%),
    radial-gradient(ellipse at 80% 60%, rgba(59,130,246,0.06), transparent 55%),
    var(--surface-0);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
}
```

- [ ] **Step 5: Add animations at end of file**

Append to `globals.css`:

```css
@keyframes mover-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}
.animate-mover-pulse { animation: mover-pulse 7s ease-in-out infinite; }

@keyframes fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-up { animation: fade-up 260ms ease-out both; }

@keyframes strength-glow {
  0%, 100% { filter: drop-shadow(0 0 2px currentColor); }
  50% { filter: drop-shadow(0 0 6px currentColor); }
}

/* Safe-area padding helper for mobile tab bar */
.pb-safe { padding-bottom: calc(env(safe-area-inset-bottom) + 0px); }
```

- [ ] **Step 6: Verify lint passes**

Run: `cd frontend && npm run lint`
Expected: no errors introduced by the CSS changes. CSS is not linted by ESLint, but this ensures we didn't accidentally break a JSX file.

- [ ] **Step 7: Commit**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign
git add frontend/src/app/globals.css
git commit -m "style(tokens): extend design tokens for polyspotter redesign

Adds --violet, --border-strong, --accent-hover/-glow, radius scale,
and retunes dark palette to match the new design. Body gets the two
radial-gradient accents spec'd in §6."
```

---

### Task 2: Install `uvicorn` deps + verify dev server + run baseline tests

**Files:**
- None (installs + runs)

- [ ] **Step 1: Install frontend deps in the worktree**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/frontend && npm install
```
Expected: completes without errors.

- [ ] **Step 2: Install backend deps**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r backend/requirements.txt
```
Expected: all packages install.

- [ ] **Step 3: Baseline: run backend tests**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/backend
source ../venv/bin/activate
pytest -q
```
Expected: tests either pass OR are skipped due to `DATABASE_URL` not set. If anything **fails** that isn't a skip, investigate before proceeding.

- [ ] **Step 4: Baseline: run frontend lint**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/frontend && npm run lint
```
Expected: passes.

- [ ] **Step 5: No commit** (this task installs + verifies only)

---

## Phase 1 — Backend: `Signal` shape + adapter

### Task 3: Define Pydantic models for `Signal` + neighbors

**Files:**
- Modify: [backend/models.py](../../../backend/models.py)

- [ ] **Step 1: Append new models to `backend/models.py`**

Add at end of file:

```python
# ─── PolySpotter redesign models ─────────────────────────────────

class SignalMarket(BaseModel):
    condition_id: str | None = None
    title: str | None = None
    topic: str = "General"
    icon: str = "📈"
    end_date: datetime | None = None
    yes_price: float | None = None
    price_change_24h: float = 0.0
    volume_24h: float = 0.0
    candles: list[float] = []

class SignalWallet(BaseModel):
    addr: str
    alias: str
    tier: str  # "legend" | "sharp" | "prov"
    win_rate: float = 0.0
    pnl: float = 0.0
    bets: int = 0
    color: str

class SignalView(BaseModel):
    id: str
    created_at: datetime | None = None
    market: SignalMarket
    wallet: SignalWallet
    side: str | None = None  # "YES" | "NO"
    entry_price: float | None = None
    stake_usd: float = 0.0
    score: float = 0.0
    rating: int = 1   # 1..5
    why: str = ""
    signals: list[str] = []
    bullets: list[str] = []
    price_at_alert: float | None = None
    price_now: float | None = None
    return_pct: int = 0

class PaginatedSignals(BaseModel):
    signals: list[SignalView]
    total: int

class MoverView(BaseModel):
    condition_id: str
    title: str
    topic: str
    icon: str
    yes_price: float | None = None
    price_change_24h: float = 0.0
    volume_24h: float = 0.0
    candles: list[float] = []

class TopicView(BaseModel):
    name: str
    icon: str
    signals: int
    volume_24h: float
    trend: int  # +/- integer percent
    spark: list[float] = []

class TickerTradeView(BaseModel):
    id: str
    side: str    # "BUY" | "SELL"
    amount: float
    market: str
    condition_id: str | None = None
    price: float | None = None
    wallet_alias: str
    wallet_tier: str
    wallet_color: str
    timestamp: datetime | None = None

class DigestView(BaseModel):
    since: datetime | None = None
    new_signals: int
    strong_signals: int
    top_signals: list[SignalView] = []
    biggest_mover: MoverView | None = None
```

- [ ] **Step 2: Add a smoke test verifying models import and validate**

Create `backend/test_signals_models.py`:

```python
from datetime import datetime, timezone
from models import SignalView, SignalMarket, SignalWallet, PaginatedSignals

def test_signal_view_validates_minimal():
    s = SignalView(
        id="1",
        created_at=datetime.now(timezone.utc),
        market=SignalMarket(title="x", topic="Politics", icon="⚖️"),
        wallet=SignalWallet(addr="0xabc", alias="WOLF", tier="sharp", color="#00c26a"),
        stake_usd=10_000,
        score=15.0,
        rating=4,
        why="test",
        signals=["win_rate"],
        bullets=["a","b","c"],
    )
    assert s.rating == 4
    assert s.wallet.alias == "WOLF"
    assert s.market.icon == "⚖️"

def test_paginated_signals():
    p = PaginatedSignals(signals=[], total=0)
    assert p.total == 0
```

- [ ] **Step 3: Run it; verify pass**

```bash
cd backend && source ../venv/bin/activate && pytest test_signals_models.py -v
```
Expected: both tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/test_signals_models.py
git commit -m "feat(backend): add SignalView + Mover/Topic/Ticker/Digest pydantic models"
```

---

### Task 4: Topic mapping + icon resolution (`backend/topics.py`)

**Files:**
- Create: `backend/topics.py`
- Create: `backend/test_topics.py`

- [ ] **Step 1: Write failing test**

Create `backend/test_topics.py`:

```python
from topics import topic_for_tags, TAG_TO_TOPIC

def test_known_tag_maps_to_topic():
    assert topic_for_tags(["Politics"]) == ("Politics", "⚖️")
    assert topic_for_tags(["Crypto"]) == ("Crypto", "Ξ")
    assert topic_for_tags(["NBA"]) == ("NBA", "🏀")
    assert topic_for_tags(["Geopolitics"]) == ("Geopolitics", "🛢️")

def test_unknown_tag_falls_back_to_general():
    assert topic_for_tags(["Uncharted"]) == ("General", "📈")

def test_empty_tags_falls_back():
    assert topic_for_tags([]) == ("General", "📈")
    assert topic_for_tags(None) == ("General", "📈")

def test_first_matching_tag_wins():
    # Priority: the FIRST tag that maps gets used.
    assert topic_for_tags(["Unknown", "Politics"]) == ("Politics", "⚖️")

def test_tag_to_topic_contains_spec_topics():
    for t in ["Politics", "Economics", "Crypto", "NBA", "Geopolitics", "Science", "Soccer"]:
        assert t in TAG_TO_TOPIC
```

- [ ] **Step 2: Run; verify fail**

```bash
cd backend && pytest test_topics.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `backend/topics.py`**

```python
"""
Topic mapping: tags from alert rows → (topic_name, icon) used in the UI.

The UI's canonical topics and their icons come from the design handoff's
data.jsx. Tags in the DB are more granular; we collapse them.
"""
from __future__ import annotations

TAG_TO_TOPIC: dict[str, tuple[str, str]] = {
    "Politics":     ("Politics",    "⚖️"),
    "Economics":    ("Economics",   "📈"),
    "Crypto":       ("Crypto",      "Ξ"),
    "NBA":          ("NBA",         "🏀"),
    "Geopolitics":  ("Geopolitics", "🛢️"),
    "Science":      ("Science",     "🚀"),
    "Soccer":       ("Soccer",      "⚽"),
    # Aliases / cousins
    "Sports":       ("NBA",         "🏀"),
    "Elections":    ("Politics",    "⚖️"),
    "Fed":          ("Economics",   "🏦"),
    "Rates":        ("Economics",   "🏦"),
    "Middle East":  ("Geopolitics", "🛢️"),
    "Space":        ("Science",     "🚀"),
    "Tech":         ("Science",     "🚀"),
}

DEFAULT_TOPIC = ("General", "📈")

def topic_for_tags(tags: list[str] | None) -> tuple[str, str]:
    """Return (topic_name, icon) for the first tag that has a mapping."""
    if not tags:
        return DEFAULT_TOPIC
    for t in tags:
        if t in TAG_TO_TOPIC:
            return TAG_TO_TOPIC[t]
    return DEFAULT_TOPIC

# Canonical topic list surfaced by /api/topics
CANONICAL_TOPICS = [
    ("Politics",    "⚖️"),
    ("Economics",   "📈"),
    ("Crypto",      "Ξ"),
    ("NBA",         "🏀"),
    ("Geopolitics", "🛢️"),
    ("Science",     "🚀"),
]
```

- [ ] **Step 4: Run; verify pass**

```bash
pytest backend/test_topics.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/topics.py backend/test_topics.py
git commit -m "feat(backend): tag→topic mapping for polyspotter redesign"
```

---

### Task 5: Signal adapter (`backend/signals.py`) — Alert row → `SignalView`

**Files:**
- Create: `backend/signals.py`
- Create: `backend/test_signals.py`

- [ ] **Step 1: Write failing tests first**

Create `backend/test_signals.py`:

```python
import json
from datetime import datetime, timezone
from signals import (
    bucket_rating,
    tier_for_wallet,
    color_for_wallet,
    return_pct,
    signal_from_row,
)

def test_rating_buckets():
    assert bucket_rating(30.0) == 5
    assert bucket_rating(25.0) == 5
    assert bucket_rating(24.9) == 4
    assert bucket_rating(18.0) == 4
    assert bucket_rating(12.0) == 3
    assert bucket_rating(11.99) == 2
    assert bucket_rating(7.0) == 2
    assert bucket_rating(6.9) == 1
    assert bucket_rating(0) == 1

def test_tier_legend_requires_both():
    assert tier_for_wallet(win_rate=0.92, pnl=500_000) == "legend"
    assert tier_for_wallet(win_rate=0.92, pnl=100_000) == "sharp"  # pnl too low
    assert tier_for_wallet(win_rate=0.75, pnl=500_000) == "sharp"  # winrate too low

def test_tier_sharp_and_prov():
    assert tier_for_wallet(win_rate=0.72, pnl=10_000) == "sharp"
    assert tier_for_wallet(win_rate=0.50, pnl=10_000) == "prov"
    assert tier_for_wallet(win_rate=None,  pnl=None)  == "prov"

def test_color_is_stable_per_address():
    c1 = color_for_wallet("0x7a3b4f21")
    c2 = color_for_wallet("0x7a3b4f21")
    c3 = color_for_wallet("0x1c4e8a09")
    assert c1 == c2
    assert c1 in {"#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"}
    assert c3 in {"#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"}

def test_return_pct_yes():
    # YES at 20¢: if it resolves yes → 1.0; return = (1 - 0.20)/0.20 = 4.0 → 400%
    assert return_pct("YES", 0.20) == 400

def test_return_pct_no():
    # NO at 20¢: if it resolves no → 1.0; return = 0.20/(1-0.20) = 0.25 → 25%
    # Wait — NO at 20¢ means YES is priced 80¢. If NO resolves (YES doesn't happen),
    # NO share pays $1. Entry was $0.20 → return = (1-0.20)/0.20 = 400%. Spec is
    # unambiguous: returnPct is the return on the side taken at its quoted price.
    assert return_pct("NO", 0.80) == 25    # entered NO at 80¢ → (1-0.80)/0.80 = 25%
    assert return_pct("NO", 0.20) == 400

def test_return_pct_handles_edge_cases():
    assert return_pct(None, 0.5) == 0
    assert return_pct("YES", None) == 0
    assert return_pct("YES", 0) == 0
    assert return_pct("YES", 1.0) == 0

def _row(**over):
    base = {
        "id": 1,
        "composite_score": 18.2,
        "tags": '["Crypto"]',
        "market_title": "Ethereum above $4,200 on April 30",
        "condition_id": "0xcid",
        "event_slug": "ethereum-above-4200",
        "market_url": "https://polymarket.com/event/eth",
        "market_image": None,
        "market_description": None,
        "wallet": "0x1c4e8a09",
        "total_usd": 31_700,
        "trade_count": 1,
        "cluster_headline": None,
        "end_date": datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc),
        "llm_headline": "ETH cluster",
        "llm_summary": "Cluster of 4 linked wallets bet $112k combined on ETH > $4,200.",
        "llm_bullets": '["A", "B", "C"]',
        "llm_copy_action": '{}',
        "scanned_at": None,
        "created_at": datetime.now(timezone.utc),
        "win_rate": 0.84,
        "total_pnl": 218_000.0,
        "total_invested": 260_000.0,
    }
    base.update(over)
    return base

def test_signal_from_row_basic_shape():
    row = _row()
    s = signal_from_row(row, trades=[], live={"yes_price": 0.44, "price_change_24h": 0.12, "volume_24h": 1_180_000, "candles": [0.31,0.35,0.40,0.44]})
    assert s.id == "1"
    assert s.market.topic == "Crypto"
    assert s.market.icon == "Ξ"
    assert s.wallet.alias != ""
    assert s.wallet.tier == "sharp"
    assert s.stake_usd == 31_700
    assert s.score == 18.2
    assert s.rating == 4
    assert s.why.startswith("Cluster of 4")
    assert s.bullets == ["A", "B", "C"]
    assert s.market.yes_price == 0.44
    assert s.market.candles == [0.31,0.35,0.40,0.44]

def test_signal_from_row_fills_side_and_entry_from_trades():
    row = _row()
    trade = {"side": "BUY", "outcome": "YES", "price": 0.41, "trade_timestamp": datetime.now(timezone.utc), "usd_value": 31_700}
    s = signal_from_row(row, trades=[trade], live={"yes_price": 0.44})
    assert s.side == "YES"
    assert s.entry_price == 0.41
    assert s.price_at_alert == 0.41
    assert s.price_now == 0.44

def test_signal_from_row_pads_bullets_to_three():
    row = _row(llm_bullets='["one"]')
    s = signal_from_row(row, trades=[], live={})
    assert len(s.bullets) == 3
    assert s.bullets[0] == "one"

def test_signal_from_row_why_fallbacks():
    row = _row(llm_summary=None, cluster_headline="cluster")
    s = signal_from_row(row, trades=[], live={})
    assert s.why == "cluster"

    row2 = _row(llm_summary=None, cluster_headline=None, llm_headline="head")
    s2 = signal_from_row(row2, trades=[], live={})
    assert s2.why == "head"

def test_signal_from_row_no_trades_returns_null_side():
    s = signal_from_row(_row(), trades=[], live={})
    assert s.side is None
    assert s.entry_price is None
    assert s.return_pct == 0
```

- [ ] **Step 2: Run; verify fail**

```bash
pytest backend/test_signals.py -v
```
Expected: ModuleNotFoundError for `signals`.

- [ ] **Step 3: Implement `backend/signals.py`**

```python
"""
Signal adapter: Alert DB row + joined trades + joined live price → SignalView.

This module is the single source of truth for the design's Signal shape.
When the Alert table changes or when the UI's Signal shape changes, the
mapping is updated HERE and nowhere else.

Shape spec: docs/superpowers/specs/2026-04-17-polyspotter-redesign-design.md §4.1
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Any

from models import SignalView, SignalMarket, SignalWallet
from topics import topic_for_tags
from pseudonym import alias_for_wallet  # reuse existing alias logic

_WALLET_PALETTE = ["#f59e0b", "#00c26a", "#8b5cf6", "#3b82f6", "#ec4899", "#06b6d4"]


def bucket_rating(score: float | None) -> int:
    """Map composite_score → 1..5 per spec §4.3."""
    s = float(score or 0)
    if s >= 25: return 5
    if s >= 18: return 4
    if s >= 12: return 3
    if s >= 7:  return 2
    return 1


def tier_for_wallet(win_rate: float | None, pnl: float | None) -> str:
    w = float(win_rate or 0)
    p = float(pnl or 0)
    if w >= 0.88 and p >= 300_000:
        return "legend"
    if w >= 0.72:
        return "sharp"
    return "prov"


def color_for_wallet(addr: str) -> str:
    """Deterministic color from a wallet address."""
    if not addr:
        return _WALLET_PALETTE[0]
    h = hashlib.md5(addr.encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % len(_WALLET_PALETTE)
    return _WALLET_PALETTE[idx]


def return_pct(side: str | None, entry: float | None) -> int:
    """Implied return on the side taken, given entry price.

    YES at E: if resolves YES, share pays $1 → return (1-E)/E.
    NO  at E: if resolves NO,  share pays $1 → return (1-E)/E.
    Same formula — we're quoting entry price of the side taken, not yesPrice.
    """
    if side not in ("YES", "NO"):
        return 0
    if entry is None or entry <= 0 or entry >= 1:
        return 0
    return round((1 - entry) / entry * 100)


def _parse_json_field(raw: Any, default: Any):
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def signal_from_row(row: dict, trades: list[dict] | None, live: dict | None) -> SignalView:
    """Build a SignalView from an alerts row + its joined trades + live market data.

    `trades`: list of alert_trades rows (earliest-first recommended).
    `live`:   dict with yes_price, price_change_24h, volume_24h, candles (any may be absent).
    """
    trades = trades or []
    live = live or {}

    tags = _parse_json_field(row.get("tags"), [])
    bullets = _parse_json_field(row.get("llm_bullets"), [])
    # Pad to 3 so the UI can always render three lines.
    while len(bullets) < 3:
        bullets.append("")

    topic, icon = topic_for_tags(tags)

    # Pick the first trade (earliest or largest — use first as canonical).
    t0 = trades[0] if trades else None
    side = None
    entry_price = None
    if t0:
        outcome = (t0.get("outcome") or "").upper()
        # outcome might literally be "Yes"/"No" or blank; side column is BUY/SELL.
        # We map outcome → YES/NO. If outcome is empty, try inferring from "side" on the market.
        if outcome in ("YES", "NO"):
            side = outcome
        entry_price = t0.get("price")

    why = (
        row.get("llm_summary")
        or row.get("cluster_headline")
        or row.get("llm_headline")
        or ""
    )

    addr = row.get("wallet") or ""
    alias = alias_for_wallet(addr) if addr else "ANON"

    market = SignalMarket(
        condition_id=row.get("condition_id"),
        title=row.get("market_title"),
        topic=topic,
        icon=icon,
        end_date=row.get("end_date"),
        yes_price=live.get("yes_price"),
        price_change_24h=float(live.get("price_change_24h") or 0),
        volume_24h=float(live.get("volume_24h") or 0),
        candles=list(live.get("candles") or []),
    )

    wallet = SignalWallet(
        addr=addr,
        alias=alias,
        tier=tier_for_wallet(row.get("win_rate"), row.get("total_pnl")),
        win_rate=float(row.get("win_rate") or 0),
        pnl=float(row.get("total_pnl") or 0),
        bets=int(row.get("trade_count") or 0),
        color=color_for_wallet(addr),
    )

    score = float(row.get("composite_score") or 0)

    return SignalView(
        id=str(row.get("id")),
        created_at=row.get("created_at"),
        market=market,
        wallet=wallet,
        side=side,
        entry_price=entry_price,
        stake_usd=float(row.get("total_usd") or 0),
        score=score,
        rating=bucket_rating(score),
        why=why,
        signals=[],  # filled by the endpoint from alert_signals rows
        bullets=bullets,
        price_at_alert=entry_price,
        price_now=live.get("yes_price") if side == "YES" else (
            None if live.get("yes_price") is None else round(1 - live["yes_price"], 4)
        ) if side == "NO" else live.get("yes_price"),
        return_pct=return_pct(side, entry_price),
    )
```

Also need a tiny `alias_for_wallet` import — if `backend/pseudonym.py` doesn't exist yet, port the one from `frontend/src/lib/pseudonym.js` into Python.

- [ ] **Step 4: Port `pseudonym.js` → `backend/pseudonym.py` if missing**

Check:
```bash
ls backend/pseudonym.py 2>/dev/null || echo MISSING
```

If MISSING, create `backend/pseudonym.py`:

```python
"""Deterministic wallet alias generator (port of frontend/src/lib/pseudonym.js)."""
import hashlib

_ANIMALS = [
    "RHINO","ORACLE","CICADA","WOLF","FOX","HERON",
    "OTTER","RAVEN","PANDA","HAWK","LYNX","GECKO",
    "KOI","MARLIN","FINCH","IBEX","MAMBA","OSPREY",
]

def alias_for_wallet(addr: str) -> str:
    if not addr:
        return "ANON"
    h = hashlib.md5(addr.lower().encode()).hexdigest()
    return _ANIMALS[int(h[:8], 16) % len(_ANIMALS)]
```

(If `frontend/src/lib/pseudonym.js` uses a different list, mirror it. Check and align.)

- [ ] **Step 5: Run tests; verify pass**

```bash
pytest backend/test_signals.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/signals.py backend/test_signals.py backend/pseudonym.py
git commit -m "feat(backend): alert→SignalView adapter with deterministic alias/color

Implements bucket_rating/tier_for_wallet/color_for_wallet/return_pct
and signal_from_row per spec §4.1–§4.3."
```

---

### Task 6: Backend live-price helper (pull live market data cheaply)

**Files:**
- Create: `backend/live_prices.py`
- Create: `backend/test_live_prices.py`

- [ ] **Step 1: Write failing tests**

Create `backend/test_live_prices.py`:

```python
from live_prices import batch_live_for_condition_ids

def test_batch_live_returns_dict_keyed_by_condition_id(monkeypatch):
    # No DB: we just test the fallback shape when rows are empty.
    monkeypatch.setattr("live_prices._fetch_batch", lambda ids: {})
    result = batch_live_for_condition_ids(["cid1","cid2"])
    assert isinstance(result, dict)
    assert result.get("cid1", {}).get("yes_price") is None
```

- [ ] **Step 2: Run; verify fail**

```bash
pytest backend/test_live_prices.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `backend/live_prices.py`**

```python
"""
Batch live-price loader. Pulls yes_price / priceChange24h / volume24h / candles
for a set of condition_ids in one DB round-trip (plus gamma_cache hit if needed).

Used by /api/signals and /api/markets/movers to avoid N+1 fetches.
"""
from __future__ import annotations

from typing import Any

from database import get_conn


def _fetch_batch(condition_ids: list[str]) -> dict[str, dict]:
    """Query gamma_cache / price_history for the requested condition_ids.

    Returns: { condition_id: {yes_price, price_change_24h, volume_24h, candles[]} }
    """
    if not condition_ids:
        return {}

    conn = get_conn()
    try:
        cur = conn.cursor()
        # Primary source: gamma_cache (populated by scanner). Column names follow
        # the existing gamma_cache.py module; adjust if schema differs.
        cur.execute(
            """
            SELECT condition_id, yes_price, price_change_24h, volume_24h, candles
            FROM gamma_cache
            WHERE condition_id = ANY(%s)
            """,
            (condition_ids,),
        )
        out: dict[str, dict] = {}
        for r in cur.fetchall():
            cid = r["condition_id"]
            candles = r.get("candles") or []
            # Normalize candles to a list[float] (may be TEXT/JSON in DB).
            if isinstance(candles, str):
                import json
                try:
                    candles = json.loads(candles)
                except Exception:
                    candles = []
            out[cid] = {
                "yes_price": r.get("yes_price"),
                "price_change_24h": r.get("price_change_24h") or 0,
                "volume_24h": r.get("volume_24h") or 0,
                "candles": candles or [],
            }
        return out
    except Exception:
        return {}
    finally:
        conn.close()


def batch_live_for_condition_ids(condition_ids: list[str]) -> dict[str, dict]:
    """Public API. Returns a dict keyed by condition_id; missing ids have empty dicts."""
    fetched = _fetch_batch(condition_ids)
    return {cid: fetched.get(cid, {}) for cid in condition_ids}
```

**Note:** If `gamma_cache` table doesn't have all those columns, this query will fail. Before committing, verify the columns exist:
```bash
grep -A5 "CREATE TABLE.*gamma_cache" backend/schema.sql
```
If columns are missing, adjust the SELECT list to what's actually there and compute the missing fields from `price_history` as a fallback.

- [ ] **Step 4: Run test; verify pass**

```bash
pytest backend/test_live_prices.py -v
```
Expected: PASS (test uses monkeypatch, doesn't touch DB).

- [ ] **Step 5: Commit**

```bash
git add backend/live_prices.py backend/test_live_prices.py
git commit -m "feat(backend): batch live-price loader for signal/mover endpoints"
```

---

## Phase 2 — Primary signal endpoints

### Task 7: `GET /api/signals`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py) (append new route)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Write failing test**

Append to `backend/test_endpoints.py`:

```python
@skip_no_db
def test_api_signals_returns_shape(self_seed_signal_fixture):
    """After the fixture seeds one TEST: alert, /api/signals returns it."""
    r = client.get("/api/signals?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "signals" in body
    assert "total" in body
    if body["signals"]:
        s = body["signals"][0]
        # Canonical shape fields
        for k in ("id","created_at","market","wallet","side","entry_price","stake_usd",
                  "score","rating","why","signals","bullets","price_at_alert",
                  "price_now","return_pct"):
            assert k in s, f"missing field: {k}"
        assert s["market"]["topic"]
        assert s["market"]["icon"]
        assert s["wallet"]["alias"]
        assert 1 <= s["rating"] <= 5

@skip_no_db
def test_api_signals_filters_by_topic(self_seed_signal_fixture):
    # Seed row has tags=["Crypto"]; topic="Crypto" should return it.
    r_on  = client.get("/api/signals?topic=Crypto&limit=10")
    r_off = client.get("/api/signals?topic=NBA&limit=10")
    assert r_on.status_code == 200 and r_off.status_code == 200
    assert any(s["id"] for s in r_on.json()["signals"])
    # Our test row shouldn't match NBA
    # (may still find other rows if DB has NBA data; only assert on the seeded one)
```

And add this fixture at the top of `test_endpoints.py`:

```python
@pytest.fixture
def self_seed_signal_fixture():
    if not _has_db:
        pytest.skip("no DB")
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alerts (alert_type, composite_score, tags, market_title,
                condition_id, wallet, total_usd, trade_count, llm_summary, llm_bullets,
                created_at)
            VALUES ('composite', 18.2, '["Crypto"]', 'TEST: ETH 4200', 'cid-TEST', '0xTEST',
                    31700, 1, 'TEST why', '["a","b","c"]', NOW())
            RETURNING id
            """
        )
        alert_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO alert_trades (alert_id, transaction_hash, wallet, condition_id,
                outcome, side, usd_value, price)
            VALUES (%s, 'tx-TEST', '0xTEST', 'cid-TEST', 'YES', 'BUY', 31700, 0.41)
            """,
            (alert_id,),
        )
        cur.execute(
            """INSERT INTO alert_signals (alert_id, strategy, severity, headline)
               VALUES (%s, 'win_rate_tracking', 5.0, 'h')""",
            (alert_id,),
        )
    yield alert_id
    with db() as conn:
        _clean_test_data(conn)
```

- [ ] **Step 2: Run; verify fail**

```bash
cd backend && pytest test_endpoints.py::test_api_signals_returns_shape -v
```
Expected: FAIL (404 — endpoint doesn't exist).

- [ ] **Step 3: Implement the endpoint in `backend/app.py`**

Add import near top:

```python
from signals import signal_from_row
from topics import topic_for_tags
from live_prices import batch_live_for_condition_ids
from models import (
    # ... existing ...
    SignalView, PaginatedSignals, MoverView, TopicView, TickerTradeView, DigestView,
)
```

Append before the health check endpoint:

```python
# ─── PolySpotter redesign endpoints ─────────────────────────────

@app.get("/api/signals", response_model=PaginatedSignals)
def list_signals(
    topic: str | None = Query(None, description="Canonical topic name (Politics, Crypto, …)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    min_rating: int = Query(1, ge=1, le=5),
    resolves_within: str | None = Query(None, description="6h | 24h | 7d"),
):
    """Return alerts shaped as SignalView, pre-joined with live prices + trades."""
    min_score = {1: 0, 2: 7, 3: 12, 4: 18, 5: 25}[min_rating]
    conditions = ["a.composite_score >= %s", "(a.end_date IS NULL OR a.end_date > NOW())"]
    params: list = [min_score]

    resolve_hours = {"6h": 6, "24h": 24, "7d": 168}.get(resolves_within or "")
    if resolve_hours:
        conditions.append("a.end_date IS NOT NULL AND a.end_date <= NOW() + (%s || ' hours')::interval")
        params.append(str(resolve_hours))

    if topic:
        # Map topic → any tags that resolve to this topic
        from topics import TAG_TO_TOPIC
        matching = [tag for tag, (t, _) in TAG_TO_TOPIC.items() if t == topic]
        if matching:
            conditions.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) AS t "
                "WHERE t = ANY(%s))"
            )
            params.append(matching)
        else:
            # Unknown topic → return empty
            return PaginatedSignals(signals=[], total=0)

    where = " AND ".join(conditions)

    with db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) as c FROM alerts a WHERE {where}", params)
        total = cur.fetchone()["c"]

        cur.execute(
            f"""
            SELECT a.*, wp.win_rate, wp.total_pnl, wp.total_invested
            FROM alerts a
            LEFT JOIN wallet_profiles wp ON wp.wallet = a.wallet
            WHERE {where}
            ORDER BY a.composite_score DESC, a.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return PaginatedSignals(signals=[], total=total)

        alert_ids = [r["id"] for r in rows]
        cur.execute(
            "SELECT alert_id, outcome, side, price, usd_value, trade_timestamp "
            "FROM alert_trades WHERE alert_id = ANY(%s) ORDER BY trade_timestamp ASC",
            (alert_ids,),
        )
        trades_by_alert: dict[int, list[dict]] = {}
        for t in cur.fetchall():
            trades_by_alert.setdefault(t["alert_id"], []).append(dict(t))

        cur.execute(
            "SELECT alert_id, strategy FROM alert_signals WHERE alert_id = ANY(%s)",
            (alert_ids,),
        )
        sigs_by_alert: dict[int, list[str]] = {}
        for s in cur.fetchall():
            sigs_by_alert.setdefault(s["alert_id"], []).append(s["strategy"])

    # Live data in one batch
    cids = [r["condition_id"] for r in rows if r.get("condition_id")]
    live_map = batch_live_for_condition_ids(cids)

    signals = []
    for r in rows:
        trades = trades_by_alert.get(r["id"], [])
        live = live_map.get(r.get("condition_id") or "", {})
        s = signal_from_row(r, trades=trades, live=live)
        # Attach strategies as signal types
        strategies = sigs_by_alert.get(r["id"], [])
        # Map strategy names to the design's SIGNAL_LABELS keys
        s.signals = _map_strategies_to_signal_keys(strategies)
        signals.append(s)

    return PaginatedSignals(signals=signals, total=total)


def _map_strategies_to_signal_keys(strategies: list[str]) -> list[str]:
    """Translate backend strategy names → design's SIGNAL_LABELS keys."""
    mapping = {
        "win_rate_tracking":        "win_rate",
        "new_wallet_large_bet":     "new_wallet",
        "timing_relative_resolution":"timing_close",
        "low_activity_large_bet":   "low_activity",
        "pre_event_volume_spike":   "volume_spike",
        "wallet_clustering":        "wallet_cluster",
        "concentrated_one_sided":   "concentrated_one_sided",
        "price_impact":             "price_impact",
        "correlated_cross_market":  "correlated_cross_market",
    }
    out = []
    for s in strategies:
        k = mapping.get(s)
        if k and k not in out:
            out.append(k)
    return out
```

- [ ] **Step 4: Run tests; verify pass**

```bash
cd backend && pytest test_endpoints.py::test_api_signals_returns_shape test_endpoints.py::test_api_signals_filters_by_topic -v
```
Expected: PASS (or SKIP if no DATABASE_URL — that's acceptable; re-run with DB set).

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "feat(api): GET /api/signals returning Signal-shaped paginated feed"
```

---

### Task 8: `GET /api/signals/top`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Add failing test**

```python
@skip_no_db
def test_api_signals_top_returns_up_to_three(self_seed_signal_fixture):
    r = client.get("/api/signals/top")
    assert r.status_code == 200
    body = r.json()
    assert "signals" in body
    assert isinstance(body["signals"], list)
    assert len(body["signals"]) <= 3
```

- [ ] **Step 2: Run; verify fail**

- [ ] **Step 3: Implement endpoint in `backend/app.py`** (append):

```python
@app.get("/api/signals/top")
def list_top_signals():
    """Curated Top 3 signals by composite_score with recency tiebreak."""
    result = list_signals(topic=None, limit=3, offset=0, min_rating=1, resolves_within=None)
    return {"signals": result.signals}
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_endpoints.py
git commit -m "feat(api): GET /api/signals/top returning the curated Top 3"
```

---

## Phase 3 — Secondary endpoints

### Task 9: `GET /api/markets/movers`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Write failing test**

```python
@skip_no_db
def test_api_markets_movers_returns_list(self_seed_signal_fixture):
    r = client.get("/api/markets/movers?limit=6")
    assert r.status_code == 200
    body = r.json()
    assert "movers" in body
    assert isinstance(body["movers"], list)
    assert len(body["movers"]) <= 6
    for m in body["movers"]:
        for k in ("condition_id","title","topic","icon","yes_price",
                  "price_change_24h","volume_24h","candles"):
            assert k in m
```

- [ ] **Step 2: Run; verify fail**

- [ ] **Step 3: Implement**

Append to `backend/app.py`:

```python
@app.get("/api/markets/movers")
def list_movers(limit: int = Query(6, ge=1, le=20)):
    """Top movers: markets with alerts in the last 24h, sorted by abs(price_change_24h)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (a.condition_id)
                a.condition_id, a.market_title, a.tags, a.end_date,
                gc.yes_price, gc.price_change_24h, gc.volume_24h, gc.candles
            FROM alerts a
            LEFT JOIN gamma_cache gc ON gc.condition_id = a.condition_id
            WHERE a.condition_id IS NOT NULL
              AND (a.end_date IS NULL OR a.end_date > NOW())
              AND a.created_at > NOW() - INTERVAL '24 hours'
            ORDER BY a.condition_id, a.composite_score DESC
            LIMIT 100
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    # Sort in Python by abs(price_change_24h). Fall back to volume_24h for ties.
    def key(r):
        pc = abs(float(r.get("price_change_24h") or 0))
        return (-pc, -(float(r.get("volume_24h") or 0)))
    rows.sort(key=key)
    rows = rows[:limit]

    out = []
    for r in rows:
        tags = _parse_tags(r.get("tags"))
        topic, icon = topic_for_tags(tags)
        candles = r.get("candles") or []
        if isinstance(candles, str):
            try: candles = json.loads(candles)
            except Exception: candles = []
        out.append(MoverView(
            condition_id=r["condition_id"],
            title=r.get("market_title") or "",
            topic=topic, icon=icon,
            yes_price=r.get("yes_price"),
            price_change_24h=float(r.get("price_change_24h") or 0),
            volume_24h=float(r.get("volume_24h") or 0),
            candles=candles,
        ))
    return {"movers": out}


def _parse_tags(raw):
    if raw is None: return []
    if isinstance(raw, list): return raw
    try: return json.loads(raw)
    except Exception: return []
```

- [ ] **Step 4: Run tests; verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): GET /api/markets/movers for the live-movers strip"
```

---

### Task 10: `GET /api/topics`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Write failing test**

```python
@skip_no_db
def test_api_topics_returns_canonical_list():
    r = client.get("/api/topics")
    assert r.status_code == 200
    body = r.json()
    assert "topics" in body
    names = {t["name"] for t in body["topics"]}
    assert {"Politics","Economics","Crypto","NBA","Geopolitics","Science"} <= names
    for t in body["topics"]:
        for k in ("name","icon","signals","volume_24h","trend","spark"):
            assert k in t
        assert isinstance(t["spark"], list)
```

- [ ] **Step 2: Run; verify fail**

- [ ] **Step 3: Implement**

Append:

```python
@app.get("/api/topics")
def list_topics():
    """Activity summary per canonical topic over the last 24h."""
    from topics import CANONICAL_TOPICS, TAG_TO_TOPIC
    out = []
    with db() as conn:
        cur = conn.cursor()
        for (topic_name, icon) in CANONICAL_TOPICS:
            matching = [t for t, (nm, _) in TAG_TO_TOPIC.items() if nm == topic_name]
            if not matching:
                out.append(TopicView(name=topic_name, icon=icon, signals=0,
                                     volume_24h=0, trend=0, spark=[]))
                continue
            cur.execute(
                """
                SELECT
                    COUNT(*)::int                                 AS signal_count,
                    COALESCE(SUM(total_usd),0)::float             AS vol_24h,
                    ARRAY(
                        SELECT COUNT(a2.id)::int
                        FROM generate_series(0,7) AS bucket
                        LEFT JOIN alerts a2 ON
                            a2.created_at >= NOW() - ((8 - bucket) * INTERVAL '3 hours')
                            AND a2.created_at <  NOW() - ((7 - bucket) * INTERVAL '3 hours')
                            AND EXISTS (
                                SELECT 1 FROM jsonb_array_elements_text(a2.tags::jsonb) t
                                WHERE t = ANY(%s)
                            )
                        GROUP BY bucket ORDER BY bucket
                    ) AS spark_ints
                FROM alerts a
                WHERE a.created_at > NOW() - INTERVAL '24 hours'
                  AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(a.tags::jsonb) t
                    WHERE t = ANY(%s)
                  )
                """,
                (matching, matching),
            )
            row = cur.fetchone()
            signal_count = row["signal_count"] or 0
            vol_24h = float(row["vol_24h"] or 0)
            spark = list(row.get("spark_ints") or [])
            # trend: percent change from first-half to second-half of 24h (rough)
            half = len(spark) // 2 or 1
            first = sum(spark[:half]) or 1
            second = sum(spark[half:])
            trend = round((second - first) / first * 100)
            out.append(TopicView(
                name=topic_name, icon=icon,
                signals=signal_count, volume_24h=vol_24h,
                trend=trend, spark=[float(x) for x in spark],
            ))
    return {"topics": out}
```

- [ ] **Step 4: Run tests; verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): GET /api/topics returning 6-tile activity summary"
```

---

### Task 11: `GET /api/digest`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Write failing test**

```python
from datetime import datetime, timezone, timedelta

@skip_no_db
def test_api_digest_returns_counts_since_timestamp(self_seed_signal_fixture):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.get(f"/api/digest?since={past}")
    assert r.status_code == 200
    body = r.json()
    for k in ("since","new_signals","strong_signals","top_signals","biggest_mover"):
        assert k in body
    assert body["new_signals"] >= 1  # our fixture row
    assert isinstance(body["top_signals"], list)
```

- [ ] **Step 2: Run; verify fail**

- [ ] **Step 3: Implement**

Append:

```python
@app.get("/api/digest", response_model=DigestView)
def get_digest(since: datetime = Query(..., description="ISO8601 last-visit timestamp")):
    """Summary of activity since a given timestamp."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM alerts WHERE created_at > %s",
            (since,),
        )
        new_signals = cur.fetchone()["c"] or 0
        cur.execute(
            "SELECT COUNT(*) AS c FROM alerts WHERE created_at > %s AND composite_score >= 18",
            (since,),
        )
        strong = cur.fetchone()["c"] or 0

    top = list_signals(topic=None, limit=3, offset=0, min_rating=1, resolves_within=None)
    movers = list_movers(limit=1)["movers"]
    biggest = movers[0] if movers else None
    return DigestView(
        since=since,
        new_signals=new_signals,
        strong_signals=strong,
        top_signals=top.signals,
        biggest_mover=biggest,
    )
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): GET /api/digest summarizing activity since a timestamp"
```

---

### Task 12: `GET /api/ticker/recent`

**Files:**
- Modify: [backend/app.py](../../../backend/app.py)
- Modify: [backend/test_endpoints.py](../../../backend/test_endpoints.py)

- [ ] **Step 1: Write failing test**

```python
@skip_no_db
def test_api_ticker_recent_returns_trades(self_seed_signal_fixture):
    r = client.get("/api/ticker/recent?limit=20")
    assert r.status_code == 200
    body = r.json()
    assert "trades" in body
    assert isinstance(body["trades"], list)
    if body["trades"]:
        t = body["trades"][0]
        for k in ("id","side","amount","market","price","wallet_alias","wallet_tier","wallet_color","timestamp"):
            assert k in t
```

- [ ] **Step 2: Run; verify fail**

- [ ] **Step 3: Implement**

Append:

```python
from signals import tier_for_wallet, color_for_wallet
from pseudonym import alias_for_wallet

@app.get("/api/ticker/recent")
def ticker_recent(limit: int = Query(20, ge=1, le=100)):
    """Latest N trades across all alerts, newest first."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.transaction_hash AS id, t.side, t.usd_value AS amount, t.price,
                   t.wallet, t.trade_timestamp AS ts,
                   a.market_title, a.condition_id,
                   wp.win_rate, wp.total_pnl
            FROM alert_trades t
            JOIN alerts a ON a.id = t.alert_id
            LEFT JOIN wallet_profiles wp ON wp.wallet = t.wallet
            WHERE t.trade_timestamp IS NOT NULL
            ORDER BY t.trade_timestamp DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    trades = []
    for r in rows:
        trades.append(TickerTradeView(
            id=r["id"],
            side=(r["side"] or "BUY").upper(),
            amount=float(r["amount"] or 0),
            market=r["market_title"] or "",
            condition_id=r["condition_id"],
            price=r["price"],
            wallet_alias=alias_for_wallet(r["wallet"] or ""),
            wallet_tier=tier_for_wallet(r["win_rate"], r["total_pnl"]),
            wallet_color=color_for_wallet(r["wallet"] or ""),
            timestamp=r["ts"],
        ))
    return {"trades": trades}
```

- [ ] **Step 4: Run; verify pass**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): GET /api/ticker/recent for the live trade ticker"
```

---

## Phase 4 — Frontend: primitives + lib

### Task 13: UI primitives — `Chip`, `StrengthBars`, `CountdownText`, `WalletAvatar`

**Files:**
- Create: `frontend/src/components/ui/Chip.jsx`
- Create: `frontend/src/components/ui/StrengthBars.jsx`
- Create: `frontend/src/components/ui/CountdownText.jsx`
- Create: `frontend/src/components/ui/WalletAvatar.jsx`

- [ ] **Step 1: Create `Chip.jsx`**

```jsx
const TONES = {
  default: { bg: "var(--surface-2)",                   fg: "var(--text-secondary)", bd: "transparent" },
  accent:  { bg: "var(--accent-subtle)",               fg: "var(--accent)",         bd: "rgba(0,194,106,0.3)" },
  danger:  { bg: "rgba(239,68,68,0.1)",                fg: "var(--bearish)",        bd: "rgba(239,68,68,0.3)" },
  warn:    { bg: "rgba(245,158,11,0.1)",               fg: "var(--warning)",        bd: "rgba(245,158,11,0.3)" },
  info:    { bg: "rgba(59,130,246,0.1)",               fg: "var(--info)",           bd: "rgba(59,130,246,0.3)" },
  violet:  { bg: "rgba(139,92,246,0.1)",               fg: "var(--violet)",         bd: "rgba(139,92,246,0.3)" },
};

export default function Chip({ tone = "default", children, className = "", ...rest }) {
  const t = TONES[tone] || TONES.default;
  return (
    <span
      {...rest}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold tracking-wide ${className}`}
      style={{ background: t.bg, color: t.fg, border: `1px solid ${t.bd}`, fontFamily: "var(--font-mono)" }}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 2: Create `StrengthBars.jsx`**

```jsx
export default function StrengthBars({ rating = 0, className = "" }) {
  const color =
    rating >= 4 ? "var(--accent)" :
    rating >= 3 ? "#f97316" :
    rating >= 2 ? "var(--warning)" :
                  "var(--text-muted)";
  return (
    <div
      role="meter"
      aria-valuemin={1}
      aria-valuemax={5}
      aria-valuenow={rating}
      aria-label={`Signal strength ${rating} of 5`}
      className={`inline-flex items-end gap-[2px] h-[14px] ${className}`}
    >
      {[1,2,3,4,5].map((i) => (
        <span
          key={i}
          style={{
            width: 3,
            height: 3 + i * 2,
            borderRadius: 1,
            background: i <= rating ? color : "var(--border)",
            boxShadow: i <= rating && rating >= 4 ? `0 0 4px ${color}` : "none",
            transition: "all 180ms",
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `CountdownText.jsx`**

```jsx
"use client";
import { useEffect, useState } from "react";

function fmt(ms) {
  if (ms <= 0) return { label: "resolved", urgent: false, soon: false };
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  let label = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
  return { label, urgent: ms < 3600_000, soon: ms < 86400_000 };
}

export default function CountdownText({ endDate, className = "" }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);
  if (!endDate) return <span className={className}>—</span>;
  const end = new Date(endDate).getTime();
  const c = fmt(end - now);
  return (
    <span
      className={className}
      style={{
        fontFamily: "var(--font-mono)",
        color: c.urgent ? "var(--bearish)" : c.soon ? "var(--warning)" : "var(--text-secondary)",
        fontWeight: 600,
      }}
    >
      {c.label}
    </span>
  );
}
```

- [ ] **Step 4: Create `WalletAvatar.jsx`**

```jsx
export default function WalletAvatar({ wallet, size = 26 }) {
  if (!wallet) return null;
  const c = wallet.color || "#00c26a";
  return (
    <div
      title={wallet.addr}
      style={{
        width: size, height: size,
        borderRadius: size >= 32 ? "50%" : 7,
        display: "inline-grid", placeItems: "center",
        background: `linear-gradient(135deg, ${c}, ${c}88)`,
        color: "#fff",
        fontFamily: "var(--font-mono)",
        fontWeight: 700,
        fontSize: size * 0.34,
        letterSpacing: 0.3,
        flexShrink: 0,
      }}
    >
      {(wallet.alias || "??").slice(0, 2)}
    </div>
  );
}
```

- [ ] **Step 5: Lint + commit**

```bash
cd frontend && npm run lint
```
Expected: passes.

```bash
git add frontend/src/components/ui/
git commit -m "feat(ui): Chip + StrengthBars + CountdownText + WalletAvatar primitives"
```

---

### Task 14: `BookmarkButton` + `CopyButton` primitives

**Files:**
- Create: `frontend/src/components/ui/BookmarkButton.jsx`
- Create: `frontend/src/components/ui/CopyButton.jsx`

- [ ] **Step 1: Create `BookmarkButton.jsx`**

```jsx
"use client";
export default function BookmarkButton({ active, onClick, size = 40 }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={!!active}
      aria-label={active ? "Remove from watchlist" : "Add to watchlist"}
      style={{
        width: size, height: size, borderRadius: 10,
        background: active ? "var(--accent-subtle)" : "rgba(255,255,255,0.06)",
        border: `1px solid ${active ? "rgba(0,194,106,0.4)" : "var(--border)"}`,
        color: active ? "var(--accent)" : "var(--text-secondary)",
        display: "grid", placeItems: "center",
        transition: "transform 150ms, background 200ms",
        cursor: "pointer",
      }}
      onMouseDown={(e) => (e.currentTarget.style.transform = "scale(0.92)")}
      onMouseUp={(e) => (e.currentTarget.style.transform = "scale(1)")}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill={active ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>
      </svg>
    </button>
  );
}
```

- [ ] **Step 2: Create `CopyButton.jsx`**

```jsx
"use client";
export default function CopyButton({ onClick, returnPct, side = "YES", size = "md", full = false }) {
  const pad = size === "sm" ? "7px 12px" : size === "lg" ? "12px 20px" : "10px 14px";
  const fs = size === "sm" ? 11 : size === "lg" ? 15 : 13;
  return (
    <button
      onClick={onClick}
      style={{
        padding: pad,
        borderRadius: 10,
        background: "var(--accent)",
        color: "#001a0e",
        border: "none",
        fontWeight: 700,
        fontSize: fs,
        letterSpacing: 0.2,
        fontFamily: "var(--font-body)",
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        width: full ? "100%" : "auto",
        boxShadow: "var(--glow-medium)",
        cursor: "pointer",
        transition: "filter 150ms, transform 150ms",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(1.1)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = ""; e.currentTarget.style.transform = ""; }}
    >
      Copy {side} {typeof returnPct === "number" && returnPct > 0 && <span style={{ opacity: 0.7, fontWeight: 500 }}>· +{returnPct}%</span>}
    </button>
  );
}
```

- [ ] **Step 3: Lint**

```bash
cd frontend && npm run lint
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ui/BookmarkButton.jsx frontend/src/components/ui/CopyButton.jsx
git commit -m "feat(ui): BookmarkButton + CopyButton primitives"
```

---

### Task 15: localStorage watchlist lib + hook

**Files:**
- Create: `frontend/src/lib/watchlist.js`
- Create: `frontend/src/hooks/useWatchlist.js`

- [ ] **Step 1: `frontend/src/lib/watchlist.js`**

```js
const KEY = "polyspotter.watchlist.v1";

export function readWatchlist() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

export function writeWatchlist(ids) {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(KEY, JSON.stringify(ids.slice(0, 200))); } catch {}
  // Notify other tabs / components
  window.dispatchEvent(new CustomEvent("polyspotter.watchlist.change", { detail: ids }));
}

export function addToWatchlist(id) {
  const list = readWatchlist();
  if (list.includes(id)) return list;
  const next = [id, ...list];
  writeWatchlist(next);
  return next;
}

export function removeFromWatchlist(id) {
  const next = readWatchlist().filter((x) => x !== id);
  writeWatchlist(next);
  return next;
}

export function toggleWatchlist(id) {
  return readWatchlist().includes(id) ? removeFromWatchlist(id) : addToWatchlist(id);
}
```

- [ ] **Step 2: `frontend/src/hooks/useWatchlist.js`**

```js
"use client";
import { useEffect, useState, useCallback } from "react";
import { readWatchlist, toggleWatchlist, addToWatchlist, removeFromWatchlist } from "../lib/watchlist";

export function useWatchlist() {
  const [ids, setIds] = useState([]);

  useEffect(() => {
    setIds(readWatchlist());
    const onChange = (e) => setIds(e.detail || readWatchlist());
    const onStorage = (e) => { if (e.key === "polyspotter.watchlist.v1") setIds(readWatchlist()); };
    window.addEventListener("polyspotter.watchlist.change", onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("polyspotter.watchlist.change", onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const toggle = useCallback((id) => setIds(toggleWatchlist(id)), []);
  const add    = useCallback((id) => setIds(addToWatchlist(id)), []);
  const remove = useCallback((id) => setIds(removeFromWatchlist(id)), []);
  const has    = useCallback((id) => ids.includes(id), [ids]);

  return { ids, has, toggle, add, remove };
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/lib/watchlist.js frontend/src/hooks/useWatchlist.js
git commit -m "feat(watchlist): localStorage-backed useWatchlist hook"
```

---

### Task 16: Frontend signal labels + adapter + API fetchers

**Files:**
- Create: `frontend/src/lib/signalLabels.js`
- Create: `frontend/src/lib/signalAdapter.js`
- Modify: [frontend/src/lib/api.js](../../../frontend/src/lib/api.js)

- [ ] **Step 1: `signalLabels.js`**

```js
export const SIGNAL_LABELS = {
  win_rate:                { label: "Sharp wallet",    tone: "accent" },
  timing_close:            { label: "Timing edge",     tone: "warn" },
  price_impact:            { label: "Moved price",     tone: "violet" },
  wallet_cluster:          { label: "Linked wallets",  tone: "info" },
  concentrated_one_sided:  { label: "One-sided",       tone: "violet" },
  volume_spike:            { label: "Volume spike",    tone: "warn" },
  new_wallet:              { label: "New wallet",      tone: "info" },
  low_activity:            { label: "Quiet market",    tone: "default" },
  correlated_cross_market: { label: "Cross-market",    tone: "violet" },
};
```

- [ ] **Step 2: `signalAdapter.js`**

```js
// Tiny helpers — heavy derivation is server-side (see backend/signals.py).
export const usdK = (n) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return `$${Math.round(n)}`;
};
export const cents = (p) => p == null ? "—" : `${Math.round(p * 100)}¢`;
export const pct   = (p, sign = true) => `${sign && p >= 0 ? "+" : ""}${(p * 100).toFixed(Math.abs(p) >= 0.1 ? 0 : 1)}%`;

export function relTime(iso) {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
```

- [ ] **Step 3: Extend `frontend/src/lib/api.js`**

Append to `frontend/src/lib/api.js`:

```js
export function fetchSignals({ topic, limit = 20, offset = 0, minRating, resolvesWithin } = {}) {
  return request("/api/signals", {
    topic: topic || undefined,
    limit,
    offset,
    min_rating: minRating || undefined,
    resolves_within: resolvesWithin || undefined,
  });
}

export function fetchTopSignals() {
  return request("/api/signals/top");
}

export function fetchMovers(limit = 6) {
  return request("/api/markets/movers", { limit });
}

export function fetchTopics() {
  return request("/api/topics");
}

export function fetchDigest(since) {
  return request("/api/digest", { since });
}

export function fetchTickerRecent(limit = 20) {
  return request("/api/ticker/recent", { limit });
}
```

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/lib/signalLabels.js frontend/src/lib/signalAdapter.js frontend/src/lib/api.js
git commit -m "feat(frontend): SIGNAL_LABELS + usd/pct/relTime helpers + new API fetchers"
```

---

## Phase 5 — Frontend: Shell + routing

### Task 17: `TopNav` (desktop)

**Files:**
- Create: `frontend/src/components/TopNav.jsx`

- [ ] **Step 1: Implement**

Reference: [design_handoff_polyspotter/src/header.jsx](../../../design_handoff_polyspotter/src/header.jsx) for visual detail.

```jsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CommandPalette } from "./CommandPalette";  // existing
import ThemeToggle from "./ThemeToggle";            // existing

const LINKS = [
  { href: "/", label: "Live" },
  { href: "/signals", label: "Signals" },
  { href: "/discover", label: "Discover" },
  { href: "/watchlist", label: "Watchlist" },
];

export default function TopNav({ tags = [], topWallets = [] }) {
  const pathname = usePathname();
  return (
    <header
      className="hidden md:flex items-center justify-between gap-4 px-6 py-4 border-b"
      style={{ borderColor: "var(--border-subtle)", background: "var(--surface-0)" }}
    >
      <Link href="/" className="flex items-center gap-2">
        <span
          className="grid place-items-center"
          style={{
            width: 28, height: 28, borderRadius: 8,
            background: "linear-gradient(135deg, var(--accent), var(--accent-hover))",
            boxShadow: "0 0 14px var(--accent-subtle)",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M4 17L9 12L13 16L20 7" stroke="#05080f" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 700, letterSpacing: -0.3, color: "var(--text-primary)" }}>
          polyspotter
        </span>
      </Link>

      <nav className="flex items-center gap-1">
        {LINKS.map((l) => {
          const active = pathname === l.href;
          return (
            <Link
              key={l.href}
              href={l.href}
              className="px-3 py-2 rounded-lg text-sm font-semibold"
              style={{
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
                background: active ? "var(--surface-2)" : "transparent",
              }}
            >
              {l.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex items-center gap-2">
        <CommandPalette tags={tags} topWallets={topWallets} />
        <ThemeToggle />
      </div>
    </header>
  );
}
```

**Note:** the existing `CommandPalette` is a default export currently — if this file uses `{ CommandPalette }` import and fails, switch to default import.

- [ ] **Step 2: Lint**

```bash
cd frontend && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TopNav.jsx
git commit -m "feat(shell): TopNav with logo + primary nav + command palette"
```

---

### Task 18: `MobileTabBar` + `AppShell`

**Files:**
- Create: `frontend/src/components/MobileTabBar.jsx`
- Create: `frontend/src/components/AppShell.jsx`

- [ ] **Step 1: `MobileTabBar.jsx`**

```jsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/",          label: "Home",      d: "M3 12l9-9 9 9M5 10v10a2 2 0 002 2h3v-6h4v6h3a2 2 0 002-2V10" },
  { href: "/signals",   label: "Signals",   d: "M2 12h4l3-8 4 16 3-8h4" },
  { href: "/discover",  label: "Discover",  d: "M12 3a9 9 0 100 18 9 9 0 000-18zM16 8l-2 6-6 2 2-6 6-2z" },
  { href: "/watchlist", label: "Watchlist", d: "M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" },
];

export default function MobileTabBar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="md:hidden fixed inset-x-0 bottom-0 z-30 flex justify-around pt-2 pb-safe"
      style={{
        background: "rgba(5,8,15,0.82)",
        backdropFilter: "blur(20px) saturate(180%)",
        WebkitBackdropFilter: "blur(20px) saturate(180%)",
        borderTop: "1px solid var(--border)",
      }}
    >
      {TABS.map((t) => {
        const active = pathname === t.href;
        const color = active ? "var(--accent)" : "var(--text-muted)";
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-label={t.label}
            aria-current={active ? "page" : undefined}
            className="flex flex-col items-center gap-1 px-3 py-1.5"
            style={{ color }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d={t.d} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: 0.1 }}>{t.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 2: `AppShell.jsx`**

```jsx
import TopNav from "./TopNav";
import MobileTabBar from "./MobileTabBar";

export default function AppShell({ tags = [], topWallets = [], children }) {
  return (
    <div className="min-h-screen">
      <TopNav tags={tags} topWallets={topWallets} />
      <main className="mx-auto max-w-[1440px] pb-32 md:pb-12">
        {children}
      </main>
      <MobileTabBar />
    </div>
  );
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/MobileTabBar.jsx frontend/src/components/AppShell.jsx
git commit -m "feat(shell): MobileTabBar + AppShell wrapping responsive nav"
```

---

## Phase 6 — Home sections

### Task 19: `DigestBanner` + `useDigest` hook

**Files:**
- Create: `frontend/src/hooks/useDigest.js`
- Create: `frontend/src/components/DigestBanner.jsx`

- [ ] **Step 1: `useDigest.js`**

```js
"use client";
import { useEffect, useState } from "react";
import { fetchDigest } from "../lib/api";

const KEY = "polyspotter.lastVisit.v1";

export function useDigest() {
  const [digest, setDigest] = useState(null);
  const [since, setSince] = useState(null);

  useEffect(() => {
    let last;
    try { last = window.localStorage.getItem(KEY); } catch { last = null; }
    if (!last) last = new Date(Date.now() - 24*60*60*1000).toISOString();
    setSince(last);
    fetchDigest(last).then(setDigest).catch(() => setDigest(null));

    // Bump on unload so next visit compares against this moment
    const bump = () => { try { window.localStorage.setItem(KEY, new Date().toISOString()); } catch {} };
    window.addEventListener("pagehide", bump);
    return () => window.removeEventListener("pagehide", bump);
  }, []);

  return { digest, since };
}
```

- [ ] **Step 2: `DigestBanner.jsx`**

```jsx
"use client";
import { useDigest } from "../hooks/useDigest";

export default function DigestBanner() {
  const { digest } = useDigest();
  if (!digest || !digest.new_signals) return null;
  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
      style={{
        background: "linear-gradient(90deg, var(--accent-subtle), rgba(0,194,106,0.03))",
        border: "1px solid rgba(0,194,106,0.2)",
      }}
    >
      <span className="relative inline-block w-2 h-2">
        <span className="absolute inset-0 rounded-full opacity-75 animate-pulse-live" style={{ background: "var(--accent)" }} />
        <span className="absolute inset-0 rounded-full" style={{ background: "var(--accent)" }} />
      </span>
      <span className="text-sm flex-1" style={{ color: "var(--text-primary)" }}>
        <b>{digest.new_signals} new signals</b>
        <span style={{ color: "var(--text-secondary)" }}> since your last visit</span>
      </span>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    </div>
  );
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/hooks/useDigest.js frontend/src/components/DigestBanner.jsx
git commit -m "feat(home): DigestBanner with useDigest hook"
```

---

### Task 20: `Top3Card` + `Top3Hero`

**Files:**
- Create: `frontend/src/components/Top3Card.jsx`
- Create: `frontend/src/components/Top3Hero.jsx`

Reference: [design_handoff_polyspotter/src/top3.jsx](../../../design_handoff_polyspotter/src/top3.jsx) for the exact visual layout.

- [ ] **Step 1: `Top3Card.jsx`**

```jsx
"use client";
import Link from "next/link";
import Chip from "./ui/Chip";
import StrengthBars from "./ui/StrengthBars";
import CountdownText from "./ui/CountdownText";
import BookmarkButton from "./ui/BookmarkButton";
import CopyButton from "./ui/CopyButton";
import { useWatchlist } from "../hooks/useWatchlist";
import { SIGNAL_LABELS } from "../lib/signalLabels";
import { usdK, cents } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function Top3Card({ signal, rank }) {
  const { has, toggle } = useWatchlist();
  const saved = has(signal.market.condition_id);
  const moves = signal.price_now != null && signal.price_at_alert != null
    ? Math.round((signal.price_now - signal.price_at_alert) * 100)
    : null;
  const slug = signal.market.condition_id ? marketSlug(signal.market.title, signal.market.condition_id) : null;
  const copyHref = signal.market.condition_id ? `https://polymarket.com/event/${signal.market.condition_id}` : null;

  return (
    <div
      className="relative rounded-2xl p-4"
      style={{
        background: "linear-gradient(180deg, var(--surface-card), var(--surface-1))",
        border: `1px solid ${rank === 1 ? "rgba(0,194,106,0.3)" : "var(--border-strong)"}`,
        boxShadow: rank === 1 ? "var(--shadow-glow)" : "var(--shadow-card)",
      }}
    >
      {/* Rank badge */}
      <div
        className="absolute top-3 right-3"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11, fontWeight: 700, letterSpacing: 1,
          color: rank === 1 ? "var(--accent)" : "var(--text-muted)",
        }}
      >#{rank}</div>

      {/* Topic + countdown */}
      <div className="flex items-center gap-1.5 mb-2.5">
        <span className="text-sm">{signal.market.icon}</span>
        <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-secondary)" }}>
          {signal.market.topic}
        </span>
        <span style={{ color: "var(--text-muted)", fontSize: 10 }}>·</span>
        <CountdownText endDate={signal.market.end_date} className="text-[10px] font-semibold" />
      </div>

      {/* Market title */}
      <Link
        href={slug ? `/market/${slug}` : "#"}
        className="block mb-2.5 font-semibold leading-snug line-clamp-2"
        style={{ fontSize: 14, color: "var(--text-primary)" }}
      >
        {signal.market.title}
      </Link>

      {/* Why panel (compressed — 3-line clamp, non-expandable on Top3) */}
      <div
        className="px-2.5 py-2 mb-2.5 rounded-lg text-xs leading-snug line-clamp-3"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--border)",
          color: "var(--text-secondary)",
        }}
      >
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>Why: </span>
        {signal.why}
      </div>

      {/* Signals + rating */}
      <div className="flex items-center gap-1 flex-wrap mb-2.5">
        {signal.signals.slice(0, 2).map((k) => {
          const def = SIGNAL_LABELS[k];
          if (!def) return null;
          return <Chip key={k} tone={def.tone}>{def.label}</Chip>;
        })}
        <StrengthBars rating={signal.rating} />
      </div>

      {/* Stats row */}
      <div
        className="grid grid-cols-3 gap-2 py-2 mb-2.5"
        style={{ borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}
      >
        <Stat label="Entry" value={cents(signal.entry_price)} />
        <Stat label="Now"   value={cents(signal.price_now)} delta={moves} />
        <Stat label="Stake" value={usdK(signal.stake_usd)} />
      </div>

      {/* CTAs */}
      <div className="flex gap-2">
        <CopyButton
          full
          side={signal.side || "YES"}
          returnPct={signal.return_pct}
          onClick={(e) => { e.preventDefault(); if (copyHref) window.open(copyHref, "_blank", "noopener"); }}
        />
        <BookmarkButton active={saved} onClick={() => toggle(signal.market.condition_id)} />
      </div>
    </div>
  );
}

function Stat({ label, value, delta }) {
  return (
    <div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
        {value}
        {typeof delta === "number" && (
          <span style={{ fontSize: 10, marginLeft: 4, fontWeight: 600, color: delta >= 0 ? "var(--accent)" : "var(--bearish)" }}>
            {delta >= 0 ? "+" : ""}{delta}¢
          </span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: `Top3Hero.jsx`**

```jsx
"use client";
import Top3Card from "./Top3Card";

export default function Top3Hero({ signals = [] }) {
  if (!signals.length) return null;
  return (
    <section className="px-4 md:px-6 mt-4">
      <div className="flex items-end justify-between mb-3">
        <div>
          <h2 className="text-lg md:text-2xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Today's top 3
          </h2>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Curated by your network's sharpest wallets
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2" style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
          <span
            className="inline-block w-1.5 h-1.5 rounded-full animate-pulse-live"
            style={{ background: "var(--accent)", boxShadow: "0 0 4px var(--accent)" }}
          />
          LIVE
        </div>
      </div>

      {/* Mobile: snap carousel. Desktop: 3-col grid. */}
      <div className="flex md:grid md:grid-cols-3 gap-3 overflow-x-auto md:overflow-visible snap-x snap-mandatory no-scrollbar -mx-4 md:mx-0 px-4 md:px-0 pb-2">
        {signals.slice(0, 3).map((s, i) => (
          <div key={s.id} className="flex-shrink-0 w-[290px] md:w-auto snap-start">
            <Top3Card signal={s} rank={i + 1} />
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/Top3Card.jsx frontend/src/components/Top3Hero.jsx
git commit -m "feat(home): Top3Hero + Top3Card (snap carousel mobile, grid desktop)"
```

---

### Task 21: `MoverCard` + `MoversStrip`

**Files:**
- Create: `frontend/src/components/MoverCard.jsx`
- Create: `frontend/src/components/MoversStrip.jsx`

Reference: [design_handoff_polyspotter/src/movers.jsx](../../../design_handoff_polyspotter/src/movers.jsx).

- [ ] **Step 1: `MoverCard.jsx`**

```jsx
import Link from "next/link";
import Sparkline from "./Sparkline";  // existing component
import { cents } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function MoverCard({ mover, pulseDelay = 0 }) {
  const up = (mover.price_change_24h || 0) >= 0;
  const color = up ? "var(--accent)" : "var(--bearish)";
  const slug = mover.condition_id ? marketSlug(mover.title, mover.condition_id) : null;

  return (
    <Link
      href={slug ? `/market/${slug}` : "#"}
      className="block flex-shrink-0 w-[150px] md:w-[180px] rounded-xl p-2.5"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-xs">{mover.icon}</span>
        <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
          {mover.topic}
        </span>
      </div>
      <div
        className="text-[11px] leading-snug font-medium line-clamp-2 mb-2 min-h-[28px]"
        style={{ color: "var(--text-primary)" }}
      >
        {mover.title}
      </div>
      <div className="flex items-end justify-between gap-1">
        <div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 700 }}>
            {cents(mover.yes_price)}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600, color }}>
            {up ? "↑" : "↓"} {Math.abs(Math.round((mover.price_change_24h || 0) * 100))}¢
          </div>
        </div>
        <div className="animate-mover-pulse" style={{ animationDelay: `${pulseDelay}s` }}>
          <Sparkline data={mover.candles} width={50} height={22} color={color} />
        </div>
      </div>
    </Link>
  );
}
```

**Note:** verify `frontend/src/components/Sparkline.jsx` accepts `data/width/height/color` props. If not, adjust.

- [ ] **Step 2: `MoversStrip.jsx`**

```jsx
export default function MoversStrip({ movers = [] }) {
  if (!movers.length) return null;
  return (
    <section className="mt-6 px-4 md:px-6">
      <div className="flex items-end justify-between mb-3">
        <h3 className="text-base md:text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          Live movers
        </h3>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>See all →</span>
      </div>
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 md:mx-0 md:px-0 pb-2">
        {movers.map((m, i) => (
          <MoverCard key={m.condition_id} mover={m} pulseDelay={i * 1.2} />
        ))}
      </div>
    </section>
  );
}
```

(Keep the `import MoverCard` at top of this file.)

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/MoverCard.jsx frontend/src/components/MoversStrip.jsx
git commit -m "feat(home): MoversStrip + MoverCard with staggered pulse animation"
```

---

### Task 22: `TopicTile` + `TopicTiles` + `TopicFilterChips`

**Files:**
- Create: `frontend/src/components/TopicTile.jsx`
- Create: `frontend/src/components/TopicTiles.jsx`
- Create: `frontend/src/components/TopicFilterChips.jsx`

Reference: [design_handoff_polyspotter/src/topics.jsx](../../../design_handoff_polyspotter/src/topics.jsx).

- [ ] **Step 1: `TopicTile.jsx`**

```jsx
import Sparkline from "./Sparkline";
import { usdK } from "../lib/signalAdapter";

export default function TopicTile({ topic, onClick }) {
  const up = (topic.trend || 0) >= 0;
  const color = up ? "var(--accent)" : "var(--bearish)";
  return (
    <button
      onClick={() => onClick?.(topic.name)}
      className="text-left rounded-xl p-3 md:p-4"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between mb-2.5">
        <div className="grid place-items-center" style={{ width: 32, height: 32, borderRadius: 9, background: "rgba(255,255,255,0.04)", fontSize: 16 }}>
          {topic.icon}
        </div>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 700, color }}>
          {up ? "+" : ""}{topic.trend}%
        </span>
      </div>
      <div className="font-bold text-sm md:text-base mb-1" style={{ color: "var(--text-primary)" }}>
        {topic.name}
      </div>
      <div className="text-xs mb-2.5" style={{ color: "var(--text-muted)" }}>
        {topic.signals} signals · {usdK(topic.volume_24h)}
      </div>
      <Sparkline data={topic.spark} width={120} height={26} color={color} />
    </button>
  );
}
```

- [ ] **Step 2: `TopicTiles.jsx`**

```jsx
import TopicTile from "./TopicTile";

export default function TopicTiles({ topics = [], onSelect, columns = "grid-cols-2 md:grid-cols-3 xl:grid-cols-6" }) {
  if (!topics.length) return null;
  return (
    <section className="mt-6 px-4 md:px-6">
      <div className={`grid ${columns} gap-2.5 md:gap-3`}>
        {topics.map((t) => <TopicTile key={t.name} topic={t} onClick={onSelect} />)}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: `TopicFilterChips.jsx`**

```jsx
"use client";
export default function TopicFilterChips({ topics = [], active = "All", onChange }) {
  const all = [{ name: "All", signals: topics.reduce((s, t) => s + (t.signals || 0), 0) }, ...topics];
  return (
    <div className="px-4 md:px-6 mt-4">
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 md:mx-0 md:px-0">
        {all.map((t) => {
          const on = active === t.name;
          return (
            <button
              key={t.name}
              onClick={() => onChange?.(t.name)}
              className="flex-shrink-0 inline-flex items-center gap-1 px-3 py-1.5 rounded-full whitespace-nowrap text-xs font-semibold"
              style={{
                background: on ? "var(--text-primary)" : "rgba(255,255,255,0.05)",
                color:      on ? "var(--surface-0)"    : "var(--text-secondary)",
                border:     `1px solid ${on ? "var(--text-primary)" : "var(--border)"}`,
                letterSpacing: -0.1,
              }}
            >
              {t.icon && <span>{t.icon}</span>}
              {t.name}
              {typeof t.signals === "number" && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600, color: on ? "rgba(5,8,15,0.55)" : "var(--text-muted)" }}>
                  {t.signals}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/TopicTile.jsx frontend/src/components/TopicTiles.jsx frontend/src/components/TopicFilterChips.jsx
git commit -m "feat(home): TopicTiles + TopicFilterChips"
```

---

### Task 23: `SignalCard` (the feed card)

**Files:**
- Create: `frontend/src/components/SignalCard.jsx`

Reference: [design_handoff_polyspotter/src/feed.jsx](../../../design_handoff_polyspotter/src/feed.jsx).

- [ ] **Step 1: Implement**

```jsx
"use client";
import Link from "next/link";
import { useState } from "react";
import Chip from "./ui/Chip";
import StrengthBars from "./ui/StrengthBars";
import CountdownText from "./ui/CountdownText";
import WalletAvatar from "./ui/WalletAvatar";
import BookmarkButton from "./ui/BookmarkButton";
import CopyButton from "./ui/CopyButton";
import { useWatchlist } from "../hooks/useWatchlist";
import { SIGNAL_LABELS } from "../lib/signalLabels";
import { usdK, cents, relTime } from "../lib/signalAdapter";
import { marketSlug } from "../lib/slugify";

export default function SignalCard({ signal }) {
  const [expanded, setExpanded] = useState(false);
  const { has, toggle } = useWatchlist();
  const saved = has(signal.market.condition_id);
  const moves = signal.price_now != null && signal.price_at_alert != null
    ? Math.round((signal.price_now - signal.price_at_alert) * 100)
    : null;
  const slug = signal.market.condition_id ? marketSlug(signal.market.title, signal.market.condition_id) : null;
  const copyHref = signal.market.condition_id ? `https://polymarket.com/event/${signal.market.condition_id}` : null;
  const panelId = `why-${signal.id}`;

  return (
    <article
      className="rounded-2xl p-3 md:p-4 mb-3"
      style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
    >
      {/* Header row: wallet + time + strength */}
      <div className="flex items-center gap-2 mb-2.5">
        <WalletAvatar wallet={signal.wallet} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Link
              href={`/wallet/${signal.wallet.addr}`}
              style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, letterSpacing: 0.3, color: "var(--text-primary)" }}
            >
              {signal.wallet.alias}
            </Link>
            {signal.wallet.tier === "legend" && <span className="text-[10px]">★</span>}
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600, color: "var(--accent)" }}>
              {Math.round(signal.wallet.win_rate * 100)}%
            </span>
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
            {signal.wallet.bets} bets · {relTime(signal.created_at)}
          </div>
        </div>
        <StrengthBars rating={signal.rating} />
      </div>

      {/* Market title */}
      <Link
        href={slug ? `/market/${slug}` : "#"}
        className="block mb-2 text-sm md:text-[15px] font-semibold leading-snug"
        style={{ color: "var(--text-primary)" }}
      >
        <span className="mr-1.5">{signal.market.icon}</span>
        {signal.market.title}
      </Link>

      {/* Why panel (expandable) */}
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="block w-full text-left px-2.5 py-2 mb-2.5 rounded-lg text-xs leading-snug"
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--border)",
          color: "var(--text-secondary)",
          transition: "max-height 200ms ease-out",
        }}
      >
        <span style={{ color: "var(--accent)", fontWeight: 600 }}>Why: </span>
        {signal.why}
        {expanded && signal.bullets?.length > 0 && (
          <ul id={panelId} className="mt-2 pl-4 text-[10.5px] leading-relaxed list-disc" style={{ color: "var(--text-secondary)" }}>
            {signal.bullets.filter(Boolean).map((b, i) => <li key={i} className="mb-0.5">{b}</li>)}
          </ul>
        )}
      </button>

      {/* Signal chips */}
      <div className="flex flex-wrap gap-1 mb-2.5">
        {(signal.signals || []).map((k) => {
          const def = SIGNAL_LABELS[k];
          if (!def) return null;
          return <Chip key={k} tone={def.tone}>{def.label}</Chip>;
        })}
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 pt-2.5" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="flex-1 flex gap-4">
          <Stat
            label={signal.side || "SIDE"}
            value={cents(signal.price_now)}
            delta={moves}
          />
          <Stat label="Stake" value={usdK(signal.stake_usd)} />
          <div>
            <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
              Ends
            </div>
            <CountdownText endDate={signal.market.end_date} className="text-[13px] font-bold" />
          </div>
        </div>
        <BookmarkButton active={saved} size={36} onClick={() => toggle(signal.market.condition_id)} />
        <CopyButton
          size="sm"
          side={signal.side || "YES"}
          returnPct={signal.return_pct}
          onClick={() => copyHref && window.open(copyHref, "_blank", "noopener")}
        />
      </div>
    </article>
  );
}

function Stat({ label, value, delta }) {
  return (
    <div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, color: "var(--text-muted)" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
        {value}
        {typeof delta === "number" && (
          <span style={{ fontSize: 10, marginLeft: 4, fontWeight: 600, color: delta >= 0 ? "var(--accent)" : "var(--bearish)" }}>
            {delta >= 0 ? "+" : ""}{delta}¢
          </span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/SignalCard.jsx
git commit -m "feat(home): SignalCard with expand-on-click Why panel"
```

---

### Task 24: `SignalFeed` + `useSignalFeed` hook

**Files:**
- Create: `frontend/src/hooks/useSignalFeed.js`
- Create: `frontend/src/components/SignalFeed.jsx`

- [ ] **Step 1: `useSignalFeed.js`**

```js
"use client";
import { useCallback, useEffect, useState } from "react";
import { fetchSignals } from "../lib/api";

export function useSignalFeed({ topic = "All", minRating, resolvesWithin, limit = 20 } = {}) {
  const [signals, setSignals] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);

  const load = useCallback((reset = false) => {
    setLoading(true);
    fetchSignals({
      topic: topic === "All" ? undefined : topic,
      limit,
      offset: reset ? 0 : offset,
      minRating,
      resolvesWithin,
    })
      .then((d) => {
        setSignals(reset ? d.signals : [...signals, ...d.signals]);
        setTotal(d.total);
        if (reset) setOffset(d.signals.length); else setOffset(offset + d.signals.length);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [topic, limit, minRating, resolvesWithin, offset, signals]);

  useEffect(() => { load(true); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [topic, minRating, resolvesWithin]);

  return { signals, total, loading, loadMore: () => load(false) };
}
```

- [ ] **Step 2: `SignalFeed.jsx`**

```jsx
"use client";
import { useState } from "react";
import SignalCard from "./SignalCard";
import { useSignalFeed } from "../hooks/useSignalFeed";

const RATING_TABS = [
  { key: "all",            label: "All",           minRating: 1 },
  { key: "strong",         label: "Strong+",       minRating: 4 },
  { key: "resolving-soon", label: "Resolving soon",minRating: 1, resolvesWithin: "24h" },
];

export default function SignalFeed({ topic = "All", showTabs = true }) {
  const [tab, setTab] = useState(RATING_TABS[0]);
  const { signals, total, loading, loadMore } = useSignalFeed({
    topic,
    minRating: tab.minRating,
    resolvesWithin: tab.resolvesWithin,
  });

  return (
    <section className="px-4 md:px-6 mt-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base md:text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          All signals
        </h3>
        {showTabs && (
          <div className="flex items-center gap-1 p-0.5 rounded-lg" style={{ background: "var(--surface-2)" }}>
            {RATING_TABS.map((t) => {
              const on = tab.key === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => setTab(t)}
                  className="px-3 py-1.5 rounded-md text-xs font-semibold"
                  style={{
                    background: on ? "var(--surface-card)" : "transparent",
                    color: on ? "var(--text-primary)" : "var(--text-secondary)",
                  }}
                >
                  {t.label}{on && ` (${total})`}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {signals.map((s) => <SignalCard key={s.id} signal={s} />)}

      {!loading && signals.length === 0 && (
        <div className="text-center py-10" style={{ color: "var(--text-muted)" }}>
          No signals{topic !== "All" ? ` in ${topic}` : ""} yet.
        </div>
      )}

      {signals.length < total && (
        <button onClick={loadMore} disabled={loading} className="block mx-auto mt-4 px-4 py-2 rounded-lg text-sm" style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/hooks/useSignalFeed.js frontend/src/components/SignalFeed.jsx
git commit -m "feat(home): SignalFeed with All/Strong+/Resolving-soon tabs"
```

---

## Phase 7 — Right rail (desktop)

### Task 25: `DigestBlock` + `SharpestWallets`

**Files:**
- Create: `frontend/src/components/rail/DigestBlock.jsx`
- Create: `frontend/src/components/rail/SharpestWallets.jsx`

Reference: [design_handoff_polyspotter/src/rail.jsx](../../../design_handoff_polyspotter/src/rail.jsx).

- [ ] **Step 1: `DigestBlock.jsx`**

```jsx
"use client";
import { useDigest } from "../../hooks/useDigest";

export default function DigestBlock() {
  const { digest } = useDigest();
  if (!digest) return null;
  return (
    <div
      className="rounded-xl p-4 mb-3"
      style={{
        background: "linear-gradient(135deg, rgba(0,194,106,0.08), rgba(0,194,106,0.02))",
        border: "1px solid rgba(0,194,106,0.2)",
      }}
    >
      <div className="text-xs mb-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
        Since your last visit
      </div>
      <div className="text-xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>
        {digest.new_signals} new signals
      </div>
      <div className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
        {digest.strong_signals} rated <b style={{ color: "var(--accent)" }}>Strong+</b>.
      </div>
      <ul className="text-xs space-y-1.5 mb-3">
        {(digest.top_signals || []).slice(0, 3).map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2">
            <span className="truncate" style={{ color: "var(--text-secondary)" }}>• {s.market.title}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent)" }}>
              ▲ {s.market.price_change_24h >= 0 ? "+" : ""}{Math.round((s.market.price_change_24h || 0) * 100)}¢
            </span>
          </li>
        ))}
      </ul>
      <button className="w-full py-2 rounded-lg text-xs font-semibold" style={{ background: "var(--surface-2)", color: "var(--text-primary)" }}>
        View digest →
      </button>
    </div>
  );
}
```

- [ ] **Step 2: `SharpestWallets.jsx`**

```jsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Sparkline from "../Sparkline";
import { usdK } from "../../lib/signalAdapter";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function SharpestWallets() {
  const [wallets, setWallets] = useState([]);
  useEffect(() => {
    fetch(`${API}/api/wallets/top?limit=5`).then((r) => r.json()).then((d) => setWallets(d.wallets || d || [])).catch(() => {});
  }, []);
  if (!wallets.length) return null;
  return (
    <div className="rounded-xl p-4 mb-3" style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Sharpest this week
        </div>
        <Link href="/wallets" className="text-xs" style={{ color: "var(--text-muted)" }}>All →</Link>
      </div>
      <ul>
        {wallets.slice(0, 5).map((w, i) => (
          <li key={w.wallet} className="flex items-center gap-2 py-1.5">
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>#{i+1}</span>
            <div style={{ width: 24, height: 24, borderRadius: "50%", background: "linear-gradient(135deg, #8b5cf6, #3b82f6)", color: "#fff", fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 10, display: "grid", placeItems: "center" }}>
              {(w.alias || w.wallet).slice(0, 1).toUpperCase()}
            </div>
            <Link href={`/wallet/${w.wallet}`} className="text-sm font-semibold flex-1" style={{ color: "var(--text-primary)" }}>
              {w.alias || w.wallet.slice(0, 6)}
            </Link>
            <div className="text-right">
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: "var(--accent)" }}>
                {w.win_rate != null ? `${Math.round(w.win_rate * 100)}%` : "—"}
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {w.total_pnl != null ? `+${usdK(w.total_pnl)}` : ""}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/rail/DigestBlock.jsx frontend/src/components/rail/SharpestWallets.jsx
git commit -m "feat(rail): DigestBlock + SharpestWallets"
```

---

### Task 26: `WatchlistBlock` + `LiveTicker` + `useLiveTicker`

**Files:**
- Create: `frontend/src/components/rail/WatchlistBlock.jsx`
- Create: `frontend/src/components/rail/LiveTicker.jsx`
- Create: `frontend/src/hooks/useLiveTicker.js`

- [ ] **Step 1: `useLiveTicker.js`**

```js
"use client";
import { useEffect, useRef, useState } from "react";
import { fetchTickerRecent } from "../lib/api";

export function useLiveTicker({ interval = 5000, limit = 20 } = {}) {
  const [trades, setTrades] = useState([]);
  const seen = useRef(new Set());

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const d = await fetchTickerRecent(limit);
        if (!alive) return;
        const incoming = d.trades || [];
        const next = [];
        for (const t of incoming) {
          if (!seen.current.has(t.id)) {
            seen.current.add(t.id);
            next.push(t);
          }
        }
        if (next.length) setTrades((curr) => [...next, ...curr].slice(0, limit));
      } catch {}
    }
    tick();
    const id = setInterval(tick, interval);
    return () => { alive = false; clearInterval(id); };
  }, [interval, limit]);

  return trades;
}
```

- [ ] **Step 2: `LiveTicker.jsx`**

```jsx
"use client";
import { useLiveTicker } from "../../hooks/useLiveTicker";
import { usdK } from "../../lib/signalAdapter";

export default function LiveTicker() {
  const trades = useLiveTicker({ interval: 5000, limit: 20 });
  return (
    <div className="rounded-xl p-4" style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Live ticker
        </div>
        <span className="inline-flex items-center gap-1.5 text-[10px]" style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>
          <span className="w-1.5 h-1.5 rounded-full animate-pulse-live" style={{ background: "var(--accent)", boxShadow: "0 0 4px var(--accent)" }} />
          LIVE
        </span>
      </div>
      <ul aria-live="polite" className="space-y-2 max-h-[360px] overflow-y-auto no-scrollbar">
        {trades.map((t) => (
          <li key={t.id} className="flex items-center gap-2 text-xs animate-fade-up">
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-bold"
              style={{
                background: t.side === "BUY" ? "rgba(0,194,106,0.12)" : "rgba(239,68,68,0.12)",
                color: t.side === "BUY" ? "var(--accent)" : "var(--bearish)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {t.side}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--text-primary)" }}>
              {usdK(t.amount)}
            </span>
            <span className="flex-1 truncate" style={{ color: "var(--text-secondary)" }}>{t.market}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: t.wallet_color }}>
              {t.wallet_alias}
            </span>
          </li>
        ))}
        {trades.length === 0 && (
          <li className="text-center text-[11px] py-4" style={{ color: "var(--text-muted)" }}>Waiting for trades…</li>
        )}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: `WatchlistBlock.jsx`**

```jsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useWatchlist } from "../../hooks/useWatchlist";
import { fetchMarketLive } from "../../lib/api";
import Sparkline from "../Sparkline";
import { cents } from "../../lib/signalAdapter";
import { marketSlug } from "../../lib/slugify";

export default function WatchlistBlock({ full = false }) {
  const { ids, remove } = useWatchlist();
  const [markets, setMarkets] = useState({});

  useEffect(() => {
    ids.forEach((cid) => {
      if (markets[cid]) return;
      fetchMarketLive(cid).then((m) => setMarkets((s) => ({ ...s, [cid]: m }))).catch(() => {});
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  if (!ids.length) {
    return (
      <div className={`rounded-xl p-4 ${full ? "" : "mb-3"}`} style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
        <div className="text-xs font-bold mb-2" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Watchlist
        </div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          Tap the bookmark icon on any card to watch a market.
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-xl p-4 ${full ? "" : "mb-3"}`} style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-bold" style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Watchlist
        </div>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{ids.length}</span>
      </div>
      <ul className="space-y-3">
        {ids.map((cid) => {
          const m = markets[cid];
          if (!m) return <li key={cid} className="text-xs" style={{ color: "var(--text-muted)" }}>Loading…</li>;
          const up = (m.price_change_24h || 0) >= 0;
          const color = up ? "var(--accent)" : "var(--bearish)";
          const slug = marketSlug(m.market_title, cid);
          return (
            <li key={cid} className="flex items-center gap-2">
              <Link href={`/market/${slug}`} className="flex-1 min-w-0">
                <div className="text-xs font-semibold line-clamp-1" style={{ color: "var(--text-primary)" }}>{m.market_title}</div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
                  {cents(m.yes_price)}
                  <span style={{ color, marginLeft: 4, fontSize: 10 }}>
                    {up ? "▲" : "▼"} {Math.abs(Math.round((m.price_change_24h || 0) * 100))}¢
                  </span>
                </div>
              </Link>
              <Sparkline data={m.candles || []} width={50} height={20} color={color} />
              <button
                onClick={() => remove(cid)}
                aria-label="Remove from watchlist"
                className="text-xs px-2 py-1"
                style={{ color: "var(--text-muted)" }}
              >✕</button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/rail/WatchlistBlock.jsx frontend/src/components/rail/LiveTicker.jsx frontend/src/hooks/useLiveTicker.js
git commit -m "feat(rail): WatchlistBlock + LiveTicker (5s poll)"
```

---

### Task 27: `RightRail` composition

**Files:**
- Create: `frontend/src/components/RightRail.jsx`

- [ ] **Step 1: Implement**

```jsx
import DigestBlock from "./rail/DigestBlock";
import SharpestWallets from "./rail/SharpestWallets";
import WatchlistBlock from "./rail/WatchlistBlock";
import LiveTicker from "./rail/LiveTicker";

export default function RightRail() {
  return (
    <aside className="hidden md:block w-[320px] sticky top-4 space-y-3 self-start">
      <DigestBlock />
      <SharpestWallets />
      <WatchlistBlock />
      <LiveTicker />
    </aside>
  );
}
```

- [ ] **Step 2: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/RightRail.jsx
git commit -m "feat(rail): RightRail composition"
```

---

## Phase 8 — Wire up routes

### Task 28: Rewrite `home-client.jsx`

**Files:**
- Rewrite: [frontend/src/app/home-client.jsx](../../../frontend/src/app/home-client.jsx)
- Modify: [frontend/src/app/page.jsx](../../../frontend/src/app/page.jsx) (extend `getHomeData` to fetch top signals + topics + movers; pass to HomeClient)

- [ ] **Step 1: Extend `getHomeData` in `page.jsx`**

Replace the body of `getHomeData()` with:

```js
async function getHomeData() {
  try {
    const [topRes, moversRes, topicsRes, walletsRes, tagsRes] = await Promise.all([
      fetch(`${API_URL}/api/signals/top`,      { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/markets/movers?limit=6`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/topics`,           { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/tags`,             { next: { revalidate: 60 } }),
    ]);
    return {
      topSignals: (await topRes.json())?.signals || [],
      movers:     (await moversRes.json())?.movers || [],
      topics:     (await topicsRes.json())?.topics || [],
      topWallets: (await walletsRes.json())?.wallets || [],
      tags:       (await tagsRes.json())?.tags || (await tagsRes.json()) || [],
    };
  } catch {
    return { topSignals: [], movers: [], topics: [], topWallets: [], tags: [] };
  }
}
```

And adjust `HomePage()` to pass the new data to `<HomeClient />`. Keep the SEO `<script type="application/ld+json">` blocks and the `.seo-content` article as-is. Do NOT change metadata, JSON-LD, or SEO content — that's out of scope and actively valuable.

```jsx
<HomeClient
  topSignals={topSignals}
  movers={movers}
  topics={topics}
  topWallets={topWallets}
  tags={tags}
/>
```

- [ ] **Step 2: Rewrite `home-client.jsx` (complete replacement)**

```jsx
"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AppShell from "../components/AppShell";
import DigestBanner from "../components/DigestBanner";
import Top3Hero from "../components/Top3Hero";
import MoversStrip from "../components/MoversStrip";
import TopicTiles from "../components/TopicTiles";
import TopicFilterChips from "../components/TopicFilterChips";
import SignalFeed from "../components/SignalFeed";
import RightRail from "../components/RightRail";

function HomeInner({ topSignals, movers, topics, topWallets, tags }) {
  const search = useSearchParams();
  const [topic, setTopic] = useState(search.get("topic") || "All");

  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="grid md:grid-cols-[minmax(0,1fr)_320px] gap-6 px-0 md:px-6 pt-2">
        <div>
          <div className="px-4 md:px-0">
            <DigestBanner />
          </div>
          <Top3Hero signals={topSignals} />
          <MoversStrip movers={movers} />
          {/* Topic tiles: desktop-only grid; mobile uses chips below */}
          <div className="hidden md:block">
            <TopicTiles topics={topics} onSelect={setTopic} />
          </div>
          <TopicFilterChips topics={topics} active={topic} onChange={setTopic} />
          <SignalFeed topic={topic} />
        </div>
        <RightRail />
      </div>
    </AppShell>
  );
}

export default function HomeClient(props) {
  // useSearchParams requires Suspense boundary in Next 15
  return (
    <Suspense fallback={null}>
      <HomeInner {...props} />
    </Suspense>
  );
}
```

- [ ] **Step 3: Start dev server**

```bash
cd frontend && npm run dev
```
Visit http://localhost:3000 at both 1440px and 390px widths.

- [ ] **Step 4: Verify visually**

Compare against [screenshots/desktop-home.png](../../../design_handoff_polyspotter/screenshots/desktop-home.png) and [screenshots/desktop-feed.png](../../../design_handoff_polyspotter/screenshots/desktop-feed.png). Check:
- [ ] Logo + TopNav render
- [ ] DigestBanner appears with accent dot (if API is running)
- [ ] Top3Hero renders 3 cards, #1 has accent glow
- [ ] MoversStrip renders horizontally scrollable cards with sparklines
- [ ] TopicTiles grid renders on desktop (hidden on mobile)
- [ ] TopicFilterChips scrollable row with count badges
- [ ] SignalFeed renders at least one SignalCard
- [ ] RightRail visible on desktop with Digest/Sharpest/Watchlist/LiveTicker blocks

- [ ] **Step 5: Lint**

```bash
cd frontend && npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/home-client.jsx frontend/src/app/page.jsx
git commit -m "feat(home): rewrite Home route with new PolySpotter surface

Wires Top3Hero + MoversStrip + TopicTiles + TopicFilterChips +
SignalFeed + RightRail via the new /api/signals/top + /movers +
/topics endpoints. Preserves existing SEO JSON-LD + .seo-content
article for crawlers."
```

---

### Task 29: `/signals` route

**Files:**
- Create: `frontend/src/app/signals/page.jsx`
- Create: `frontend/src/app/signals/signals-client.jsx`

- [ ] **Step 1: `signals/page.jsx`**

```jsx
import SignalsClient from "./signals-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const revalidate = 60;

export const metadata = {
  title: "Signals — live feed",
  description: "The live stream of notable Polymarket trades flagged by smart-money signals.",
};

async function getData() {
  try {
    const [tagsRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);
    return {
      tags: (await tagsRes.json())?.tags || (await tagsRes.json()) || [],
      topWallets: (await walletsRes.json())?.wallets || [],
    };
  } catch { return { tags: [], topWallets: [] }; }
}

export default async function SignalsPage() {
  const { tags, topWallets } = await getData();
  return <SignalsClient tags={tags} topWallets={topWallets} />;
}
```

- [ ] **Step 2: `signals-client.jsx`**

```jsx
"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AppShell from "../../components/AppShell";
import SignalFeed from "../../components/SignalFeed";

function Inner({ tags, topWallets }) {
  const s = useSearchParams();
  const topic = s.get("topic") || "All";
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Signals</h1>
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Live stream of notable trades</div>
      </div>
      <SignalFeed topic={topic} />
    </AppShell>
  );
}

export default function SignalsClient(props) {
  return <Suspense fallback={null}><Inner {...props} /></Suspense>;
}
```

- [ ] **Step 3: Visit http://localhost:3000/signals at mobile + desktop widths**

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/app/signals/
git commit -m "feat(route): /signals — full feed"
```

---

### Task 30: `/discover` route

**Files:**
- Create: `frontend/src/app/discover/page.jsx`
- Create: `frontend/src/app/discover/discover-client.jsx`

- [ ] **Step 1: `discover/page.jsx`**

```jsx
import DiscoverClient from "./discover-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const revalidate = 60;

export const metadata = {
  title: "Discover — signal activity by topic",
  description: "Browse signal activity by topic across Politics, Crypto, NBA, Geopolitics, and more.",
};

async function getData() {
  try {
    const [topicsRes, tagsRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/topics`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);
    return {
      topics: (await topicsRes.json())?.topics || [],
      tags: (await tagsRes.json())?.tags || (await tagsRes.json()) || [],
      topWallets: (await walletsRes.json())?.wallets || [],
    };
  } catch { return { topics: [], tags: [], topWallets: [] }; }
}

export default async function DiscoverPage() {
  const { topics, tags, topWallets } = await getData();
  return <DiscoverClient topics={topics} tags={tags} topWallets={topWallets} />;
}
```

- [ ] **Step 2: `discover-client.jsx`**

```jsx
"use client";
import { useRouter } from "next/navigation";
import AppShell from "../../components/AppShell";
import TopicTiles from "../../components/TopicTiles";

export default function DiscoverClient({ topics, tags, topWallets }) {
  const router = useRouter();
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Discover</h1>
        <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          Signal activity by topic · last 24h
        </div>
      </div>
      <TopicTiles topics={topics} onSelect={(name) => router.push(`/signals?topic=${encodeURIComponent(name)}`)} />
    </AppShell>
  );
}
```

- [ ] **Step 3: Verify at /discover**

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/app/discover/
git commit -m "feat(route): /discover — topic grid"
```

---

### Task 31: `/watchlist` route

**Files:**
- Create: `frontend/src/app/watchlist/page.jsx`
- Create: `frontend/src/app/watchlist/watchlist-client.jsx`

- [ ] **Step 1: `watchlist/page.jsx`**

```jsx
import WatchlistClient from "./watchlist-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const metadata = {
  title: "Watchlist — your saved markets",
  description: "Markets you've saved on PolySpotter.",
};

async function getData() {
  try {
    const [tagsRes, walletsRes] = await Promise.all([
      fetch(`${API_URL}/api/tags`, { next: { revalidate: 60 } }),
      fetch(`${API_URL}/api/wallets/top?limit=10`, { next: { revalidate: 60 } }),
    ]);
    return {
      tags: (await tagsRes.json())?.tags || (await tagsRes.json()) || [],
      topWallets: (await walletsRes.json())?.wallets || [],
    };
  } catch { return { tags: [], topWallets: [] }; }
}

export default async function WatchlistPage() {
  const { tags, topWallets } = await getData();
  return <WatchlistClient tags={tags} topWallets={topWallets} />;
}
```

- [ ] **Step 2: `watchlist-client.jsx`**

```jsx
"use client";
import AppShell from "../../components/AppShell";
import WatchlistBlock from "../../components/rail/WatchlistBlock";

export default function WatchlistClient({ tags, topWallets }) {
  return (
    <AppShell tags={tags} topWallets={topWallets}>
      <div className="px-4 md:px-6 pt-6">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>Watchlist</h1>
        <div className="text-xs mt-1 mb-4" style={{ color: "var(--text-muted)" }}>
          Your saved markets (stored locally on this device)
        </div>
        <div className="max-w-xl">
          <WatchlistBlock full />
        </div>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 3: Verify at /watchlist**

- [ ] **Step 4: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/app/watchlist/
git commit -m "feat(route): /watchlist — localStorage-backed saved markets"
```

---

## Phase 9 — Polish + verification

### Task 32: Accessibility pass + mark orphaned components

**Files:**
- Modify: `frontend/src/components/AlertTable.jsx`, `AlertList.jsx`, `AlertRow.jsx`, `Filters.jsx`, `Pagination.jsx`, `ResolvingSoonStrip.jsx`, `HeroSpotlight.jsx`, `TopicNav.jsx`, `Ticker.jsx`, `MarketPulse.jsx`

- [ ] **Step 1: Add TODO comment to each orphan file**

For each file listed above, add at the very top (before the first import):

```jsx
// TODO(cleanup): unused after polyspotter redesign 2026-04-17.
// Kept in-tree temporarily — verify via grep across /app + /components,
// then delete in a follow-up PR. See spec §3.6.
```

You can do all ten with a script:

```bash
cd frontend/src/components
for f in AlertTable.jsx AlertList.jsx AlertRow.jsx Filters.jsx Pagination.jsx ResolvingSoonStrip.jsx HeroSpotlight.jsx TopicNav.jsx Ticker.jsx MarketPulse.jsx; do
  head -n 1 "$f" | grep -q "TODO(cleanup)" || \
    { printf '%s\n%s\n' "// TODO(cleanup): unused after polyspotter redesign 2026-04-17." "$(cat "$f")" > "$f.tmp" && mv "$f.tmp" "$f"; }
done
```

- [ ] **Step 2: Verify each orphan is NOT imported by any live code**

```bash
cd frontend
for f in AlertTable AlertList AlertRow Filters Pagination ResolvingSoonStrip HeroSpotlight TopicNav Ticker MarketPulse; do
  echo "=== $f ==="
  grep -rn "from.*components/${f}\|components/${f}'" src/ | grep -v "components/${f}.jsx"
done
```

If any orphan IS imported, either:
- Remove the `TODO(cleanup)` comment (it's still used), OR
- Replace the import with the new equivalent.

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/
git commit -m "chore: mark orphaned components for follow-up cleanup"
```

---

### Task 33: Manual verification pass + screenshot capture

**Files:**
- None (verification only)

- [ ] **Step 1: Start both servers**

In two terminals:
```bash
# Terminal 1 — backend
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign && source venv/bin/activate && cd backend && uvicorn app:app --reload --port 8000

# Terminal 2 — frontend
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/frontend && npm run dev
```

- [ ] **Step 2: Verify desktop at 1440px width**

Using browser devtools (responsive mode, 1440×900), visit:
- [ ] `/` — matches [screenshots/desktop-home.png](../../../design_handoff_polyspotter/screenshots/desktop-home.png) and `desktop-feed.png`. Header, Top 3 with #1 glow, movers, topic tiles, feed, right rail all visible.
- [ ] `/signals` — full feed, no hero, no right rail.
- [ ] `/discover` — topic tiles grid.
- [ ] `/watchlist` — empty state if no saved.

- [ ] **Step 3: Verify mobile at 390px width**

In devtools (iPhone 14 preset or 390×844), visit:
- [ ] `/` — matches mobile phone #1 in [screenshots/mobile-overview.png](../../../design_handoff_polyspotter/screenshots/mobile-overview.png). Tab bar at bottom.
- [ ] `/signals` — matches phone #2.
- [ ] `/discover` — matches phone #3.
- [ ] Tab bar navigates correctly; scroll resets on forward tap, preserved on back.
- [ ] Top3 cards snap at 290px widths.

- [ ] **Step 4: Verify interactions**

- [ ] Tap a topic chip → feed refetches (network panel shows `?topic=...`).
- [ ] Tap "Why" panel → expands smoothly, bullets visible.
- [ ] Tap bookmark icon → icon fills, `/watchlist` shows the saved market.
- [ ] Tap Copy trade → opens Polymarket in new tab.
- [ ] Countdown under 1h renders red.
- [ ] DigestBanner shows a count after a refresh-past-lastVisit.
- [ ] LiveTicker shows rows fading in as new trades arrive (at 5s intervals).

- [ ] **Step 5: Capture screenshots**

```bash
# Save to design_handoff_polyspotter/screenshots/shipped/
mkdir -p /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/design_handoff_polyspotter/screenshots/shipped
```

Use browser's full-page screenshot at both viewports and place alongside the design screenshots.

- [ ] **Step 6: Run full test suite one more time**

```bash
cd /Users/bhavya/git/polybot/.worktrees/polyspotter-redesign/backend && source ../venv/bin/activate && pytest -q
cd ../frontend && npm run lint
```
Expected: all pass (DB-requiring tests may skip if no DATABASE_URL).

- [ ] **Step 7: Finalize**

If all the above pass, the redesign is ready for PR. Invoke the `superpowers:finishing-a-development-branch` skill (or just open the PR) to capture before/after screenshots and draft the description.

---

## Spec self-review & plan self-review results

**Spec coverage (spec → task):**
- §3.1 Routing → Tasks 28–31
- §3.2 Component tree → Tasks 13–27
- §3.3 New files → all phases
- §3.4 Modified files → Tasks 1, 16, 28
- §3.6 Orphaned components → Task 32
- §4.1 Signal shape → Task 3 (models) + Task 5 (adapter)
- §4.2 Mover/Topic/Ticker/Digest shapes → Tasks 3 + 9–12
- §4.3 Derivations → Tasks 4–5
- §4.4 Query params → Tasks 7–12
- §5 State & interactions → Tasks 15, 19, 23, 24, 26
- §6 Tokens → Task 1
- §7 A11y → implemented in each component task; final check in Task 32
- §8 Testing → Tasks 3–12 (backend TDD) + Task 33 (manual verification)
- §9 Risks → covered in adapter edge-case tests + fallback logic
- §10 Rollout → Task 33

**Placeholder scan:** clean (no TBD/TODO beyond the intentional orphan markers, no "similar to", no "write tests for the above").

**Type/name consistency:** `SignalView`/`SignalMarket`/`SignalWallet` defined in Task 3 and used verbatim through Tasks 5–12; `signal_from_row` signature matches between Tasks 5 and 7; frontend `fetchSignals`/`fetchMovers`/`fetchTopics`/`fetchDigest`/`fetchTickerRecent` defined in Task 16 and used in Tasks 19, 20, 21, 24, 26.

**Scope:** this is a large plan (33 tasks). Consider splitting into two sub-plans if executing with a tight review cadence:
- Sub-plan A: Phases 0–3 (backend + tokens + lib) — 16 tasks, can ship as a backend-only PR.
- Sub-plan B: Phases 4–9 (frontend components + routes + polish) — 17 tasks, depends on A.

But since the branch is single-PR anyway (spec §10), keeping one plan is reasonable.
