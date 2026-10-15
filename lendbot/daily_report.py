"""精簡日報的純資料轉換；不發送訊息、不下單。"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from .bfx_client import LedgerEntry

TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class PostedIncome:
    today: float | None  # None＝今天尚未有入帳紀錄；零額入帳仍是 0
    seven_day_apy: float | None


@dataclass(frozen=True)
class CurrencyReport:
    currency: str
    income: PostedIncome | None  # None＝查詢失敗
    wallet: float | None
    lent: float | None
    long_used: float | None
    long_cap: float | None


def summarize_income(entries: list[LedgerEntry], now: datetime) -> PostedIncome:
    """依台北入帳日彙整。7 日年化使用每日入帳前錢包本金，口徑與 Dashboard 相同。

    ledger 利息已扣費，不再乘 0.85；每日本金是快照近似，不能還原日內出入金時點。
    缺少任一天紀錄／本金時不硬算成零或拿前一日補上。
    """
    today = now.astimezone(TAIPEI).date()
    grouped: dict = {}
    for entry in sorted({e.id: e for e in entries}.values(), key=lambda e: e.mts):
        dt = datetime.fromtimestamp(entry.mts / 1000, TAIPEI)
        if dt > now:
            continue
        day = dt.date()
        amount, _ = grouped.get(day, (0.0, None))
        grouped[day] = (amount + entry.amount, entry.balance)
    posted = grouped[today][0] if today in grouped else None
    days = [today - timedelta(days=n) for n in range(7)]
    if any(day not in grouped for day in days):
        return PostedIncome(posted, None)
    amounts = [grouped[day][0] for day in days]
    capitals = [grouped[day][1] - grouped[day][0]
                if grouped[day][1] is not None else 0 for day in days]
    if any(not math.isfinite(v) or v <= 0 for v in capitals) or not all(map(math.isfinite, amounts)):
        return PostedIncome(posted, None)
    return PostedIncome(posted, sum(amounts) / sum(capitals) * 36500)


def format_daily_report(now: datetime, rows: list[CurrencyReport]) -> str:
    lines = [f"📊 放貸日報｜{now.astimezone(TAIPEI):%m/%d %H:%M}", "", "💰 今日入帳（已扣費）"]

    def income_text(row):
        if row.income is None:
            return "查詢失敗"
        return "尚未入帳" if row.income.today is None else f"{row.income.today:,.2f}"

    lines.append("｜".join(f"{row.currency} {income_text(row)}" for row in rows))
    lines += ["", "💼 放貸中／放貸錢包總額"]
    for row in rows:
        if row.wallet is None or row.lent is None:
            lines.append(f"{row.currency}：查詢失敗")
        else:
            utilization = f"{row.lent / row.wallet * 100:.0f}%" if row.wallet > 0 else "—"
            lines.append(f"{row.currency}：{row.lent:,.0f}／{row.wallet:,.0f}（{utilization}）")
    lines += ["", "📈 近7日實際年化"]
    lines.append("｜".join(
        f"{row.currency} " + ("查詢失敗" if row.income is None else
                              "資料不足" if row.income.seven_day_apy is None else
                              f"{row.income.seven_day_apy:.1f}%") for row in rows))
    lines += ["", "⏳ 120天額度（含掛單）"]
    for row in rows:
        if row.long_used is None or row.long_cap is None:
            lines.append(f"{row.currency}：查詢失敗")
        else:
            lines.append(f"{row.currency}：{row.long_used:,.0f}／{row.long_cap:,.0f}")
    return "\n".join(lines)
