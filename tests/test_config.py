import pytest

from lendbot.config import Config, Env, load_config
from lendbot.strategy import long_term_exposure_cap


def test_learning_symbols_include_legacy_symbol_and_strategy_symbols():
    cfg = Config(env=Env(learning_symbol="fUSD"), raw={"symbols": ["fUSD", "fUST"]})

    assert cfg.learning_symbols == ["fUSD", "fUST"]


def test_learning_symbols_are_unique_and_keep_legacy_symbol_first():
    cfg = Config(env=Env(learning_symbol="fUST"), raw={"symbols": ["fUSD", "fUST"]})

    assert cfg.learning_symbols == ["fUST", "fUSD"]


def test_frr_third_stage_parameters():
    pilot = load_config().strategy["frr_pilot"]

    assert pilot["long_term_max_amount"] == 1000
    assert pilot["period_days"] == 120
    assert pilot["timeout_minutes"] == 4320


def test_long_batch_environment_overrides_and_blank_defaults(monkeypatch):
    monkeypatch.setenv("LONG_TERM_MAX_PER_OFFER", "500")
    monkeypatch.setenv("LONG_TERM_BATCH_AMOUNT", "800")
    monkeypatch.setenv("LONG_TERM_BATCH_MINUTES", "60")
    pilot = load_config().strategy["frr_pilot"]
    assert (pilot["max_offer_amount"], pilot["batch_max_amount"], pilot["batch_window_minutes"]) == (500, 800, 60)
    for name in ["LONG_TERM_MAX_PER_OFFER", "LONG_TERM_BATCH_AMOUNT", "LONG_TERM_BATCH_MINUTES"]:
        monkeypatch.setenv(name, "")
    pilot = load_config().strategy["frr_pilot"]
    assert (pilot["max_offer_amount"], pilot["batch_max_amount"], pilot["batch_window_minutes"]) == (1000, 1000, 30)


@pytest.mark.parametrize("name,value", [("LONG_TERM_BATCH_MINUTES", "0"),
                                      ("LONG_TERM_BATCH_AMOUNT", "nan"),
                                      ("LONG_TERM_MAX_PER_OFFER", "-1")])
def test_invalid_long_batch_configuration_fails_before_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        load_config()


def test_long_term_max_amount_env_override(monkeypatch):
    monkeypatch.setenv("LONG_TERM_MAX_AMOUNT", "1250")

    assert load_config().strategy["frr_pilot"]["long_term_max_amount"] == 1250


def test_lending_limits_are_independent_and_usdt_maps_to_fust(monkeypatch):
    monkeypatch.setenv("LENDING_MAX_USD", "5000")
    monkeypatch.setenv("LENDING_MAX_USDT", "3000.25")
    cfg = load_config()
    assert cfg.lending_limit("fUSD") == 5000
    assert cfg.lending_limit("fUST") == 3000.25
    assert cfg.lending_limit("fBTC") is None


def test_lending_limit_blank_is_unlimited_and_zero_stops_lending(monkeypatch):
    monkeypatch.setenv("LENDING_MAX_USD", " ")
    monkeypatch.setenv("LENDING_MAX_USDT", "0")
    cfg = load_config()
    assert cfg.lending_limit("fUSD") is None
    assert cfg.lending_limit("fUST") == 0


@pytest.mark.parametrize("name", ["LENDING_MAX_USD", "LENDING_MAX_USDT"])
@pytest.mark.parametrize("value", ["-1", "NaN", "inf", "-inf", "oops", "5,000"])
def test_invalid_lending_limit_fails_before_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_config()


def test_long_term_limits_override_shared_fallback_independently(monkeypatch):
    monkeypatch.setenv("LONG_TERM_MAX_AMOUNT", "1200")
    monkeypatch.setenv("LONG_TERM_MAX_USD", "600")
    monkeypatch.setenv("LONG_TERM_MAX_USDT", "0")
    cfg = load_config()
    assert long_term_exposure_cap(10000, cfg.strategy, "fUSD") == 600
    assert long_term_exposure_cap(10000, cfg.strategy, "fUST") == 0
    assert long_term_exposure_cap(10000, cfg.strategy) == 1200


def test_blank_coin_limit_uses_shared_or_legacy_default(monkeypatch):
    monkeypatch.setenv("LONG_TERM_MAX_USD", "500")
    monkeypatch.setenv("LONG_TERM_MAX_USDT", " ")
    monkeypatch.setenv("LONG_TERM_MAX_AMOUNT", " ")
    monkeypatch.setenv("FRR_MAX_AMOUNT", "1500")
    cfg = load_config()
    assert long_term_exposure_cap(10000, cfg.strategy, "fUSD") == 500
    assert long_term_exposure_cap(10000, cfg.strategy, "fUST") == 1500


@pytest.mark.parametrize("name", ["LONG_TERM_MAX_USD", "LONG_TERM_MAX_USDT", "LONG_TERM_MAX_AMOUNT"])
@pytest.mark.parametrize("value", ["-1", "NaN", "inf", "oops"])
def test_invalid_long_term_limit_blocks_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_config()
