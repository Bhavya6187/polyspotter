# LLM Prompt Quality Improvement — Design Spec

**Date:** 2026-04-03
**Goal:** Reduce false positives (routine whales surfaced as interesting) and eliminate formulaic/generic LLM output (headlines, bullets) by enriching prompt data and overhauling the system prompt.

## Problem Statement

The LLM filter (`llm_filter.py`) evaluates ~11.7k alerts with a 56.4% acceptance rate. Two quality issues:

1. **False positives on "impressive but routine" alerts** — clusters where the only interesting wallet would already be caught individually by `win_rate_tracking`, mixed-quality clusters surfaced because of raw size/USD, routine whale activity on liquid markets.

2. **Generic, formulaic output** — headlines follow the same "[X%] win-rate [sport] sharp" template. Bullets follow a rigid 3-part structure (win rate → market breadth → trade detail). The phrase "repeatable edge" appears in nearly every output. No alert feels distinctive.

## Approach

Single-pass architecture stays. Two levers:
1. **Enrich the data** passed to the LLM so it can make better-informed decisions
2. **Overhaul the system prompt** with anti-patterns, few-shot examples, and better framing

No changes to: response schema, model (gpt-5.4), backend, frontend, thesis headline generation.

---

## Section 1: Data Enrichment

### 1a. Wallet Flag History

**Source:** `flagged_wallets` table (931 wallets, up to 116 flags each)

Add to the "Wallet profiles" section of the prompt:
```
- 0xabb899...c9bba3: 54% win rate (...), flagged 42 times ($890k total), first seen 2026-01-15
```

**Why:** A wallet flagged 100+ times with millions in bets is a known whale — less interesting than a first-time flag with a strong record. The LLM currently can't distinguish these.

**Implementation:** Query `flagged_wallets` by wallet address in `_build_prompt()`. The table already exists; add a `get_wallet_flag_summary(wallet)` helper in `db.py` if one doesn't exist.

### 1b. Category-Specific Win Rates

**Source:** `tracked_bets` joined with market category metadata

Instead of a single blended win rate, break it down:
```
- 0xabb899...c9bba3: 73% overall (454 resolved) — NBA 87% (120), Soccer 61% (89), Crypto 52% (45)
```

**Why:** An 87% NBA bettor on an NBA market is much more interesting than the same wallet betting crypto at 52%. The LLM currently only sees the blended number.

**Implementation:** New `get_wallet_category_win_rates(wallet)` function in `db.py`.

`tracked_bets` has `condition_id` but no category column. Category is resolved via `gamma_cache.get_market_category(condition_id)` which calls the Gamma API. For a wallet with hundreds of bets, calling this for every condition_id would be expensive.

Approach: query all distinct `condition_id` values from `tracked_bets` for the wallet (with resolved status), then resolve category only for those already present in the in-memory gamma cache (`_market_cache`), skipping the rest. Most recent/active markets will be in cache from the current scan. Returns `{category: {wins, losses, closed, win_rate}}` for top 5 categories by closed positions. Uncategorized bets are grouped under "Other".

If the gamma cache hit rate is too low in practice (<50% of a wallet's bets), fall back to deriving category from `event_slug` patterns in `wallet_event_history` (e.g., slugs containing "nba", "nfl", "premier-league" map to known categories via simple keyword matching).

### 1c. Same-Scan Market Context

**Source:** Other alerts in the current `filter_alerts()` batch

New prompt section when multiple alerts share a `condition_id`:
```
Other alerts on this market (this scan):
  - 85% win-rate wallet buying Flyers, $3,621 (score 8.0)
  - 90% win-rate wallet buying Islanders, $5,000 (score 8.0)
```

**Why:** Two sharp bettors on opposite sides of the same market is fascinating context the LLM currently misses because it evaluates each alert in isolation. Similarly, multiple independent sharps converging strengthens the signal.

**Implementation:** In `filter_alerts()`, pre-group alerts by `condition_id`. Pass the list of peer summaries (market title, wallet win rate, side, USD, score) into `_build_prompt()` as a new parameter. Exclude the current alert from its own peer list.

### 1d. Volume Trend

**Source:** Gamma API (fields `volume1wk`, `volume1mo` already returned but not used)

Add to market context:
```
Volume: total $1.4M, 24h $1,287, 1wk $9,202, 1mo $63,113
```

**Why:** 24h volume of $1,287 is meaningless without trend. If 1wk is $9k, it's normal. If 1wk is $200k, today is unusually quiet. The LLM needs this to assess volume-based signals.

**Implementation:** Read `volume1wk` and `volume1mo` from the Gamma market dict in `_build_prompt()`. Two extra lines of code.

---

## Section 2: System Prompt Overhaul

### 2a. Anti-Pattern Rules

Add after the existing "Bullet style rules" section:

```
## Anti-patterns — DO NOT do these

- Don't use the phrase "repeatable edge" or "suggesting a repeatable edge"
- Don't start every first bullet with "This bettor wins X% of..."
- Don't use the same 3-bullet template for every alert (win rate → breadth → trade)
- Don't describe signal mechanics — users don't know what "concentrated_one_sided" means
- Don't repeat the market name in the headline
- Vary headline structure — "[X%] win-rate [sport] sharp" cannot be the default
- Don't say "suggesting informed momentum" or similar hedging — be direct
```

### 2b. "What Makes This One Different?" Framing

Add to the "How to evaluate" section:

```
Before writing your output, ask: "If this user has already seen 50 alerts today 
about sharp bettors with high win rates, what makes THIS one worth stopping on?"

Lead with the surprising or unusual detail — the stat that doesn't fit the pattern, 
the context that changes the interpretation, the timing that's uncanny. If there's 
nothing surprising, it's probably not interesting.
```

### 2c. Few-Shot Examples (Good vs Bad)

Add 4 example pairs covering the main alert types. Each pair shows the alert data summary, a BAD output (what the model currently produces), and a GOOD output (what we want).

**Example 1: Individual sharp bettor**

Alert context: 90% win rate, 71 bets, $43.5k profit, buying Islanders at 58¢, avg winning entry 55¢

Bad:
```json
{
  "headline": "90% win-rate sports bettor",
  "bullets": [
    "This bettor wins 90% of their resolved trades and is up $43.5k overall.",
    "They have placed 71 bets across 68 events, which points to a repeatable edge.",
    "They bought Islanders at 58¢ from a trader whose average winning entry is 55¢."
  ]
}
```

Good:
```json
{
  "headline": "90% winner loads up on underdog",
  "bullets": [
    "Bought Islanders at 58¢ — their average winning entry is 55¢, so paying above their usual threshold signals extra conviction.",
    "90% win rate on 71 bets with $43k profit, and most of that edge comes from hockey specifically."
  ]
}
```

**Example 2: Cluster alert (weak — should be discarded)**

Alert context: 6-wallet cluster, $10.5k on Detroit Tigers, only one wallet has a strong record (96% on 76 bets), others are 47-63% with mixed P&L

Bad (what model does now — surfaces it):
```json
{
  "interesting": true,
  "headline": "6-wallet Tigers cluster",
  "bullets": [
    "Six wallets put $10.5k on Detroit Tigers, covering most of this market's daily volume.",
    "One wallet in the group wins 96% of bets with $201k in profit.",
    "The cluster bought between 58-63¢, showing coordinated conviction."
  ]
}
```

Good (should discard):
```json
{
  "interesting": false,
  "summary": "Mixed-quality 6-wallet cluster where the only standout (96% winner) would be flagged individually. The other 5 wallets have mediocre records. Not coordinated conviction."
}
```

**Example 3: Serial timer**

Alert context: Bet placed 1.4 min before resolution, wallet has 74% win rate on 1,024 bets, $16.3M lifetime profit, $51.5k on No at 44¢, 116x volume spike

Bad:
```json
{
  "headline": "Serial timer with $16.3M profit",
  "bullets": [
    "This bettor has won 74% of 1,024 resolved bets and is up $16.3M lifetime.",
    "The trade came 1.4 minutes before resolution with a documented edge.",
    "They put $51.5k on No at 44¢ while volume was 116x normal."
  ]
}
```

Good:
```json
{
  "headline": "$51k No bet 84 seconds before close",
  "bullets": [
    "Dropped $51.5k on No at 44¢ with just 84 seconds left — this wallet has a pattern of last-minute bets and is up $16.3M lifetime on 1,024 trades.",
    "Market volume was running 116x normal when the trade hit, suggesting other informed money was already moving."
  ]
}
```

**Example 4: Same-market conflict**

Alert context: Two alerts on Flyers vs. Islanders — 85% winner buying Flyers, 90% winner buying Islanders

Good (for the Islanders alert):
```json
{
  "headline": "90% winner takes Islanders — sharps split",
  "bullets": [
    "Bought Islanders at 58¢, but an 85% winner is simultaneously buying the other side — two proven bettors disagree on this game.",
    "This wallet's edge is strongest in hockey (92% on 30 NHL bets), which gives their side extra weight."
  ]
}
```

### 2d. Cluster-Specific Filtering Rules

Add to the "NOT interesting" section:

```
- Clusters where only one wallet has a strong track record and that wallet would be 
  flagged individually by win_rate_tracking — the individual alert surfaces the 
  sharp bettor already; the cluster adds noise, not signal.
- A cluster is interesting when the COORDINATION is the signal: linked wallets via 
  shared funder, unusual convergence of multiple independently-strong wallets, or 
  significant capital from wallets that don't usually trade this category.
```

### 2e. Same-Market Conflict/Convergence Rules

Add as a new section after "Position history context":

```
## Same-market context

When "Other alerts on this market" appears, use it:
- If sharp bettors are on opposite sides, mention it — "Another proven winner is 
  taking the other side." This is valuable context for copy-traders, not a reason to 
  discard.
- If multiple independent sharps converge on the same side, that strengthens the 
  signal — call it out.
- Do NOT surface an alert solely because there's a conflict. The alert must be 
  interesting on its own merits; the conflict is additional context.
```

---

## Section 3: Implementation Details

### 3a. Files Changed

| File | Change |
|------|--------|
| `db.py` | Add `get_wallet_flag_summary(wallet)` and `get_wallet_category_win_rates(wallet)` helpers |
| `llm_filter.py` | Enrich `_build_prompt()` with flag history, category win rates, volume trend, same-market peers. Overhaul `SYSTEM_PROMPT`. Add `PROMPT_VERSION` to cache key. Update `filter_alerts()` to pre-group by condition_id and pass peer context. |

### 3b. `get_wallet_flag_summary(wallet)` in db.py

```python
def get_wallet_flag_summary(wallet: str) -> dict | None:
    """Return flag history for a wallet, or None if never flagged."""
    # Query flagged_wallets for: times_flagged, total_usd_flagged, first_flagged_at
```

### 3c. `get_wallet_category_win_rates(wallet)` in db.py

```python
def get_wallet_category_win_rates(wallet: str) -> dict[str, dict]:
    """Return win rates broken down by market category.
    
    Returns {category: {wins, losses, closed, win_rate}} for top 5 categories.
    """
    # 1. Query all distinct (condition_id, won) from tracked_bets WHERE resolved=1
    # 2. For each condition_id, check gamma_cache._market_cache (in-memory only, no API calls)
    # 3. Resolve category via get_market_category() only for cached markets
    # 4. Group wins/losses by category, compute win_rate
    # 5. Return top 5 categories by closed positions; rest grouped as "Other"
```

### 3d. `_build_prompt()` Changes

New parameter: `peer_alerts: list[dict] | None = None`

New sections appended to the prompt:
- Flag history line added to each wallet profile
- Category win rates added to each wallet profile
- `volume1wk` and `volume1mo` added to market context
- "Other alerts on this market" section from `peer_alerts`

### 3e. `filter_alerts()` Changes

Before the evaluation loop:
1. Group alerts by `condition_id` into a dict
2. For each alert, build a peer summary list (excluding itself)
3. Pass peer summaries into `_build_prompt()`

### 3f. Cache Invalidation

Add `PROMPT_VERSION = "v2"` constant. Include it in the cache key computation so all existing cache entries naturally miss and get re-evaluated with the new prompt.

```python
PROMPT_VERSION = "v2"

# In filter_alerts():
cache_key = alert.get("llm_cache_key") or alert.get("dedup_key", "")
if cache_key:
    cache_key = f"{PROMPT_VERSION}:{cache_key}"
```

Old `v1` entries remain in the table but are never matched. Can be cleaned up with a one-time DELETE if desired.

---

## Out of Scope

- Response schema changes (headline, bullets, copy_action structure stays)
- Model change (stays on gpt-5.4)
- Architecture change (stays single-pass)
- Thesis headline generation (seeder.py unchanged)
- Backend/frontend changes
- Two-pass filter/writer split (revisit if cost becomes an issue)
