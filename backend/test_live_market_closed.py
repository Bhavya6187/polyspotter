"""
_fetch_live_market must retry Gamma with closed=true.

Gamma hides closed markets by default. Every resolved market page (kept as an
evergreen SEO page) therefore got empty outcomes, the price-history endpoint
404'd with "No outcomes found" and holders were labelled by token id.
grade_worker.fetch_market and _fetch_gamma_status already do this retry.
"""

from unittest.mock import MagicMock

import app as app_module


def _resp(payload):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


def test_closed_market_is_found_on_retry(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        if params.get("closed") == "true":
            # outcomes/clobTokenIds length mismatch -> Gamma outcomePrices fallback (no CLOB call)
            return _resp([{"outcomes": '["Yes","No"]', "clobTokenIds": "[]",
                           "outcomePrices": '["1","0"]', "volume24hr": "10", "liquidity": "5"}])
        return _resp([])

    monkeypatch.setattr(app_module._requests, "get", fake_get)

    data = app_module._fetch_live_market("0xresolved")

    assert [o.name for o in data.outcomes] == ["Yes", "No"]
    assert [o.price for o in data.outcomes] == [1.0, 0.0]
    assert calls[0].get("closed") is None
    assert calls[1].get("closed") == "true"


def test_active_market_does_not_trigger_retry(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _resp([{"outcomes": '["Yes","No"]', "clobTokenIds": "[]",
                       "outcomePrices": '["0.6","0.4"]'}])

    monkeypatch.setattr(app_module._requests, "get", fake_get)
    data = app_module._fetch_live_market("0xactive")
    assert len(calls) == 1
    assert [o.price for o in data.outcomes] == [0.6, 0.4]
