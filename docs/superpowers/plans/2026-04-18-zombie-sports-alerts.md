# Zombie Sports Alerts Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop surfacing Top 3 alerts for sports markets whose games have already concluded by making `gamma_cache.get_market_by_condition()` fall back to `closed=true` when the default Gamma lookup returns empty.

**Architecture:** Single-file change in `gamma_cache.py`. The rest of the pipeline (seeder populating `game_start_time`, backend `kickoff + 3h` SQL filter) already exists and starts doing its job once the lookup returns closed markets. No schema changes, no API changes, no frontend changes.

**Tech Stack:** Python 3.13, `requests`, `unittest` + `unittest.mock.patch`, pytest runner.

**Related spec:** [docs/superpowers/specs/2026-04-18-zombie-sports-alerts-design.md](../specs/2026-04-18-zombie-sports-alerts-design.md)

---

## Task 1: Add failing test for closed-market fallback

**Files:**
- Create: `test/test_gamma_cache.py`

- [ ] **Step 1: Write the failing tests**

Full file contents for `test/test_gamma_cache.py`:

```python
import unittest
from unittest.mock import patch, MagicMock

import gamma_cache


class GetMarketByConditionTests(unittest.TestCase):
    def setUp(self):
        # Clear the module-level cache so tests don't leak between each other.
        gamma_cache._market_cache.clear()

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_active_market_returned_on_first_call(self, mock_get):
        market = {"conditionId": "0xabc", "question": "Active market"}
        resp = MagicMock()
        resp.json.return_value = [market]
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        result = gamma_cache.get_market_by_condition("0xabc")

        self.assertEqual(result, market)
        self.assertEqual(mock_get.call_count, 1)
        # First (and only) call should NOT pass closed=true — active-market path.
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"], {"condition_ids": "0xabc"})

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_closed_market_returned_via_fallback(self, mock_get):
        closed_market = {"conditionId": "0xdef", "question": "Closed market", "closed": True}
        active_resp = MagicMock()
        active_resp.json.return_value = []  # default query returns empty
        active_resp.raise_for_status.return_value = None
        closed_resp = MagicMock()
        closed_resp.json.return_value = [closed_market]
        closed_resp.raise_for_status.return_value = None
        mock_get.side_effect = [active_resp, closed_resp]

        result = gamma_cache.get_market_by_condition("0xdef")

        self.assertEqual(result, closed_market)
        self.assertEqual(mock_get.call_count, 2)
        # Second call must carry closed=true.
        second_call_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(
            second_call_kwargs["params"],
            {"condition_ids": "0xdef", "closed": "true"},
        )

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_nonexistent_market_returns_none_after_fallback(self, mock_get):
        empty_resp = MagicMock()
        empty_resp.json.return_value = []
        empty_resp.raise_for_status.return_value = None
        mock_get.side_effect = [empty_resp, empty_resp]

        result = gamma_cache.get_market_by_condition("0xghi")

        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2)

    @patch("gamma_cache.time.sleep", lambda *_a, **_kw: None)
    @patch("gamma_cache.requests.get")
    def test_cached_result_skips_network(self, mock_get):
        market = {"conditionId": "0xjkl"}
        resp = MagicMock()
        resp.json.return_value = [market]
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp

        first = gamma_cache.get_market_by_condition("0xjkl")
        second = gamma_cache.get_market_by_condition("0xjkl")

        self.assertEqual(first, market)
        self.assertEqual(second, market)
        # Cached on first call — second should not hit the network.
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest test/test_gamma_cache.py -v`

Expected: `test_closed_market_returned_via_fallback` FAILS — it asserts two requests are made and the second carries `closed=true`, but current code only makes one request. The other three tests pass (they describe behavior that already works).

## Task 2: Implement closed-market fallback

**Files:**
- Modify: `gamma_cache.py:33-53`

- [ ] **Step 1: Update `get_market_by_condition()`**

Replace lines 33-53 with:

```python
def get_market_by_condition(condition_id: str) -> dict | None:
    """Fetch market metadata from Gamma API by conditionId.

    Gamma's /markets endpoint defaults to active markets only. When a market
    has closed (e.g. a sports game that just ended), the default lookup
    returns empty. Retry once with closed=true so we still get metadata for
    recently closed markets — this is what lets the scanner populate
    game_start_time for concluded sports events and keeps them from
    lingering as 'zombie' alerts in Top 3.

    Results are cached so repeated calls across strategies are free."""
    if condition_id in _market_cache:
        return _market_cache[condition_id]

    for params in (
        {"condition_ids": condition_id},
        {"condition_ids": condition_id, "closed": "true"},
    ):
        time.sleep(MARKET_LOOKUP_DELAY)
        try:
            resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
            if markets:
                _market_cache[condition_id] = markets[0]
                return markets[0]
        except requests.RequestException as e:
            print(f"[WARN] Market lookup failed for condition {condition_id}: {e}", file=sys.stderr)
            return None
    return None
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest test/test_gamma_cache.py -v`

Expected: all four tests PASS.

- [ ] **Step 3: Run the full scanner test suite to confirm no regression**

Run: `source venv/bin/activate && pytest`

Expected: all tests pass. The strategies mock `get_market_by_condition` directly, so they're unaffected.

- [ ] **Step 4: Commit**

```bash
git add gamma_cache.py test/test_gamma_cache.py
git commit -m "$(cat <<'EOF'
Fix Gamma lookup to find closed markets

Retry /markets with closed=true when the default (active-only) query
returns empty. This lets the seeder populate game_start_time for sports
markets that have closed since ingest, which in turn lets the existing
'kickoff + 3h' Top 3 filter drop concluded games instead of letting
them linger until the UMA deadline 7 days out.
EOF
)"
```

## Task 3: Manual verification against production Gamma

**Files:** None.

- [ ] **Step 1: Verify the fallback works against the real Gamma API**

Run this quick ad-hoc check against the two condition_ids that were zombie alerts on 2026-04-18:

```bash
source venv/bin/activate && python3 -c "
from gamma_cache import get_market_by_condition, _market_cache
_market_cache.clear()

# Rublev tennis match — was 'Resolves in 149h' zombie
rublev = get_market_by_condition('0xaf37946bd95986f60b5c0339e8669982062f5da922d9c2dde82411b0077c8dd4')
print('Rublev found:', rublev is not None)
if rublev:
    print('  gameStartTime:', rublev.get('gameStartTime'))
    print('  closed:', rublev.get('closed'))

# Rays MLB — was 'Resolves in 157h' zombie
rays = get_market_by_condition('0x3464ca5b200791ca9c881cc34a51725c975ac214c4cb64a4e58decaf96228af3')
print('Rays found:', rays is not None)
if rays:
    print('  gameStartTime:', rays.get('gameStartTime'))
    print('  closed:', rays.get('closed'))
"
```

Expected output (give or take whitespace):

```
Rublev found: True
  gameStartTime: 2026-04-18 11:40:00+00
  closed: True
Rays found: True
  gameStartTime: 2026-04-18 20:05:00+00
  closed: True
```

If both markets come back with `closed: True` and a real `gameStartTime`, the fix is working end-to-end.

- [ ] **Step 2: Confirm no regression on active markets**

Run a spot-check against one currently-active market to make sure the first-try path still works. Pick any condition_id currently showing in Top 3 that is NOT closed (e.g. the A-League match at rank 3 from the observed screenshot) and confirm it comes back on the first call:

```bash
source venv/bin/activate && python3 -c "
from gamma_cache import get_market_by_condition, _market_cache
_market_cache.clear()
m = get_market_by_condition('0xc44f79769b26857ca64bc2030683c8cf6a648ca2f4757faf0ca9e976a35e3238')
print('Found:', m is not None)
if m:
    print('  closed:', m.get('closed'))
    print('  gameStartTime:', m.get('gameStartTime'))
"
```

Expected: `Found: True`, `closed: False` (or whatever status it has today), with a `gameStartTime` if the match hasn't finished yet.

If this condition_id has since resolved by the time you run this, any active sports market condition_id from `/api/top3` works — the point is confirming the first-attempt path still returns markets correctly.
