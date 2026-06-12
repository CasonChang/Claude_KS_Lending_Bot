"""即時對比 USD/UST：深度、IQM、近 7 / 30 日 MA。
用法：python research/depth_compare.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.bfx_client import BfxClient
from lendbot.strategy import daily_to_apy, iqm

client = BfxClient()
for sym in ("fUSD", "fUST"):
    book = client.funding_book(sym, length=100)
    time.sleep(1)
    trades = client.funding_trades(sym, limit=120)
    time.sleep(1)
    candles = client.funding_candles(sym, tf="1D", limit=30, sort=-1)
    time.sleep(1)

    asks = sum(e.amount for e in book if e.amount > 0)
    bids = sum(-e.amount for e in book if e.amount < 0)
    cur_iqm = iqm([t.rate for t in trades])
    closes = [c["close"] for c in candles]
    ma7 = sum(closes[:7]) / 7
    ma30 = sum(closes) / len(closes)
    span_min = (trades[0].mts - trades[-1].mts) / 60000

    print(f"{sym}：放貸方深度 ${asks:,.0f}｜借款方深度 ${bids:,.0f}")
    print(f"   現在 IQM {daily_to_apy(cur_iqm)*100:.2f}%（近 120 筆 ≈ {span_min:.0f} 分鐘）"
          f"｜7日MA {daily_to_apy(ma7)*100:.2f}%｜30日MA {daily_to_apy(ma30)*100:.2f}%")
