"""Weekly scoreboard renderer + result_pipeline weekly posting (Delta 4)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def _data(n_cashed=11, n_burned=4, net=58000.0):
    return {"n_cashed": n_cashed, "n_burned": n_burned,
            "net_pl_usd": net, "week_label": "Week of Jun 8"}


def test_weekly_scoreboard_renders_png_bytes():
    for net in (58000.0, -12000.0, 0.0):
        png = charts.render_weekly_scoreboard(_data(net=net))
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_weekly_scoreboard_handles_zero_results():
    png = charts.render_weekly_scoreboard(_data(n_cashed=0, n_burned=0, net=0.0))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
