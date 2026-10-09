"""額度／提領回流測試：全程使用假交易所，不連線、不啟動背景引擎。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lendbot.bfx_client import BfxError, Credit, FundingTicker, Offer
from lendbot.config import Config, Env
from lendbot.engine import Engine, SimAccount, lending_exposure
from lendbot.strategy import MarketView, long_term_exposure_cap


def credit(amount, cid=1, period=2):
    return Credit(id=cid, symbol="fUSD", amount=amount, rate=0.0002,
                  period=period, mts_opening=0)


def offer(amount, oid=1, period=2):
    return Offer(id=oid, symbol="fUSD", mts_created=oid, amount=amount,
                 rate=0.0002, period=period)


VIEW = MarketView(frr=0.0003, best_ask=0.0002, depth_rate=0.0002,
                  trade_iqm=0.0002, recent_high=0.0003, spike=False, anchor=0.0002)


class FakeClient:
    def __init__(self, wallet=10000, credits=(), offers=(), loans=()):
        self.wallet = wallet
        self.credits = list(credits)
        self.loans = list(loans)
        self.offers = list(offers)
        self.canceled = []
        self.submitted = []
        self.cancel_error = False
        self.fill_on_cancel = False
        self.fail_refresh = False

    def funding_wallet(self, currency):
        if self.fail_refresh and self.canceled:
            raise BfxError("snapshot unavailable")
        merged = {c.id: c for c in [*self.credits, *self.loans]}
        available = self.wallet - sum(c.amount for c in merged.values()) - sum(o.amount for o in self.offers)
        return self.wallet, available

    def funding_available(self, currency):
        return self.funding_wallet(currency)[1]

    def active_offers(self, sym):
        return list(self.offers)

    def active_credits(self, sym):
        return list(self.credits)

    def active_loans(self, sym):
        return list(self.loans)

    def cancel_offer(self, oid):
        if self.fill_on_cancel:
            o = next(o for o in self.offers if o.id == oid)
            self.offers.remove(o)
            self.credits.append(credit(o.amount, cid=oid))
            raise BfxError("offer already filled")
        if self.cancel_error:
            raise BfxError("cancel rejected")
        self.canceled.append(oid)
        self.offers = [o for o in self.offers if o.id != oid]

    def submit_offer(self, sym, amount, rate, period, offer_type="LIMIT"):
        self.submitted.append((sym, amount, period, offer_type))
        self.offers.append(Offer(id=100 + len(self.submitted), symbol=sym,
                                 mts_created=100, amount=amount, rate=rate, period=period))

    def funding_ticker(self, sym):
        return FundingTicker(frr=0.0003, bid=0.0002, ask=0.0002,
                             last=0.0002, high=0.0003, low=0.0002)

    def funding_book(self, *args, **kwargs):
        return []

    def funding_trades(self, *args, **kwargs):
        return []

    def credits_history(self, *args, **kwargs):
        return []


def engine(client, limit=5000, usdt_limit=None, dry_run=False, frr=False):
    cfg = Config(env=Env(bfx_key="test", bfx_secret="test", dry_run=dry_run,
                         lending_max_usd=limit, lending_max_usdt=usdt_limit),
                 raw={"symbols": ["fUSD", "fUST"], "strategy": {
                     "floor_hours": 0, "min_offer_usd": 150,
                     "ladder": [{"weight": 1, "mult": 1}],
                     "frr_pilot": {"enabled": frr, "long_term_max_amount": 1000},
                 }})
    bot = Engine(cfg, client, Mock(), SimpleNamespace(commands={}, notify=Mock()))
    bot.states["fUSD"].last_view = VIEW
    return bot


def process(bot):
    # 市場撤单規則不影響這些用來驗證額度的既有單。
    bot._cancel_stale = Mock(return_value=0)
    bot._process_symbol("fUSD", bot.states["fUSD"])


def test_withdrawal_waits_for_repayments_without_reinvesting_excess():
    client = FakeClient(credits=[credit(10000)])
    bot = engine(client)
    process(bot)
    client.credits = [credit(7000)]  # 先還 3000：仍超額，不續掛
    process(bot)
    assert client.submitted == []
    client.credits = [credit(4000)]  # 再還 3000：只補 1000 到 5000
    process(bot)
    assert sum(x[1] for x in client.submitted) == 1000
    assert client.funding_available("USD") == 5000


def test_lower_cap_cancels_excess_newest_offers_and_refills_only_room():
    client = FakeClient(credits=[credit(4000)], offers=[offer(600, 2), offer(700, 3)])
    bot = engine(client)
    process(bot)
    assert client.canceled == [3]  # 保留較早 600 元單
    assert sum(x[1] for x in client.submitted) == 400
    assert sum(o.amount for o in client.offers) == 1000
    assert client.funding_available("USD") == 5000


def test_zero_cancels_all_pending_including_frr_but_keeps_active_loans():
    client = FakeClient(credits=[credit(4000)],
                        offers=[offer(600, 2), offer(700, 3, 120)], loans=[credit(500, 4)])
    bot = engine(client, limit=0)
    process(bot)
    assert client.canceled == [3, 2]
    assert client.submitted == []
    assert sum(c.amount for c in [*client.credits, *client.loans]) == 4500


def test_failed_cancel_does_not_release_budget():
    client = FakeClient(credits=[credit(4000)], offers=[offer(2000)])
    client.cancel_error = True
    bot = engine(client)
    process(bot)
    assert client.submitted == []
    assert client.offers[0].amount == 2000


def test_offer_filled_during_cancel_is_counted_as_lent():
    client = FakeClient(credits=[credit(4000, 10)], offers=[offer(2000)])
    client.fill_on_cancel = True
    bot = engine(client)
    process(bot)
    assert sum(c.amount for c in client.credits) == 6000
    assert client.submitted == []


def test_failed_refresh_after_cancel_blocks_all_submissions():
    client = FakeClient(credits=[credit(4000)], offers=[offer(2000)])
    client.fail_refresh = True
    bot = engine(client)
    with pytest.raises(BfxError, match="snapshot unavailable"):
        process(bot)
    assert client.submitted == []


def test_lowering_limit_cancels_pending_even_when_public_market_is_unavailable():
    client = FakeClient(credits=[credit(4000)], offers=[offer(2000)])
    client.funding_ticker = Mock(side_effect=BfxError("market unavailable"))
    bot = engine(client, limit=0)
    with pytest.raises(BfxError, match="market unavailable"):
        process(bot)
    assert client.canceled == [1]
    assert client.submitted == []


def test_missing_offers_are_counted_from_wallet_reserve():
    offers, credits = [], [credit(4000)]
    bot = engine(FakeClient())
    assert lending_exposure(0, 10000, offers, credits) == 10000
    assert bot._lending_budget("fUSD", 0, offers, credits, 10000) == 0
    assert bot._lending_budget("fUSD", 4000, offers, credits, 10000) == 0


def test_frr_and_ladder_share_one_total_budget():
    client = FakeClient(credits=[credit(4500)])
    bot = engine(client, frr=True)
    offers = []
    st = bot.states["fUSD"]
    available = bot._maybe_place_frr("fUSD", st, 5500, VIEW, 0, "ts", offers, client.credits, 10000)
    bot._place_ladder("fUSD", st, available, VIEW, 0, "ts", offers, client.credits, 10000)
    assert client.submitted == [("fUSD", 500, 120, "FRRDELTAVAR")]


def test_frr_and_ladder_can_both_place_without_exceeding_total_or_long_cap():
    client = FakeClient(credits=[credit(3000)])
    bot = engine(client, frr=True)
    offers = []
    st = bot.states["fUSD"]
    available = bot._maybe_place_frr("fUSD", st, 7000, VIEW, 0, "ts", offers, client.credits, 10000)
    bot._place_ladder("fUSD", st, available, VIEW, 0, "ts", offers, client.credits, 10000)
    assert sum(x[1] for x in client.submitted) == 2000
    assert sum(x[1] for x in client.submitted if x[2] == 120) == 1000


def test_dry_run_does_not_cancel_or_submit_and_combined_proposals_respect_cap():
    client = FakeClient(credits=[credit(4500)], offers=[offer(1000)])
    bot = engine(client, dry_run=True)
    process(bot)
    assert client.canceled == client.submitted == []
    assert bot.states["fUSD"].last_plans == []
    assert bot.store.log_action.call_args_list[0].args[0] == "cancel(dry)"


def test_dry_run_frr_reserves_budget_for_ladder_proposals():
    client = FakeClient(credits=[credit(4500)])
    bot = engine(client, dry_run=True, frr=True)
    offers = []
    st = bot.states["fUSD"]
    available = bot._maybe_place_frr("fUSD", st, 5500, VIEW, 0, "ts", offers, client.credits, 10000)
    bot._place_ladder("fUSD", st, available, VIEW, 0, "ts", offers, client.credits, 10000)
    assert client.submitted == []
    assert st.last_plans == []


def test_manual_lend_and_go_cannot_bypass_limit():
    client = FakeClient(credits=[credit(5000)])
    bot = engine(client)
    assert "最多可新增 0.00" in bot._cmd_lend("fUSD 250 11.5 7")
    assert "上限" in bot._cmd_go()
    assert client.submitted == []


def test_manual_go_only_uses_remaining_room():
    client = FakeClient(credits=[credit(4500)])
    bot = engine(client)
    assert "已執行掛單" in bot._cmd_go()
    assert 499.9 < sum(x[1] for x in client.submitted) <= 500


def test_manual_lend_consumes_room_and_next_order_cannot_reuse_it():
    client = FakeClient(credits=[credit(4500)])
    bot = engine(client)
    assert "已掛單" in bot._cmd_lend("fUSD 300 11.5 7")
    assert "最多可新增 200.00" in bot._cmd_lend("fUSD 250 11.5 7")
    assert sum(x[1] for x in client.submitted) == 300


def test_usdt_limit_is_independent_from_usd_and_unset_preserves_behavior():
    bot = engine(FakeClient(), limit=5000, usdt_limit=3000)
    assert bot._lending_budget("fUSD", 10000, [], [], 10000) == 5000
    assert bot._lending_budget("fUST", 10000, [], [], 10000) == 3000
    client = FakeClient(credits=[credit(4000)])
    bot = engine(client, limit=None)
    process(bot)
    assert sum(x[1] for x in client.submitted) == 6000


def test_credits_and_loans_overlap_is_deduplicated():
    c = credit(4500)
    client = FakeClient(credits=[c], loans=[c])
    bot = engine(client)
    process(bot)
    assert sum(x[1] for x in client.submitted) == 500


def test_subminimum_room_is_not_rounded_up():
    client = FakeClient(credits=[credit(4850.01)])
    bot = engine(client)
    process(bot)
    assert client.submitted == []


def test_paused_keeps_existing_offers_and_does_not_place():
    client = FakeClient(credits=[credit(4000)], offers=[offer(2000)])
    bot = engine(client, limit=0)
    bot.paused = True
    process(bot)
    assert client.canceled == client.submitted == []


def test_status_shows_configured_total_limit():
    bot = engine(FakeClient(credits=[credit(4000)]))
    text = bot._status_text()
    assert "fUSD 總放貸上限 5,000.00" in text
    assert "已承諾 4,000.00｜總額度最多可新增 1,000.00｜可用中保留 5,000.00" in text


def test_simulation_respects_cap_and_returns_canceled_money_to_available_balance():
    bot = engine(FakeClient())
    bot.has_auth = False
    bot.dry_run = True
    sim = SimAccount(balance=4000, credits=[credit(4000)], offers=[offer(2000)])
    bot.states["fUSD"].sim = sim
    process(bot)
    assert sim.balance == 5000
    assert sum(c.amount for c in sim.credits) + sum(o.amount for o in sim.offers) == 5000
    assert bot.client.submitted == bot.client.canceled == []


@pytest.mark.parametrize("symbol,cap", [("fUSD", 500), ("fUST", 300)])
def test_frr_uses_the_matching_coin_long_term_limit(symbol, cap):
    client = FakeClient(credits=[credit(4000)])
    bot = engine(client, frr=True)
    bot.scfg["frr_pilot"]["long_term_max_amounts"] = {"fUSD": 500, "fUST": 300}
    st = bot.states[symbol]
    offers = []
    available = bot._maybe_place_frr(symbol, st, 6000, VIEW, 0, "ts", offers, client.credits, 10000)
    bot._place_ladder(symbol, st, available, VIEW, 0, "ts", offers, client.credits, 10000)
    assert sum(x[1] for x in client.submitted if x[2] == 120) == cap


def test_zero_long_limit_stops_frr_but_allows_short_ladder():
    client = FakeClient(credits=[credit(4000)])
    bot = engine(client, frr=True)
    bot.scfg["frr_pilot"]["long_term_max_amounts"] = {"fUSD": 0}
    st = bot.states["fUSD"]
    offers = []
    available = bot._maybe_place_frr("fUSD", st, 6000, VIEW, 0, "ts", offers, client.credits, 10000)
    bot._place_ladder("fUSD", st, available, VIEW, 0, "ts", offers, client.credits, 10000)
    assert sum(x[1] for x in client.submitted) == 1000
    assert all(x[2] < 120 for x in client.submitted)


def test_fixed_long_ladder_and_go_obey_coin_limit():
    client = FakeClient(credits=[credit(4000)])
    bot = engine(client)
    bot.scfg["periods"] = [{"apy": 0, "days": 120}]
    bot.scfg["frr_pilot"]["long_term_max_amounts"] = {"fUSD": 300}
    assert "已執行掛單" in bot._cmd_go()
    assert sum(x[1] for x in client.submitted) == 300
    assert "120天上限" in bot._cmd_lend("fUSD 150 11.5 120")
    assert sum(x[1] for x in client.submitted) == 300


def test_longcap_coin_command_changes_only_target_and_legacy_changes_both():
    bot = engine(FakeClient())
    assert "USD硬上限暫時改為 500.00" in bot._cmd_frrcap("USD 500")
    assert long_term_exposure_cap(10000, bot.scfg, "fUSD") == 500
    assert long_term_exposure_cap(10000, bot.scfg, "fUST") == 1000
    assert "USDT硬上限暫時改為 0.00" in bot._cmd_frrcap("USDT 0")
    assert "USD 500.00｜USDT 0.00" in bot._cmd_frrcap("")
    assert "暫時改為 750.00" in bot._cmd_frrcap("750")
    assert long_term_exposure_cap(10000, bot.scfg, "fUSD") == 750
    assert long_term_exposure_cap(10000, bot.scfg, "fUST") == 750


@pytest.mark.parametrize("args", ["USD NaN", "USDT inf", "USD -1", "BTC 500"])
def test_longcap_rejects_invalid_values_without_changing_caps(args):
    bot = engine(FakeClient())
    bot._cmd_frrcap(args)
    assert long_term_exposure_cap(10000, bot.scfg, "fUSD") == 1000
    assert long_term_exposure_cap(10000, bot.scfg, "fUST") == 1000
