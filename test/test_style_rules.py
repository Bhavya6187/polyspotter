"""STYLE_RULES is the shared voice rule set used by both the thread bot
and the article bot. This test pins down what the constant must contain."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))


def test_style_rules_contains_expected_sections():
    from style_rules import STYLE_RULES

    # Section headers / lead phrases we expect to find verbatim
    expected_headers = [
        "Hard style rules (apply to EVERY tweet in the thread):",
        "- First-use unpack.",
        "- Analyst-speak is also BANNED.",
        "- Rewrite table — internalize the voice shift:",
        "## How to present numbers",
        "## Fact fidelity",
    ]
    for h in expected_headers:
        assert h in STYLE_RULES, f"missing header: {h!r}"


def test_style_rules_contains_banned_phrases():
    from style_rules import STYLE_RULES

    # A representative banned-phrase from each banned-phrase block
    expected_phrases = [
        '"funding tree"',
        '"composite score"',
        '"real size"',
        '"the sharp"',
    ]
    for p in expected_phrases:
        assert p in STYLE_RULES, f"missing phrase: {p}"


def test_storybot_system_prompt_still_contains_voice_rules():
    """Smoke test: the storybot system prompt assembles to a string that
    still contains the voice rules (proves the refactor didn't drop them)."""
    import storybot

    assert "Hard style rules (apply to EVERY tweet in the thread):" in storybot.SYSTEM_PROMPT
    assert "- Analyst-speak is also BANNED." in storybot.SYSTEM_PROMPT
    assert '"funding tree"' in storybot.SYSTEM_PROMPT
    assert "## How to present numbers" in storybot.SYSTEM_PROMPT
    assert "## Fact fidelity" in storybot.SYSTEM_PROMPT


def test_run_agent_accepts_system_prompt_and_kickoff_message_kwargs():
    """run_agent must accept explicit `system_prompt` and `kickoff_message`
    keyword arguments so articlebot can supply its own."""
    import inspect
    import storybot

    sig = inspect.signature(storybot.run_agent)
    assert "system_prompt" in sig.parameters
    assert "kickoff_message" in sig.parameters
    # Defaults so existing thread-bot callers don't break:
    assert sig.parameters["system_prompt"].default is not inspect.Parameter.empty
    assert sig.parameters["kickoff_message"].default is None or \
           sig.parameters["kickoff_message"].default is inspect.Parameter.empty


def test_run_agent_accepts_max_tool_calls_and_max_iterations_kwargs():
    """run_agent must accept budget overrides so articlebot can use its
    higher budgets (40/35) without changing the module-level defaults."""
    import inspect
    import storybot

    sig = inspect.signature(storybot.run_agent)
    assert "max_tool_calls" in sig.parameters
    assert "max_iterations" in sig.parameters


def test_run_agent_accepts_json_retry_hint_kwarg():
    """run_agent must accept a `json_retry_hint` keyword argument so callers
    can supply a schema-specific retry hint without the default falling back
    to a thread-bot schema."""
    import inspect
    import storybot

    sig = inspect.signature(storybot.run_agent)
    assert "json_retry_hint" in sig.parameters
    # Default must be None so existing thread-bot callers work unchanged.
    assert sig.parameters["json_retry_hint"].default is None
