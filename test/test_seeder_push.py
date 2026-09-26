"""
Tests for seeder.push_to_backend: failure signalling and ingest auth header.

* A failed POST used to return 0, indistinguishable from "nothing to push",
  so the scanner advanced its cursor and the alerts were lost for good.
* POST /api/ingest was unauthenticated. The seeder now sends the shared
  secret from POLYBOT_INGEST_TOKEN when it is configured.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests

import seeder
from detection_strategies import Signal


def _signal():
    return Signal(strategy="win_rate_tracking", severity=3.0, headline="h",
                  trade={"transactionHash": "0xtx"}, condition_id="0xcond")


class _PushHarness:
    """Patch every collaborator so only the HTTP call is real (mocked)."""

    def __init__(self, post):
        self.patches = [
            patch("seeder.build_alerts_payload",
                  return_value={"alerts": [{"condition_id": "0xcond", "dedup_key": "d"}],
                                "wallet_profiles": []}),
            patch("llm_filter.filter_alerts", side_effect=lambda alerts: alerts),
            patch("db.get_recent_price_candles", return_value=[]),
            patch("seeder.build_theses_payload", return_value=[]),
            patch("seeder.requests.post", post),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self.patches):
            p.stop()
        return False


def _ok_response():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"inserted_alerts": 1, "updated_alerts": 0, "skipped_alerts": 0}
    return resp


class PushToBackendTests(unittest.TestCase):
    def test_success_returns_alert_count(self):
        post = MagicMock(return_value=_ok_response())
        with _PushHarness(post):
            self.assertEqual(seeder.push_to_backend([_signal()], [{}]), 1)

    def test_no_signals_returns_zero_without_posting(self):
        post = MagicMock()
        with _PushHarness(post):
            self.assertEqual(seeder.push_to_backend([], [{}]), 0)
        post.assert_not_called()

    def test_http_failure_returns_none(self):
        post = MagicMock(side_effect=requests.ConnectionError("backend down"))
        with _PushHarness(post):
            self.assertIsNone(seeder.push_to_backend([_signal()], [{}]))

    def test_http_error_status_returns_none(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        post = MagicMock(return_value=resp)
        with _PushHarness(post):
            self.assertIsNone(seeder.push_to_backend([_signal()], [{}]))


class IngestTokenHeaderTests(unittest.TestCase):
    def test_token_sent_when_configured(self):
        post = MagicMock(return_value=_ok_response())
        with patch.dict("os.environ", {"POLYBOT_INGEST_TOKEN": "s3cret"}), _PushHarness(post):
            seeder.push_to_backend([_signal()], [{}])
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["X-Ingest-Token"], "s3cret")

    def test_no_token_header_when_unconfigured(self):
        post = MagicMock(return_value=_ok_response())
        with patch.dict("os.environ", {}, clear=False), _PushHarness(post):
            import os
            os.environ.pop("POLYBOT_INGEST_TOKEN", None)
            seeder.push_to_backend([_signal()], [{}])
        _, kwargs = post.call_args
        self.assertNotIn("X-Ingest-Token", kwargs.get("headers") or {})


if __name__ == "__main__":
    unittest.main()
