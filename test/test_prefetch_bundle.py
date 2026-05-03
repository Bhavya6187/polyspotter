"""Tests for storybot.prefetch_bundle.

Covers the predictable queries it should kick off so the orchestrator's
research loop doesn't have to re-issue them via `query`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


# A canonical scope: 1 condition_id, 1 event_slug, 1 alert_id, 1 wallet.
_SCOPE = {
    "event_slug": "ky-04-republican-primary-winner",
    "condition_ids": ["0xe3033b163d0e0e30cb3154049f28295dada348030e5c6cdfe58ed0d4e393c7e9"],
    "alert_ids": [134076],
    "wallets": ["0x000d257d2dc7616feaef4ae0f14600fdf50a758e"],
}


def _stub_backends():
    """Return a {backend_name: callable} dict that records calls and returns
    deterministic data, so prefetch_bundle's two phases can be inspected
    without hitting a real DB or network."""
    calls: list[tuple] = []
    yes_token = "84474900710899633954422645443302070527051"

    def postgres(sql):
        calls.append(("postgres", sql))
        # Match on what the caller wants — the SQL fragments are stable.
        if "FROM alert_trades" in sql or "alert_trades t" in sql:
            return [{
                "alert_id": 134076,
                "wallet": "0x000d257d2dc7616feaef4ae0f14600fdf50a758e",
                "usd_value": 7000.0,
            }]
        if "tweeted_alerts" in sql:
            return []
        if "FROM alerts a" in sql and "INTERVAL '7 days'" in sql:
            return [{"id": 1, "wallet": "0xabc"}]
        if "FROM wallet_theses" in sql:
            return [{"wallet": "0xabc", "event_slug": _SCOPE["event_slug"]}]
        if "wallet_profiles" in sql:
            return [{"wallet": "0xabc", "wins": 10}]
        return []

    def sqlite(sql):
        calls.append(("sqlite", sql))
        if "wallet_funders" in sql:
            return [{"wallet": "0xabc", "funder": "0xdef"}]
        if "wallet_event_history" in sql:
            return [{"wallet": "0xabc", "usd_value": 100.0}]
        return []

    def gamma(path, params=None):
        calls.append(("gamma", path, params))
        if path == "/markets":
            # clobTokenIds is stored as a JSON string by Polymarket
            return [{
                "conditionId": _SCOPE["condition_ids"][0],
                "clobTokenIds": f'["{yes_token}", "no_token"]',
                "outcomePrices": '["0.78", "0.22"]',
            }]
        if path == "/events":
            return [{"slug": _SCOPE["event_slug"], "title": "KY-04"}]
        return []

    def clob(path, params=None):
        calls.append(("clob", path, params))
        if path == "/prices-history":
            return {"history": [{"t": 1, "p": 0.76}, {"t": 2, "p": 0.78}]}
        if path == "/book":
            return {"bids": [{"price": "0.77", "size": "100"}],
                    "asks": [{"price": "0.79", "size": "100"}]}
        return {}

    return {
        "postgres": postgres,
        "sqlite": sqlite,
        "gamma": gamma,
        "clob": clob,
        "data_api": lambda path, params=None: [],
    }, calls, yes_token


def _run_prefetch():
    import storybot
    backends, calls, yes_token = _stub_backends()
    with patch.dict(storybot._BACKENDS, backends, clear=True):
        results = storybot.prefetch_bundle(_SCOPE)
    return results, calls, yes_token


def test_prefetch_includes_recent_event_alerts_and_theses():
    """Phase-1 should issue Postgres queries against alerts (7d window) and
    wallet_theses for the picked event_slug — these are the cheapest wins
    over the agent re-issuing them via query()."""
    results, calls, _ = _run_prefetch()

    assert "recent_event_alerts_7d" in results
    assert results["recent_event_alerts_7d"]["ok"]
    assert "wallet_theses" in results
    assert results["wallet_theses"]["ok"]

    pg_sqls = [c[1] for c in calls if c[0] == "postgres"]
    assert any("INTERVAL '7 days'" in s and "FROM alerts a" in s for s in pg_sqls)
    assert any("FROM wallet_theses" in s for s in pg_sqls)


def test_prefetch_kicks_off_clob_calls_after_market_meta_resolves():
    """Phase-2 CLOB tasks (prices_history_24h, order_book) should use the
    Yes-side token id parsed out of market_meta.clobTokenIds — not a value
    derived from the scope alone."""
    results, calls, yes_token = _run_prefetch()

    assert "prices_history_24h" in results
    assert results["prices_history_24h"]["ok"]
    assert "order_book" in results
    assert results["order_book"]["ok"]

    clob_calls = [c for c in calls if c[0] == "clob"]
    paths = [c[1] for c in clob_calls]
    assert "/prices-history" in paths
    assert "/book" in paths

    # Both CLOB calls must target the Yes token from clobTokenIds[0].
    for _, path, params in clob_calls:
        if path == "/prices-history":
            assert params and params.get("market") == yes_token
        elif path == "/book":
            assert params and params.get("token_id") == yes_token


def test_prefetch_skips_clob_when_market_meta_missing_token_ids():
    """If Gamma returns no clobTokenIds we must NOT submit CLOB tasks —
    they'd 400 anyway, and we don't want to cache empty errors."""
    import storybot

    def postgres(sql): return []
    def sqlite(sql): return []
    def gamma(path, params=None):
        if path == "/markets":
            return [{"conditionId": _SCOPE["condition_ids"][0]}]   # no clobTokenIds
        return []
    clob_called = []
    def clob(path, params=None):
        clob_called.append(path)
        return {}

    backends = {"postgres": postgres, "sqlite": sqlite, "gamma": gamma,
                "clob": clob, "data_api": lambda *a, **k: []}
    with patch.dict(storybot._BACKENDS, backends, clear=True):
        results = storybot.prefetch_bundle(_SCOPE)

    assert "prices_history_24h" not in results
    assert "order_book" not in results
    assert clob_called == []


def test_prefetch_returns_empty_for_empty_scope():
    import storybot
    assert storybot.prefetch_bundle({}) == {}


def test_yes_token_extractor_handles_string_and_list():
    """Polymarket sometimes serializes clobTokenIds as a JSON string and
    sometimes as a real list; both must produce the Yes token."""
    import storybot
    as_string = [{"clobTokenIds": '["yes_tid", "no_tid"]'}]
    as_list = [{"clobTokenIds": ["yes_tid", "no_tid"]}]
    assert storybot._yes_token_ids_from_market_meta(as_string) == ["yes_tid"]
    assert storybot._yes_token_ids_from_market_meta(as_list) == ["yes_tid"]
    assert storybot._yes_token_ids_from_market_meta([{"clobTokenIds": None}]) == []
    assert storybot._yes_token_ids_from_market_meta(None) == []


def test_slim_market_keeps_truncated_description():
    """The writer needs the resolution rules in `description` to ground claims
    about how the market resolves; without it the agent re-fetches /markets
    just to read this field. We cap to _MARKET_DESCRIPTION_CAP to keep
    prompt tokens bounded."""
    import storybot
    short = "Resolves YES if Massie wins the GOP nomination for KY-04."
    out = storybot._slim_market({"id": "1", "description": short})
    assert out["description"] == short

    long_desc = "x" * (storybot._MARKET_DESCRIPTION_CAP + 500)
    out = storybot._slim_market({"id": "1", "description": long_desc})
    assert out["description"].endswith("…")
    assert len(out["description"]) <= storybot._MARKET_DESCRIPTION_CAP + 1


def test_bundle_descriptions_for_market_meta_enumerates_fields():
    """The kickoff prompt uses _BUNDLE_DESCRIPTIONS to tell the model what's
    inside each prefetched item. If market_meta's entry doesn't list the
    important fields (description, outcomePrices, clobTokenIds), the model
    re-issues Gamma /markets to check — which is the bug we just fixed.
    """
    import storybot
    desc = storybot._BUNDLE_DESCRIPTIONS["market_meta"]
    for field in ("description", "outcomePrices", "bestBid", "clobTokenIds",
                  "volume24hr", "oneDayPriceChange"):
        assert field in desc, f"market_meta description missing {field!r}"
