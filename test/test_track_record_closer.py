"""format_track_record_closer guards + formatting (Delta 2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import tweet_utils as tu  # noqa: E402


def test_formats_winning_record():
    assert tu.format_track_record_closer(11, 4) == "Recent flags: 11-4."


def test_none_below_min_sample():
    assert tu.format_track_record_closer(6, 3) is None  # 9 settled < 10


def test_none_when_not_winning():
    assert tu.format_track_record_closer(8, 8) is None
    assert tu.format_track_record_closer(4, 12) is None


def test_min_settled_override():
    assert tu.format_track_record_closer(4, 1, min_settled=5) == "Recent flags: 4-1."


def test_closer_passes_flag_tweet_validation():
    # Appended as the final sentence of a flag tweet, the closer must not
    # trip validate_tweet (banned-closer phrases, record-opener regex, etc.).
    import twitter_pipeline as tp
    body = ("Volume on Mariners-Orioles just spiked to 6.8x its usual flow "
            "with $70k on Seattle. Mariners edge or Orioles value?")
    ok, err = tp.validate_tweet(f"{body}\n\nRecent flags: 11-4.")
    assert ok, err
