"""Minimal ESPN payload builders shared by the sport-overlay tests."""

TODAY = "20300101"
TOMORROW = "20300102"


def espn_scoreboard(event_id, home, away, home_name="", away_name=""):
    return {"events": [{"id": event_id, "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"abbreviation": home, "displayName": home_name}},
        {"homeAway": "away", "team": {"abbreviation": away, "displayName": away_name}},
    ]}]}]}


def espn_summary(event_id, state, home, away, home_name="", away_name="",
                 home_score="0", away_score="0"):
    return {"header": {"id": event_id, "competitions": [{
        "date": "2030-01-02T00:00Z",
        "status": {"type": {"state": state}},
        "competitors": [
            {"homeAway": "home", "score": home_score,
             "team": {"abbreviation": home, "displayName": home_name}},
            {"homeAway": "away", "score": away_score,
             "team": {"abbreviation": away, "displayName": away_name}},
        ],
    }]}}


def two_day_espn(home, away, home_name="", away_name=""):
    """(scoreboard_fn, summary_fn): today's board has the pair live as event
    'today'; tomorrow's board has them pre-game as event 'tmrw'."""
    def scoreboard(*args):
        date_str = args[-1] if args else None
        eid = "tmrw" if date_str == TOMORROW else "today"
        return espn_scoreboard(eid, home, away, home_name, away_name)

    def summary(*args):
        eid = args[-1]
        state = "pre" if eid == "tmrw" else "in"
        return espn_summary(eid, state, home, away, home_name, away_name)

    return scoreboard, summary
