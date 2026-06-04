import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))
import charts  # noqa: E402


def _data(verdict, net):
    return {
        "verdict": verdict,
        "net_pl_usd": net,
        "record_str": "3-1",
        "event_label": "Padres-Phillies Over 7.5 runs",
        "outcome_side": "Over 7.5 runs",
        "flagged_days_ago": 2,
    }


def test_result_scorecard_renders_png_bytes_for_each_verdict():
    for verdict, net in [("CASHED", 31000.0), ("BURNED", -28000.0),
                         ("WASH", 0.0)]:
        png = charts.render_result_scorecard(_data(verdict, net))
        assert isinstance(png, (bytes, bytearray))
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_result_scorecard_is_registered_chart_type():
    assert "result_scorecard" in charts.CHART_TYPES
