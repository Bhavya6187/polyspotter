"""
Topic mapping: tags from alert rows → (topic_name, icon) used in the UI.

The UI's canonical topics and their icons come from the design handoff's
data.jsx. Tags in the DB are more granular; we collapse them.
"""
from __future__ import annotations

TAG_TO_TOPIC: dict[str, tuple[str, str]] = {
    "Politics":     ("Politics",    "⚖️"),
    "Economics":    ("Economics",   "📈"),
    "Crypto":       ("Crypto",      "Ξ"),
    "NBA":          ("NBA",         "🏀"),
    "Geopolitics":  ("Geopolitics", "🛢️"),
    "Science":      ("Science",     "🚀"),
    "Soccer":       ("Soccer",      "⚽"),
    # Aliases / cousins
    "Sports":       ("NBA",         "🏀"),
    "Elections":    ("Politics",    "⚖️"),
    "Fed":          ("Economics",   "🏦"),
    "Rates":        ("Economics",   "🏦"),
    "Middle East":  ("Geopolitics", "🛢️"),
    "Space":        ("Science",     "🚀"),
    "Tech":         ("Science",     "🚀"),
}

DEFAULT_TOPIC = ("General", "📈")

def topic_for_tags(tags: list[str] | None) -> tuple[str, str]:
    """Return (topic_name, icon) for the first tag that has a mapping."""
    if not tags:
        return DEFAULT_TOPIC
    for t in tags:
        if t in TAG_TO_TOPIC:
            return TAG_TO_TOPIC[t]
    return DEFAULT_TOPIC

# Canonical topic list surfaced by /api/topics
CANONICAL_TOPICS = [
    ("Politics",    "⚖️"),
    ("Economics",   "📈"),
    ("Crypto",      "Ξ"),
    ("NBA",         "🏀"),
    ("Geopolitics", "🛢️"),
    ("Science",     "🚀"),
]
