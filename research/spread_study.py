"""USD vs UST 放貸利差研究：用 3 年歷史 1D K 線回測「何時切換幣別」。

回測規則（每天收盤決策一次）：
  - 計算兩幣別日利率的 N 日移動平均（MA）
  - 若「對方 MA 年化 - 目前持有 MA 年化」連續 confirm_days 天都 > diff 門檻 → 切換
  - 每次切換扣 cost（USD↔UST 透過 tUSTUSD 交易的費用+滑價，預設 0.2%）

基準：全程持有 USD、全程持有 UST、每天事後諸葛選較高者（理論上限）。
用法：python research/spread_study.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.bfx_client import BfxClient
from lendbot.strategy import daily_to_apy

YEARS = 3
COST = 0.002  # 單次切換成本 0.2%（交易費 + 滑價，保守估）


def fetch_series(client: BfxClient, sym: str) -> dict[int, float]:
    """日期(mts) -> 當日收盤日利率"""
    start = int((time.time() - YEARS * 365 * 86400) * 1000)
    candles = client.funding_candles(sym, tf="1D", limit=1100, start_mts=start, sort=1)
    return {c["mts"]: c["close"] for c in candles}


def aligned(a: dict, b: dict) -> list[tuple[int, float, float]]:
    days = sorted(set(a) & set(b))
    return [(d, a[d], b[d]) for d in days]


def ma(series: list[float], i: int, n: int) -> float:
    lo = max(0, i - n + 1)
    window = series[lo:i + 1]
    return sum(window) / len(window)


def backtest_switch(rows, ma_days: int, diff_apy: float, confirm_days: int,
                    cost: float = COST) -> tuple[float, int]:
    """回傳（總報酬倍數, 切換次數）。rows = [(mts, r_usd, r_ust)]"""
    usd = [r[1] for r in rows]
    ust = [r[2] for r in rows]
    holding = 0  # 0=USD, 1=UST
    value = 1.0
    streak = 0
    switches = 0
    for i in range(len(rows)):
        # 先收今天的利息（用昨天決定的持倉）
        value *= 1 + (ust[i] if holding else usd[i])
        # 收盤後決策
        my_ma = ma(ust if holding else usd, i, ma_days)
        other_ma = ma(usd if holding else ust, i, ma_days)
        diff = (daily_to_apy(other_ma) - daily_to_apy(my_ma)) * 100
        streak = streak + 1 if diff > diff_apy else 0
        if streak >= confirm_days:
            holding = 1 - holding
            value *= 1 - cost
            switches += 1
            streak = 0
    return value, switches


def main():
    client = BfxClient()
    print("抓取歷史資料中…")
    usd = fetch_series(client, "fUSD")
    ust = fetch_series(client, "fUST")
    rows = aligned(usd, ust)
    n_days = len(rows)
    print(f"對齊後共 {n_days} 天（約 {n_days / 365:.1f} 年）\n")

    def apy_of(mult: float) -> float:
        return (mult ** (365 / n_days) - 1) * 100

    # 基準
    hold_usd = 1.0
    hold_ust = 1.0
    oracle = 1.0
    half = 1.0
    for _, ru, rt in rows:
        hold_usd *= 1 + ru
        hold_ust *= 1 + rt
        oracle *= 1 + max(ru, rt)
        half *= 1 + (ru + rt) / 2
    print(f"{'基準':<28}{'年化':>8}")
    print(f"{'全程 USD':<28}{apy_of(hold_usd):>7.2f}%")
    print(f"{'全程 UST':<28}{apy_of(hold_ust):>7.2f}%")
    print(f"{'50/50 各半':<28}{apy_of(half):>7.2f}%")
    print(f"{'每日事後諸葛（理論上限）':<28}{apy_of(oracle):>7.2f}%\n")

    # 參數網格
    results = []
    for ma_days in (3, 7, 14, 30):
        for diff_apy in (0.5, 1.0, 2.0, 3.0):
            for confirm in (1, 3, 7, 14):
                mult, switches = backtest_switch(rows, ma_days, diff_apy, confirm)
                results.append((apy_of(mult), switches, ma_days, diff_apy, confirm))
    results.sort(reverse=True)

    print(f"{'年化':>7} {'切換次數':>6} {'MA天數':>6} {'利差門檻':>7} {'確認天數':>6}")
    for apy, sw, m, d, c in results[:15]:
        print(f"{apy:>6.2f}% {sw:>6} {m:>6} {d:>6.1f}% {c:>6}")
    print("\n（完整結果共", len(results), "組）")

    # 也輸出最差 5 組對照
    print("\n最差 5 組（避免踩到的參數）：")
    for apy, sw, m, d, c in results[-5:]:
        print(f"{apy:>6.2f}% {sw:>6} {m:>6} {d:>6.1f}% {c:>6}")


if __name__ == "__main__":
    main()
