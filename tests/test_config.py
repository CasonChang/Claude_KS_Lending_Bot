from lendbot.config import Config, Env, load_config


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


def test_long_term_max_amount_env_override(monkeypatch):
    monkeypatch.setenv("LONG_TERM_MAX_AMOUNT", "1250")

    assert load_config().strategy["frr_pilot"]["long_term_max_amount"] == 1250
