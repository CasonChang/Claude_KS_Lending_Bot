from tools.export_public_anchors import public_rows


def test_export_whitelists_market_fields_and_rejects_invalid_rows():
    rows = [{"ts": "2026-10-09T00:00:00Z", "symbol": "fUST", "anchor_apy": 8.5,
             "wallet": 10000, "offers": [1], "password": "private"},
            {"ts": "invalid", "symbol": "fUSD", "anchor_apy": 9},
            {"ts": "2026-10-09", "symbol": "private", "anchor_apy": 9},
            {"ts": "2026-10-09", "symbol": "fUSD", "anchor_apy": float("nan")},
            {"ts": "2026-10-09", "symbol": "fUSD", "anchor_apy": True}]
    assert public_rows(rows) == [{"ts": "2026-10-09T00:00:00Z", "symbol": "fUST", "anchor_apy": 8.5}]
