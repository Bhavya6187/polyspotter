"""
Call parameters of the alert-evaluation GPT call (2026-09-26 cost review).

* reasoning.effort=low: replaying 12 random + 30 borderline alerts on
  gpt-6-luna matched the default-effort verdict 12/12 and 25/30 with 41%
  fewer output tokens (reasoning tokens are billed as output).
* max_output_tokens=4000 instead of 16000: 40 degenerate-whitespace replies
  since July each burned the full 16k budget; the largest real reasoning
  trace seen was 516 tokens on top of ~200 visible.
* evaluate_alert returns the token usage so filter_alerts can persist it —
  successful calls previously left no usage record anywhere (only
  llm_failures.jsonl carried token counts).
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import llm_filter

GOOD_REPLY = json.dumps({
    "interesting": True, "summary": "s", "headline": "h",
    "bullets": ["b"], "copy_action": {"outcome": "Yes"},
})


def _usage(prompt=3252, cached=2730, output=627, reasoning=334):
    u = MagicMock()
    u.input_tokens = prompt
    u.input_tokens_details.cached_tokens = cached
    u.output_tokens = output
    u.output_tokens_details.reasoning_tokens = reasoning
    return u


def _client(output_text=GOOD_REPLY, usage=None):
    resp = MagicMock()
    resp.output_text = output_text
    resp.status = "completed"
    resp.incomplete_details = None
    resp.usage = usage
    client = MagicMock()
    client.responses.create.return_value = resp
    return client


class AlertCallParamsTests(unittest.TestCase):
    def setUp(self):
        self.alert = {"dedup_key": "k1", "condition_id": "0xc"}
        self._patches = [
            patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"),
            patch.object(llm_filter, "_log_prompt"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _call(self, client):
        with patch.object(llm_filter, "OpenAI", return_value=client):
            return llm_filter.evaluate_alert(self.alert, "prompt")

    def test_alert_call_uses_low_reasoning_effort(self):
        client = _client()
        self._call(client)
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs.get("reasoning"), {"effort": "low"})

    def test_alert_call_caps_output_tokens_at_4000(self):
        client = _client()
        self._call(client)
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs.get("max_output_tokens"), 4000)

    def test_evaluate_alert_returns_token_usage(self):
        result = self._call(_client(usage=_usage()))
        self.assertEqual(result["usage"], {
            "prompt_tokens": 3252, "cached_tokens": 2730,
            "completion_tokens": 627, "reasoning_tokens": 334,
        })

    def test_usage_is_zero_when_response_has_none(self):
        result = self._call(_client(usage=None))
        self.assertEqual(result["usage"], {
            "prompt_tokens": 0, "cached_tokens": 0,
            "completion_tokens": 0, "reasoning_tokens": 0,
        })

    def test_inconclusive_reply_still_reports_usage(self):
        with patch.object(llm_filter, "_log_failure"):
            result = self._call(
                _client(output_text="not json", usage=_usage(output=4000, reasoning=200))
            )
        self.assertTrue(result["inconclusive"])
        self.assertEqual(result["usage"]["completion_tokens"], 4000)


class FilterAlertsRecordsUsageTests(unittest.TestCase):
    """filter_alerts persists each LLM call's usage on the main thread
    (evaluate_alert runs in worker threads, and the SQLite connection is
    bound to the thread that opened it)."""

    USAGE = {"prompt_tokens": 3252, "cached_tokens": 2730, "completion_tokens": 627, "reasoning_tokens": 334}

    def _alert(self):
        return {
            "alert_type": "composite", "composite_score": 6.5, "market_title": "T",
            "condition_id": "cond", "tags": ["Sports"], "total_usd": 5000.0,
            "trade_count": 1, "wallet": "0xabc", "dedup_key": "dk-usage",
            "trades": [{"wallet": "0xabc", "usd_value": 5000.0, "price": 0.5, "outcome": "Yes", "side": "BUY"}],
            "signals": [{"strategy": s, "severity": 1.0, "headline": "h"}
                        for s in ("win_rate_tracking", "price_impact")],
        }

    def _run(self, eval_result):
        patches = [
            patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"),
            patch.object(llm_filter, "get_llm_evaluation", return_value=None),
            patch.object(llm_filter, "get_market_eval_count", return_value=0),
            patch.object(llm_filter, "increment_market_eval_count"),
            patch.object(llm_filter, "save_llm_evaluation"),
            patch.object(llm_filter, "_build_prompt", return_value="prompt"),
            patch.object(llm_filter, "evaluate_alert", return_value=eval_result),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with patch.object(llm_filter, "record_llm_usage") as record:
            kept = llm_filter.filter_alerts([self._alert()])
        return kept, record

    def test_usage_recorded_for_a_kept_alert(self):
        kept, record = self._run({
            "interesting": True, "summary": "s", "headline": "h", "bullets": [],
            "copy_action": {}, "usage": self.USAGE,
        })
        self.assertEqual(len(kept), 1)
        record.assert_called_once_with("alert_eval", llm_filter.MODEL, "dk-usage", self.USAGE)

    def test_usage_recorded_for_an_inconclusive_call(self):
        kept, record = self._run({
            "interesting": False, "summary": "", "bullets": [], "copy_action": {},
            "inconclusive": True, "usage": self.USAGE,
        })
        self.assertEqual(kept, [])
        record.assert_called_once_with("alert_eval", llm_filter.MODEL, "dk-usage", self.USAGE)

    def test_result_without_usage_is_tolerated(self):
        kept, record = self._run({
            "interesting": True, "summary": "s", "headline": "h", "bullets": [], "copy_action": {},
        })
        self.assertEqual(len(kept), 1)
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
