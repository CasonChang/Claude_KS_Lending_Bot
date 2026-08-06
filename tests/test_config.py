from lendbot.config import Config, Env


def test_learning_symbols_include_legacy_symbol_and_strategy_symbols():
    cfg = Config(env=Env(learning_symbol="fUSD"), raw={"symbols": ["fUSD", "fUST"]})

    assert cfg.learning_symbols == ["fUSD", "fUST"]


def test_learning_symbols_are_unique_and_keep_legacy_symbol_first():
    cfg = Config(env=Env(learning_symbol="fUST"), raw={"symbols": ["fUSD", "fUST"]})

    assert cfg.learning_symbols == ["fUST", "fUSD"]
