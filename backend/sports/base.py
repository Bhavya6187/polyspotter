"""Base contract and envelope for sport-overlay plugins.

Each sport (basketball, cricket, MLB, NHL, soccer, ...) implements
SportOverlay and self-registers with the registry on import.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class OverlayResponse(BaseModel):
    """Wire envelope returned by the /api/market/{id}/overlay endpoint."""

    sport: str
    status: Literal["pre", "live", "final"]
    last_updated: str
    payload: dict[str, Any]


class SportOverlay(ABC):
    """Plugin contract for a sport's live-game overlay."""

    sport_id: str
    tag_aliases: tuple[str, ...]

    @abstractmethod
    def can_handle(self, title: str, tags: list[str], event_slug: str = "") -> bool:
        """Whether this plugin can produce an overlay for this market.

        Should return False fast when neither the title nor the event_slug
        carry enough info to identify two teams. Spread/moneyline/over-under
        titles name only one team (e.g. "Spread: Cavaliers (-4.5)"); for those
        the slug is the only source of the matchup.
        """

    @abstractmethod
    def fetch(
        self,
        condition_id: str,
        title: str,
        tags: list[str],
        event_slug: str = "",
    ) -> OverlayResponse | None:
        """Fetch live data; return None if no matching game exists today."""
