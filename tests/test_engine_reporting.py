from lendbot.bfx_client import Credit, Offer
from lendbot.engine import (Engine, format_learning_positions, frr_exposure_with_reserve,
                            merge_funding_positions)


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


def test_frrcap_command_updates_runtime_absolute_cap():
    engine = Engine.__new__(Engine)
    engine.scfg = {"min_offer_usd": 150, "frr_pilot": {"long_term_max_amount": 1000}}

    assert "1,000.00" in engine._cmd_frrcap("")
    assert "暫時改為 1,250.00" in engine._cmd_frrcap("1250")
    assert engine.scfg["frr_pilot"]["long_term_max_amount"] == 1250
    assert "不可低於" in engine._cmd_frrcap("100")


def test_frr_exposure_counts_reserved_funds_missing_from_active_offers():
    credits = [Credit(id=1, symbol="fUST", amount=3000, rate=0.0002,
                      period=2, mts_opening=0)]

    exposure, unidentified = frr_exposure_with_reserve(
        available=0, wallet_balance=6000, offers=[], credits=credits)

    assert exposure == 3000
    assert unidentified == 3000


def test_frr_exposure_does_not_double_count_known_fixed_offers():
    offers = [Offer(id=1, symbol="fUSD", mts_created=0, amount=800,
                    rate=0.0002, period=30)]

    exposure, unidentified = frr_exposure_with_reserve(
        available=200, wallet_balance=1000, offers=offers, credits=[])

    assert exposure == 0
    assert unidentified == 0


def test_long_term_exposure_counts_fixed_and_frr_120_day_positions_only():
    offers = [
        Offer(id=1, symbol="fUST", mts_created=0, amount=400, rate=0, period=120),
        Offer(id=2, symbol="fUST", mts_created=0, amount=300, rate=0.0003, period=120),
        Offer(id=3, symbol="fUST", mts_created=0, amount=200, rate=0.0003, period=30),
    ]

    exposure, unidentified = frr_exposure_with_reserve(
        available=100, wallet_balance=1000, offers=offers, credits=[])

    assert exposure == 700
    assert unidentified == 0


def test_merge_funding_positions_includes_loans_and_deduplicates_bucket_overlap():
    credit = Credit(id=1, symbol="fUST", amount=500, rate=0, period=120,
                    mts_opening=1)
    loan = Credit(id=2, symbol="fUST", amount=1000, rate=0, period=120,
                  mts_opening=2)
    same_position_in_other_bucket = Credit(id=1, symbol="fUST", amount=500, rate=0,
                                           period=120, mts_opening=1)

    merged = merge_funding_positions([credit], [loan, same_position_in_other_bucket])

    assert {position.id for position in merged} == {1, 2}
    assert sum(position.amount for position in merged) == 1500
