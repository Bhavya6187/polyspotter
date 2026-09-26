"""
Robustness tests for llm_filter (2026-09 repo review).

* The parse-failure branch of evaluate_alert referenced an undefined name
  (`finish_reason`), so a malformed GPT reply raised NameError instead of
  being logged to llm_failures.jsonl.
* A JSON reply that is not an object raised AttributeError, which escaped
  the except tuple entirely.
* Inconclusive verdicts (truncated / content-filtered / unparseable) were
  cached as permanent "not interesting" -- 4,252 such rows in polybot.db --
  so a transient failure blocked that cache key forever.
* llm_prompts.jsonl grew without bound (4.3 GB); it now rotates.
* The system prompt still said "9 automated detection strategies".
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import llm_filter


def _fake_response(output_text, status="completed"):
    resp = MagicMock()
    resp.output_text = output_text
    resp.status = status
    resp.incomplete_details = None
    resp.usage = None
    return resp


def _fake_client(output_text):
    client = MagicMock()
    client.responses.create.return_value = _fake_response(output_text)
    return client


class EvaluateAlertFailurePathTests(unittest.TestCase):
    def setUp(self):
        self.alert = {"dedup_key": "k1", "condition_id": "0xc"}
        self._env = patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key")
        self._env.start()
        self._log_prompt = patch.object(llm_filter, "_log_prompt")
        self._log_prompt.start()

    def tearDown(self):
        self._log_prompt.stop()
        self._env.stop()

    def test_unparseable_reply_is_inconclusive_and_logged(self):
        with patch.object(llm_filter, "OpenAI", return_value=_fake_client("not json at all")), \
             patch.object(llm_filter, "_log_failure") as log_failure:
            result = llm_filter.evaluate_alert(self.alert, "prompt")

        self.assertFalse(result["interesting"])
        self.assertTrue(result.get("inconclusive"))
        log_failure.assert_called_once()
        self.assertIn("parse_error", log_failure.call_args.kwargs.get("error", ""))

    def test_non_object_json_is_inconclusive(self):
        with patch.object(llm_filter, "OpenAI", return_value=_fake_client("[1, 2, 3]")), \
             patch.object(llm_filter, "_log_failure"):
            result = llm_filter.evaluate_alert(self.alert, "prompt")

        self.assertFalse(result["interesting"])
        self.assertTrue(result.get("inconclusive"))

    def test_truncated_reply_is_inconclusive(self):
        client = MagicMock()
        client.responses.create.return_value = _fake_response("", status="incomplete")
        with patch.object(llm_filter, "OpenAI", return_value=client), \
             patch.object(llm_filter, "_log_failure"):
            result = llm_filter.evaluate_alert(self.alert, "prompt")

        self.assertTrue(result.get("inconclusive"))

    def test_well_formed_reply_is_not_inconclusive(self):
        payload = json.dumps({"interesting": True, "summary": "s", "headline": "h",
                              "bullets": ["b"], "copy_action": {"outcome": "Yes"}})
        with patch.object(llm_filter, "OpenAI", return_value=_fake_client(payload)):
            result = llm_filter.evaluate_alert(self.alert, "prompt")

        self.assertTrue(result["interesting"])
        self.assertFalse(result.get("inconclusive", False))


class InconclusiveNotCachedTests(unittest.TestCase):
    """filter_alerts must not persist inconclusive verdicts."""

    def _run(self, verdict):
        alert = {"dedup_key": "k", "condition_id": "0xc", "composite_score": 9.0,
                 "total_usd": 5000, "market_title": "m"}
        with patch.object(llm_filter, "AZURE_OPENAI_API_KEY", "test-key"), \
             patch.object(llm_filter, "get_llm_evaluation", return_value=None), \
             patch.object(llm_filter, "_pre_llm_gate", return_value=None), \
             patch.object(llm_filter, "get_market_eval_count", return_value=0), \
             patch.object(llm_filter, "increment_market_eval_count"), \
             patch.object(llm_filter, "_build_prompt", return_value="p"), \
             patch.object(llm_filter, "evaluate_alert", return_value=verdict), \
             patch.object(llm_filter, "save_llm_evaluation") as save:
            kept = llm_filter.filter_alerts([alert])
        return kept, save

    def test_inconclusive_verdict_is_discarded_but_not_cached(self):
        verdict = {"interesting": False, "summary": "LLM evaluation inconclusive",
                   "bullets": [], "copy_action": {}, "inconclusive": True}
        kept, save = self._run(verdict)
        self.assertEqual(kept, [])
        save.assert_not_called()

    def test_definite_negative_verdict_is_cached(self):
        verdict = {"interesting": False, "summary": "boring", "bullets": [], "copy_action": {}}
        kept, save = self._run(verdict)
        self.assertEqual(kept, [])
        save.assert_called_once()
        self.assertFalse(save.call_args.kwargs["interesting"])


class PromptLogRotationTests(unittest.TestCase):
    def test_log_rotates_when_it_exceeds_the_cap(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "llm_prompts.jsonl"
            entry = [{"role": "user", "content": "x" * 100}]
            with patch.object(llm_filter, "PROMPT_LOG_FILE", log_file), \
                 patch.object(llm_filter, "PROMPT_LOG_MAX_BYTES", 500):
                for i in range(10):
                    llm_filter._log_prompt(entry, "m", f"k{i}")

            rotated = log_file.with_name(log_file.name + ".1")
            self.assertTrue(rotated.exists(), "expected a rotated .1 file")
            self.assertLessEqual(log_file.stat().st_size, 500 + 400)
            total_lines = sum(1 for _ in log_file.open()) + sum(1 for _ in rotated.open())
            # Rotation keeps exactly one previous generation, so some early
            # lines may be gone -- but nothing in the current + previous file
            # may be corrupted.
            for path in (log_file, rotated):
                for line in path.read_text().splitlines():
                    json.loads(line)
            self.assertGreater(total_lines, 0)

    def test_no_rotation_below_cap(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "llm_prompts.jsonl"
            with patch.object(llm_filter, "PROMPT_LOG_FILE", log_file), \
                 patch.object(llm_filter, "PROMPT_LOG_MAX_BYTES", 10_000_000):
                llm_filter._log_prompt([{"role": "user", "content": "hi"}], "m", "k")
            self.assertFalse(log_file.with_name(log_file.name + ".1").exists())
            self.assertEqual(len(log_file.read_text().splitlines()), 1)


class SystemPromptTests(unittest.TestCase):
    def test_prompt_states_the_live_strategy_count(self):
        from polybot import _build_strategies
        _, _, all_strats, _ = _build_strategies()
        self.assertIn(f"{len(all_strats)} automated detection strategies", llm_filter.SYSTEM_PROMPT)
        self.assertNotIn("9 automated detection strategies", llm_filter.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
