"""X's weighted tweet length (twitter-text v3 rules)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
from tweet_utils import weighted_length  # noqa: E402


def test_ascii_counts_one_each():
    assert weighted_length("abc") == 3


def test_ellipsis_counts_two():
    assert weighted_length("…") == 2


def test_arrow_counts_two():
    assert weighted_length("→") == 2


def test_emoji_counts_two():
    assert weighted_length("\U0001F525") == 2


def test_general_punctuation_in_light_ranges_counts_one():
    # en/em dash and curly quotes sit in 8208-8223.
    assert weighted_length("–—“”") == 4


def test_bare_domain_counts_as_url():
    assert weighted_length("see example.com today") == 4 + 23 + 6


def test_scheme_url_counts_23():
    assert weighted_length("https://example.com/a/very/long/path?x=1") == 23


def test_decimal_is_not_a_domain():
    assert weighted_length("3.5x") == 4


def test_nfc_normalisation():
    assert weighted_length("é") == 1   # decomposed é -> one code point
    assert weighted_length("é") == 1
