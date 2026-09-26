"""The LINKED ACCOUNTS grid tile must only render for wallets that actually
share a funder (facts_bundle.linked_wallets), never for same-direction
cluster size."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storybot"))

import chart_grid  # noqa: E402


def test_same_direction_cluster_alone_gets_no_linked_tile():
    assert chart_grid._tile_linked_accounts({"cluster_size": 7}, hero="price_sparkline") is None


def test_linked_wallets_render_the_tile():
    tile = chart_grid._tile_linked_accounts({"cluster_size": 37, "linked_wallets": 8}, hero="price_sparkline")
    assert tile is not None
    assert tile.big == "8 wallets"
    assert tile.label == "one funder"


def test_below_minimum_linked_count_gets_no_tile():
    n = chart_grid.MIN_CLUSTER_SIZE_FOR_TILE - 1
    assert chart_grid._tile_linked_accounts({"linked_wallets": n}, hero="price_sparkline") is None


def test_cluster_card_hero_suppresses_the_tile():
    assert chart_grid._tile_linked_accounts({"linked_wallets": 9}, hero="cluster_card") is None
