from topics import topic_for_tags, TAG_TO_TOPIC

def test_known_tag_maps_to_topic():
    assert topic_for_tags(["Politics"]) == ("Politics", "⚖️")
    assert topic_for_tags(["Crypto"]) == ("Crypto", "Ξ")
    assert topic_for_tags(["NBA"]) == ("NBA", "🏀")
    assert topic_for_tags(["Geopolitics"]) == ("Geopolitics", "🛢️")

def test_unknown_tag_falls_back_to_general():
    assert topic_for_tags(["Uncharted"]) == ("General", "📈")

def test_empty_tags_falls_back():
    assert topic_for_tags([]) == ("General", "📈")
    assert topic_for_tags(None) == ("General", "📈")

def test_first_matching_tag_wins():
    assert topic_for_tags(["Unknown", "Politics"]) == ("Politics", "⚖️")

def test_tag_to_topic_contains_spec_topics():
    for t in ["Politics", "Economics", "Crypto", "NBA", "Geopolitics", "Science", "Soccer"]:
        assert t in TAG_TO_TOPIC
