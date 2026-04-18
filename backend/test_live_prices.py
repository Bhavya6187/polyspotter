from live_prices import batch_live_for_condition_ids


def test_batch_live_empty_input_returns_empty():
    assert batch_live_for_condition_ids([]) == {}


def test_batch_live_missing_condition_has_empty_dict(monkeypatch):
    # No rows returned → every requested cid gets an empty dict.
    monkeypatch.setattr("live_prices._fetch_batch", lambda ids: {})
    result = batch_live_for_condition_ids(["cid1", "cid2"])
    assert result == {"cid1": {}, "cid2": {}}


def test_batch_live_passes_through_fetched_data(monkeypatch):
    fake = {
        "cid1": {
            "yes_price": 0.44,
            "price_change_24h": 0.07,
            "volume_24h": 0.0,
            "candles": [0.31, 0.35, 0.40, 0.44],
        }
    }
    monkeypatch.setattr("live_prices._fetch_batch", lambda ids: fake)
    result = batch_live_for_condition_ids(["cid1", "cid2"])
    assert result["cid1"]["yes_price"] == 0.44
    assert result["cid1"]["candles"] == [0.31, 0.35, 0.40, 0.44]
    assert result["cid2"] == {}  # not in fetched set
