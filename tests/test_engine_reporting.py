from lendbot.engine import format_learning_positions


def test_format_learning_positions_shows_frr_and_repayment_warning():
    text = format_learning_positions([{
        "symbol": "fUSD", "wallet_total": 10095.0, "available": 595.0,
        "lent_total": 9500.0, "weighted_apy": 12.8, "offers": [],
        "credits": [
            {"amount": 500.0, "frr": True},
            {"amount": 9000.0, "frr": True},
        ],
    }])

    assert "fUSD｜放貸 9,500.00/10,095.00" in text
    assert "FRR 9,500.00（2 筆）" in text
    assert "⚠️ 可用餘額 595.00" in text


def test_format_learning_positions_ignores_small_interest_balance():
    text = format_learning_positions([{
        "symbol": "fUST", "wallet_total": 5003.0, "available": 3.0,
        "lent_total": 5000.0, "weighted_apy": 9.5, "offers": [],
        "credits": [{"amount": 500.0, "frr": True}] * 10,
    }])

    assert "fUST" in text
    assert "⚠️" not in text
