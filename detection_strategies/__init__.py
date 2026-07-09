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
    # Effective cluster direction ("outcome:side"), set by cluster strategies.
    # The representative trade's own outcome/side can't be used for this: a
    # direction-remapped SELL member would flip the identity between scans.
    direction: str = ""

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


# -- composite scoring ---------------------------------------------------------
# Backtest-derived ranking weights (2026-07, see STRATEGY_USAGE_REPORT.md):
# price_impact was the only strategy positive in both backtest windows
# (+7.7% / +5.8% per-market copy return); new_wallet_large_bet,
# pre_event_volume_spike, win_rate_tracking and low_activity_large_bet were
# flat-to-negative in both.
STRATEGY_WEIGHTS: dict[str, float] = {
    "price_impact": 1.3,
    "correlated_cross_market": 1.0,
    "concentrated_one_sided": 1.0,
    "wallet_clustering": 0.9,
    "new_wallet_large_bet": 0.7,
    "pre_event_volume_spike": 0.7,
    "win_rate_tracking": 0.7,
    "low_activity_large_bet": 0.7,
    "timing_relative_resolution": 0.5,  # retired from the scan roster
}


def compute_composite_score(signals) -> float:
    """Aggregate a set of Signals into an alert's composite score.

    Takes the max severity per strategy (so one strategy firing many
    signals on the same alert can't stack), applies STRATEGY_WEIGHTS,
    then sums the per-strategy contributions with diminishing returns
    (1, 1/2, 1/4, ... strongest first). Replaces the raw severity sum:
    the 2026-06/07 backtests showed summed severity was non-monotonic
    with graded copy returns because correlated_cross_market severity
    stacking dominated the 8-12 score band (-5.2% per-market return).
    """
    best_per_strategy: dict[str, float] = {}
    for s in signals:
        w = STRATEGY_WEIGHTS.get(s.strategy, 1.0)
        weighted = w * s.severity
        if weighted > best_per_strategy.get(s.strategy, 0.0):
            best_per_strategy[s.strategy] = weighted
    contributions = sorted(best_per_strategy.values(), reverse=True)
    return sum(v * (0.5 ** i) for i, v in enumerate(contributions))


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
