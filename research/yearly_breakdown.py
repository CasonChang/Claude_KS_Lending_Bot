"""逐年分解 USD vs UST 放貸表現 + 目前 30 日 MA 利差。
用法：python research/yearly_breakdown.py
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.bfx_client import BfxClient
from lendbot.strategy import daily_to_apy

client = BfxClient()
start = int((time.time() - 3 * 365 * 86400) * 1000)
usd = {c["mts"]: c["close"] for c in client.funding_candles("fUSD", "1D", 1100, start)}
ust = {c["mts"]: c["close"] for c in client.funding_candles("fUST", "1D", 1100, start)}
days = sorted(set(usd) & set(ust))

by_year: dict[int, list[tuple[float, float]]] = {}
for d in days:
    y = datetime.fromtimestamp(d / 1000, timezone.utc).year
    by_year.setdefault(y, []).append((usd[d], ust[d]))

print(f"{'年份':<6}{'USD年化':>9}{'UST年化':>9}{'UST勝率':>9}{'天數':>6}")
for y in sorted(by_year):
    rows = by_year[y]
    mu = 1.0
    mt = 1.0
    win = 0
    for ru, rt in rows:
        mu *= 1 + ru
        mt *= 1 + rt
        win += rt > ru
    n = len(rows)
    apy_u = (mu ** (365 / n) - 1) * 100
    apy_t = (mt ** (365 / n) - 1) * 100
    print(f"{y:<6}{apy_u:>8.2f}%{apy_t:>8.2f}%{win / n * 100:>8.1f}%{n:>6}")

# 目前 30 日 MA 利差
last30 = days[-30:]
ma_u = sum(usd[d] for d in last30) / len(last30)
ma_t = sum(ust[d] for d in last30) / len(last30)
print(f"\n目前 30 日 MA：USD {daily_to_apy(ma_u)*100:.2f}% vs UST {daily_to_apy(ma_t)*100:.2f}%"
      f"（利差 {abs(daily_to_apy(ma_t)-daily_to_apy(ma_u))*100:.2f} 個百分點）")
