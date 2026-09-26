"""Cricket overlay game resolution. No DB or network required."""


def test_slug_date_game_beats_todays_scoreboard(monkeypatch):
    from sport_test_helpers import two_day_espn
    from sports import cricket
    sb, summ = two_day_espn("DC", "GT", "Delhi Capitals", "Gujarat Titans")
    monkeypatch.setattr(cricket, "_fetch_espn_scoreboard", sb)
    monkeypatch.setattr(cricket, "_fetch_espn_summary", summ)
    monkeypatch.setattr(cricket, "_fetch_espn_playbyplay", lambda *a, **k: None)
    cricket._match_cache.clear()
    data = cricket.get_cricket_data(
        "Delhi Capitals vs Gujarat Titans", event_slug="ipl-dc-gt-2030-01-02")
    assert data is not None
    assert data.espn_match_id == "tmrw"
    assert data.status == "pre"
