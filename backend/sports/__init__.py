"""Sport-overlay plugin registry.

Plugins self-register on import. Resolution is first-match against tag aliases,
deterministic by registration order.
"""
from __future__ import annotations

from .base import OverlayResponse, SportOverlay

_PLUGINS: list[SportOverlay] = []


def register(plugin: SportOverlay) -> None:
    """Register a plugin. Called by each plugin module on import."""
    if not getattr(plugin, "sport_id", None):
        raise TypeError(f"{type(plugin).__name__} missing sport_id")
    if not getattr(plugin, "tag_aliases", None):
        raise TypeError(f"{type(plugin).__name__} missing tag_aliases")
    _PLUGINS.append(plugin)


def all_plugins() -> list[SportOverlay]:
    """Return registered plugins in registration order."""
    return list(_PLUGINS)


def resolve_for_tags(tags: list[str]) -> SportOverlay | None:
    """Return the first plugin whose tag_aliases intersect the given tags.

    Tags are matched case-insensitively.
    """
    lower = {t.lower() for t in tags if t}
    for plugin in _PLUGINS:
        aliases = {a.lower() for a in plugin.tag_aliases}
        if lower & aliases:
            return plugin
    return None


__all__ = ["OverlayResponse", "SportOverlay", "register", "all_plugins", "resolve_for_tags"]
