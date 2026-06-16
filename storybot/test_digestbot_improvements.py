"""Tests for the digest improvements:
  #2 conviction floor, #3 cross-day staleness dedup, #4 on-site links + UTM +
  view-in-browser, #5 market thumbnails, #6 category normalization, #7 preheader.
"""
import digestbot


# --- #4 links: on-site event URLs, UTM tagging, view-in-browser -------------

def test_with_utm_appends_query_when_none():
    url = digestbot._with_utm("https://polyspotter.com/event/x")
    assert url == "https://polyspotter.com/event/x?utm_source=digest&utm_medium=email&utm_campaign=daily"


def test_with_utm_uses_ampersand_when_query_present():
    url = digestbot._with_utm("https://polyspotter.com/digest/2026-06-16?foo=1")
    assert url == "https://polyspotter.com/digest/2026-06-16?foo=1&utm_source=digest&utm_medium=email&utm_campaign=daily"


def test_link_for_pick_prefers_onsite_event_url(monkeypatch):
    monkeypatch.setattr(digestbot, "SITE_URL", "https://polyspotter.com")
    pick = {"event_slug": "nba-sas-nyk-2026-06-10",
            "market_url": "https://polymarket.com/event/nba-sas-nyk-2026-06-10"}
    url = digestbot.link_for_pick(pick)
    assert url.startswith("https://polyspotter.com/event/nba-sas-nyk-2026-06-10")
    assert "utm_source=digest" in url
    # never leaks the reader off to polymarket when we have a real slug
    assert "polymarket.com" not in url


def test_link_for_pick_falls_back_to_market_url_for_condition_id(monkeypatch):
    monkeypatch.setattr(digestbot, "SITE_URL", "https://polyspotter.com")
    pick = {"event_slug": "0xabc123", "market_url": "https://polymarket.com/event/foo"}
    assert digestbot.link_for_pick(pick) == "https://polymarket.com/event/foo"


def test_browser_url_is_onsite_digest_permalink(monkeypatch):
    monkeypatch.setattr(digestbot, "SITE_URL", "https://polyspotter.com")
    url = digestbot.browser_url("2026-06-16")
    assert url.startswith("https://polyspotter.com/digest/2026-06-16")
    assert "utm_source=digest" in url


# --- #2 conviction floor ----------------------------------------------------

def test_meets_conviction_passes_on_dollar_size():
    assert digestbot.meets_conviction({"total_usd": 250000, "trade_count": 3}) is True


def test_meets_conviction_passes_on_trade_count_even_if_small_dollars():
    # coordinated flow: many small trades still counts as a signal
    assert digestbot.meets_conviction({"total_usd": 4000, "trade_count": 12}) is True


def test_meets_conviction_rejects_lone_small_bet():
    # the "single $1,000 wager" noise that leaked into Resolving Today
    assert digestbot.meets_conviction({"total_usd": 1000, "trade_count": 1}) is False


def test_meets_conviction_handles_missing_fields():
    assert digestbot.meets_conviction({}) is False


# --- #3 cross-day staleness dedup -------------------------------------------

def test_extract_event_slugs_from_content_json():
    content = {
        "sections": [
            {"items": [{"event_slug": "a"}, {"event_slug": "b"}]},
            {"items": [{"event_slug": "c"}]},
        ]
    }
    assert digestbot.extract_event_slugs(content) == {"a", "b", "c"}


def test_extract_event_slugs_tolerates_garbage():
    assert digestbot.extract_event_slugs(None) == set()
    assert digestbot.extract_event_slugs({"sections": "nope"}) == set()
    assert digestbot.extract_event_slugs('{"sections": [{"items": [{"event_slug": "z"}]}]}') == {"z"}


def _cand(slug, score=50.0, usd=200000, trades=10):
    return {"event_slug": slug, "composite_score": score,
            "total_usd": usd, "trade_count": trades}


def test_build_week_pool_excludes_today_and_featured_and_low_conviction():
    upcoming = [_cand("today-dupe"), _cand("featured-1"), _cand("fresh-1", score=90)]
    hot = [_cand("noise", usd=500, trades=1), _cand("fresh-2", score=80)]
    week = digestbot.build_week_pool(
        upcoming, hot,
        today_slugs={"today-dupe"},
        featured_slugs={"featured-1"},
    )
    slugs = [c["event_slug"] for c in week]
    assert "today-dupe" not in slugs        # already in Resolving Today
    assert "featured-1" not in slugs        # featured in a recent digest
    assert "noise" not in slugs             # below the conviction floor
    assert slugs == ["fresh-1", "fresh-2"]  # sorted by composite desc


def test_build_week_pool_dedupes_keeping_highest_composite():
    week = digestbot.build_week_pool(
        [_cand("x", score=30)], [_cand("x", score=95)],
        today_slugs=set(), featured_slugs=set(),
    )
    assert [c["event_slug"] for c in week] == ["x"]
    assert week[0]["composite_score"] == 95


# --- #5 market thumbnail ----------------------------------------------------

def test_shape_candidate_carries_market_image():
    row = {
        "event_slug": "nba-x", "condition_id": "0x1", "market_title": "t",
        "market_url": "u", "market_image": "https://img/x.png",
        "end_date": None, "event_end_estimate": None,
        "total_usd": 1.0, "trade_count": 1, "composite_score": 1.0,
        "llm_copy_action": "{}", "tags": "[]",
    }
    assert digestbot.shape_candidate(row)["image"] == "https://img/x.png"


def test_assemble_content_carries_image_and_render_shows_img():
    pick = {"event_slug": "nba-x", "title": "T", "market_url": "u",
            "image": "https://img/x.png", "leaning": "Yes (60% implied)"}
    write_out = {"subject": "s", "intro": "", "writeups": [
        {"event_slug": "nba-x", "headline": "H", "blurb": "B"}]}
    content = digestbot.assemble_content(write_out, today_picks=[pick], week_picks=[])
    item = content["sections"][0]["items"][0]
    assert item["image"] == "https://img/x.png"
    html = digestbot.render_email_html(content)
    assert "<img" in html
    assert "https://img/x.png" in html


def test_render_email_html_encodes_spaces_in_image_url():
    # Some Polymarket S3 image keys contain literal spaces (e.g. 'soccer ball.png'),
    # which break the <img src> in strict clients unless percent-encoded.
    pick = {"event_slug": "x", "title": "T", "market_url": "u",
            "image": "https://img/soccer ball.png", "leaning": "Yes (50% implied)"}
    write_out = {"subject": "s", "intro": "", "writeups": [
        {"event_slug": "x", "headline": "H", "blurb": "B"}]}
    content = digestbot.assemble_content(write_out, today_picks=[pick], week_picks=[])
    html = digestbot.render_email_html(content)
    assert "soccer%20ball.png" in html
    assert "soccer ball.png" not in html


def test_render_email_html_omits_img_when_no_image():
    pick = {"event_slug": "nba-x", "title": "T", "market_url": "u",
            "image": None, "leaning": "Yes (60% implied)"}
    write_out = {"subject": "s", "intro": "", "writeups": [
        {"event_slug": "nba-x", "headline": "H", "blurb": "B"}]}
    content = digestbot.assemble_content(write_out, today_picks=[pick], week_picks=[])
    assert "<img" not in digestbot.render_email_html(content)


# --- #6 category normalization ----------------------------------------------

def test_category_label_infers_broad_for_bare_geopolitics_specific():
    # the lonely "Iran" chip — infer the broad half rather than show it alone
    assert digestbot.category_label(["Iran"]) == "Politics · Iran"


def test_category_label_returns_none_when_no_broad_and_not_inferable():
    assert digestbot.category_label(["Wimbledon Qualifiers Zzz"]) is None


def test_category_label_normalizes_counter_strike():
    assert digestbot.category_label(["Esports", "Counter Strike 2"]) == "Esports · Counter-Strike 2"


def test_category_label_prefers_tournament_over_generic_sport():
    assert digestbot.category_label(["Sports", "Soccer", "FIFA World Cup"]) == "Sports · FIFA World Cup"
    # but a generic specific is fine when nothing more specific exists
    assert digestbot.category_label(["Sports", "Soccer"]) == "Sports · Soccer"


# --- #7 preheader + view-in-browser -----------------------------------------

def test_render_email_html_includes_hidden_preheader():
    content = {"subject": "Subj", "intro": "Big day on Polymarket.", "sections": []}
    html = digestbot.render_email_html(content)
    # hidden preheader present and placed before the visible headline
    assert "max-height:0" in html
    assert html.index("Big day on Polymarket.") < html.index("<h1")


def test_render_email_html_includes_view_in_browser_when_given():
    content = {"subject": "s", "intro": "", "sections": []}
    html = digestbot.render_email_html(
        content, browser_url="https://polyspotter.com/digest/2026-06-16")
    assert "View in browser" in html
    assert "https://polyspotter.com/digest/2026-06-16" in html


def test_render_email_html_omits_view_in_browser_when_absent():
    content = {"subject": "s", "intro": "", "sections": []}
    assert "View in browser" not in digestbot.render_email_html(content)
