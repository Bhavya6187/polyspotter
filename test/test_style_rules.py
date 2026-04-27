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
