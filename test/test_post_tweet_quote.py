"""post_tweet quote_tweet_id plumbing (Delta 1)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import tweet_utils as tu  # noqa: E402


class FakeClient:
    def __init__(self):
        self.kwargs = None

    def create_tweet(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(data={"id": "555"})


def test_quote_tweet_id_passed_through():
    fc = FakeClient()
    tid = tu.post_tweet("hello", twitter_client=fc, twitter_api_v1=None,
                        media_png=None, quote_tweet_id="123", dry_run=False)
    assert tid == "555"
    assert fc.kwargs["quote_tweet_id"] == "123"
    assert fc.kwargs["text"] == "hello"


def test_quote_tweet_id_omitted_when_none():
    fc = FakeClient()
    tu.post_tweet("hello", twitter_client=fc, twitter_api_v1=None,
                  media_png=None, dry_run=False)
    assert "quote_tweet_id" not in fc.kwargs


def test_dry_run_skips_client_entirely():
    tid = tu.post_tweet("hello", twitter_client=None, twitter_api_v1=None,
                        media_png=None, quote_tweet_id="123", dry_run=True)
    assert tid.startswith("dryrun-")
