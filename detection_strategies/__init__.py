"""
Detection strategies for surfacing notable Polymarket trades.

Each strategy is a subclass of DetectionStrategy and implements the
`check_trade` method and/or the `analyze_all` method for batch analysis.
Add new strategies as separate files in this package, then register them
in `ALL_STRATEGIES`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Signal:
    """A single detection signal emitted by a strategy."""

    strategy: str  # strategy name, e.g. "new_wallet_large_bet"
    severity: float  # 0.0 to 10.0
    headline: str  # short description, e.g. "New wallet (4d 22h)"
    trade: dict  # representative trade dict
    condition_id: str = ""
    trade_hashes: list[str] = field(default_factory=list)

    @property
    def dedup_key(self) -> tuple[str, str]:
        """Key used for deduplication when compositing signals.

        Per-trade strategies that fire once per trade for the same wallet
        (like new_wallet_large_bet) use just the strategy name so that
        only the highest-severity instance survives dedup within a
        wallet+event group.  Other strategies use (strategy, headline)
        to preserve legitimately distinct signals (e.g., two different
        wallet_clustering funders).
        """
        # Strategies whose signals are inherently per-wallet, not per-trade.
        # Within a (wallet, event) group these should collapse to one signal.
        PER_WALLET_STRATEGIES = {"new_wallet_large_bet", "timing_relative_resolution"}
        if self.strategy in PER_WALLET_STRATEGIES:
            return (self.strategy, "")
        return (self.strategy, self.headline)


class DetectionStrategy(ABC):
    """Base class for all detection strategies."""

    name: str = "unnamed"
    description: str = ""

    @abstractmethod
    def check_trade(self, trade: dict) -> Signal | None:
        """Examine a single trade and return a Signal if it looks
        notable, or None to skip it."""
        ...

    def analyze_all(self, trades: list[dict]) -> list[Signal]:
        """Optional batch analysis across all trades in the window.
        Override this for strategies that need cross-trade context
        (e.g., clustering, volume aggregation).
        Returns a list of Signal objects."""
        return []


# -- registry ----------------------------------------------------------------
# Import concrete strategies so they're available via the package.
from detection_strategies.new_wallet_large_bet import NewWalletLargeBetStrategy  # noqa: E402
from detection_strategies.pre_event_volume_spike import PreEventVolumeSpikeStrategy  # noqa: E402
from detection_strategies.concentrated_one_sided import ConcentratedOneSidedStrategy  # noqa: E402
from detection_strategies.wallet_clustering import WalletClusteringStrategy  # noqa: E402
from detection_strategies.timing_relative_resolution import TimingRelativeResolutionStrategy  # noqa: E402
from detection_strategies.price_impact import PriceImpactStrategy  # noqa: E402
from detection_strategies.win_rate_tracking import WinRateTrackingStrategy  # noqa: E402
from detection_strategies.low_activity_large_bet import LowActivityLargeBetStrategy  # noqa: E402
from detection_strategies.correlated_cross_market import CorrelatedCrossMarketStrategy  # noqa: E402
