from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests import Timeout

from lendbot.bfx_client import BfxClient, BfxError, Credit, LedgerEntry, Offer
from lendbot.config import Config, Env, load_config
from lendbot.daily_report import CurrencyReport, PostedIncome, TAIPEI, format_daily_report, summarize_income
from lendbot.engine import Engine

NOW = datetime(2026, 10, 15, 10, tzinfo=TAIPEI)


def entry(day, amount=2, capital=10000, eid=None, hour=9, minute=30):
    posted = (NOW - timedelta(days=day)).replace(hour=hour, minute=minute)
    return LedgerEntry(id=day + 1 if eid is None else eid, currency="USD",
                       mts=int(posted.timestamp() * 1000), amount=amount,
                       balance=capital + amount, description="Margin Funding Payment")


def test_posted_income_uses_taipei_dates_and_never_substitutes_yesterday():
    before_posting = NOW.replace(hour=9)
    rows = [entry(day) for day in range(8)]
    result = summarize_income(rows, before_posting)
    assert result.today is None and result.seven_day_apy is None
    result = summarize_income(rows, NOW)
    assert result.today == 2
    assert result.seven_day_apy == pytest.approx(7.3)
    # UTC 還是前一天，台北已經當天。
    assert summarize_income([entry(0, hour=0, minute=5)], NOW).today == 2


def test_net_annualization_includes_entire_wallet_and_variable_daily_capital():
    rows = [entry(day, capital=10000 if day < 3 else 20000) for day in range(7)]
    result = summarize_income(rows, NOW)
    assert result.seven_day_apy == pytest.approx(14 / 110000 * 36500)
    # 實收利息已扣費，不能再扣一次 15%。
    assert summarize_income([entry(day) for day in range(7)], NOW).seven_day_apy == pytest.approx(7.3)


def test_missing_days_or_capital_does_not_turn_into_zero_annualization():
    assert summarize_income([entry(day) for day in range(6)], NOW).seven_day_apy is None
    rows = [entry(day) for day in range(7)]
    rows[0].balance = rows[0].amount
    assert summarize_income(rows, NOW).seven_day_apy is None
    rows[0].balance = None
    assert summarize_income(rows, NOW).seven_day_apy is None


def test_zero_income_is_posted_and_split_payments_use_latest_wallet_balance():
    assert summarize_income([entry(0, amount=0)], NOW).today == 0
    rows = [entry(day) for day in range(1, 7)]
    rows += [entry(0, amount=1, eid=100), entry(0, amount=2, capital=10001, eid=101, minute=31)]
    result = summarize_income(rows + [rows[-1]], NOW)
    assert result.today == 3
    assert result.seven_day_apy == pytest.approx(15 / 70000 * 36500)


def report_engine():
    cfg = Config(env=Env(bfx_key="fake", bfx_secret="fake"), raw={
        "symbols": ["fUSD", "fUST"],
        "strategy": {"frr_pilot": {"long_term_max_amount": 2000,
                                    "long_term_max_amounts": {"fUST": 10000}}},
    })
    client = Mock(spec=BfxClient)
    client.funding_earnings.return_value = [entry(day) for day in range(7)]
    client.funding_wallet.side_effect = lambda cur: (10000, 200) if cur == "USD" else (20000, 1000)
    usd_long = Credit(1, "fUSD", 1000, 0, 120, 0)
    client.active_credits.side_effect = lambda sym: (
        [usd_long, Credit(2, sym, 8000, .0002, 2, 0)] if sym == "fUSD" else
        [Credit(3, sym, 10000, .0002, 120, 0), Credit(4, sym, 9000, .0002, 2, 0)])
    client.active_loans.side_effect = lambda sym: [usd_long] if sym == "fUSD" else []
    client.active_offers.side_effect = lambda sym: [Offer(1, sym, 0, 800, .0002, 2)] if sym == "fUSD" else []
    bot = Engine(cfg, client, Mock(), SimpleNamespace(commands={}, notify=Mock(return_value=True)))
    return bot


def test_compact_report_reads_fresh_income_positions_and_deduplicates_loans():
    bot = report_engine()
    text = bot._compact_daily_report(NOW)
    assert "USD：9,000／10,000（90%）" in text
    assert "USDT：19,000／20,000（95%）" in text
    assert "USD：1,000／2,000" in text
    assert "USDT：10,000／10,000" in text
    assert "USD 2.00｜USDT 2.00" in text
    assert "USD 7.3%｜USDT 7.3%" in text
    assert "子帳戶" not in text and "⚠" not in text and "30日MA" not in text
    assert len(text.splitlines()) == 15
    assert all(call.kwargs["start_mts"] == int(NOW.replace(hour=0).timestamp() * 1000) - 6 * 86400000
               for call in bot.client.funding_earnings.call_args_list)
    bot.store.select.assert_not_called()
    bot.tg.notify.assert_not_called()


@pytest.mark.parametrize("error", [BfxError("unavailable"), Timeout("connection timeout")])
def test_income_and_position_failures_are_distinct_from_zero(error):
    bot = report_engine()
    bot.client.funding_earnings.side_effect = [error, [entry(day) for day in range(7)]]
    bot.client.funding_wallet.side_effect = [error, (20000, 1000)]
    text = bot._compact_daily_report(NOW)
    assert "USD 查詢失敗｜USDT 2.00" in text
    assert "USD：查詢失敗" in text
    assert "USDT：19,000／20,000（95%）" in text


def test_formatter_marks_pending_income_and_empty_wallet_without_alert_block():
    text = format_daily_report(NOW, [CurrencyReport("USD", PostedIncome(None, None), 0, 0, 0, 2000)])
    assert "尚未入帳" in text and "資料不足" in text
    assert "0／0（—）" in text
    assert "⚠" not in text and "無需處理" not in text


def freeze_engine_clock(monkeypatch, current):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz)
    monkeypatch.setattr("lendbot.engine.datetime", Clock)
    monkeypatch.setattr("lendbot.engine.time.time", lambda: current[0].timestamp())


def test_daily_schedule_waits_until_ten_and_sends_once_after_success(monkeypatch):
    bot = report_engine()
    current = [NOW.replace(hour=9, minute=59)]
    freeze_engine_clock(monkeypatch, current)
    bot._compact_daily_report = Mock(return_value="compact daily report")
    bot._maybe_daily_report()
    bot.tg.notify.assert_not_called()
    current[0] = NOW
    bot._maybe_daily_report()
    bot._maybe_daily_report()
    bot.tg.notify.assert_called_once_with("compact daily report")
    assert bot.last_report_date == "2026-10-15"
    current[0] += timedelta(days=1)
    bot._maybe_daily_report()
    assert bot.tg.notify.call_count == 2


def test_delivery_failure_does_not_mark_sent_or_retry_every_cycle(monkeypatch):
    bot = report_engine()
    current = [NOW]
    freeze_engine_clock(monkeypatch, current)
    bot._compact_daily_report = Mock(return_value="compact daily report")
    bot.tg.notify.side_effect = [False, True]
    bot._maybe_daily_report()
    assert bot.last_report_date == ""
    current[0] += timedelta(minutes=2)
    bot._maybe_daily_report()
    assert bot.tg.notify.call_count == 1
    current[0] += timedelta(minutes=4)
    bot._maybe_daily_report()
    assert bot.tg.notify.call_count == 2
    assert bot.last_report_date == "2026-10-15"


def test_earnings_command_also_does_not_label_previous_deposit_as_today(monkeypatch):
    bot = report_engine()
    current = [NOW.replace(hour=9)]
    freeze_engine_clock(monkeypatch, current)
    assert "今日入帳 尚未入帳" in bot._earnings_summary()
    assert "USDT" in bot._earnings_summary()
    assert load_config().telegram["daily_report_hour"] == 10
