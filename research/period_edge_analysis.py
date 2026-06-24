"""一次性分析（唯讀）：診斷 fUSD 績效落後是 (a)沒掛長單 (b)掛了不成交 (c)成交被早還。

絕不下單/撤單，不啟動引擎。只讀公開 API + Bitfinex 唯讀私有 API + Supabase。
用法：python research/period_edge_analysis.py
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from lendbot.bfx_client import BfxClient
from lendbot.config import load_config
from lendbot.strategy import daily_to_apy

SYM = "fUSD"
NOW = int(time.time() * 1000)
DAY = 86_400_000


def bucket_period(p: int) -> str:
    if p <= 2:
        return "2天"
    if p <= 7:
        return "3-7天"
    if p <= 30:
        return "8-30天"
    return "31-120天"


def apy(r: float) -> float:
    return daily_to_apy(r) * 100


def fetch_market_trades(client: BfxClient, pages: int = 8, per: int = 2000) -> list:
    """分頁往回撈公開成交（trades/hist）。fUSD 量極大，撈最近 pages×per 筆當代表樣本，
    避免 limit 過大被限流；回傳實際涵蓋多久由呼叫端報告。"""
    end = NOW
    out = []
    for i in range(pages):
        d = client._get_public(f"trades/{SYM}/hist",
                               {"limit": per, "end": end, "sort": -1})
        if not d:
            break
        out.extend(d)  # [ID, MTS, AMOUNT, RATE, PERIOD]
        oldest = min(t[1] for t in d)
        if len(d) < per:
            break
        end = oldest - 1
        time.sleep(2.5)  # 放慢避免限流
    return out


def main():
    cfg = load_config()
    client = BfxClient(cfg.env.bfx_key, cfg.env.bfx_secret)

    print("=" * 70)
    print("分析一：市場端（公開 API）—— fUSD 成交的天期分布與 spike 行為")
    print("=" * 70)
    try:
        trades = fetch_market_trades(client)
    except Exception as e:
        print(f"！市場成交抓取失敗（限流？）：{e}\n  跳過分析一，繼續帳戶端分析")
        trades = []
    if not trades:
        print("！沒撈到成交資料，跳過分析一")
        return _account_side(client)
    span_h = (max(t[1] for t in trades) - min(t[1] for t in trades)) / 3_600_000
    print(f"樣本：{len(trades):,} 筆成交，涵蓋約 {span_h/24:.1f} 天 "
          f"（{datetime.fromtimestamp(min(t[1] for t in trades)/1000, timezone.utc):%m/%d} ~ "
          f"{datetime.fromtimestamp(max(t[1] for t in trades)/1000, timezone.utc):%m/%d} UTC）")

    # 成交量以 |amount| 計（funding trades amount 有正負，取絕對值）
    by_bucket = defaultdict(lambda: [0, 0.0, 0.0])  # bucket -> [筆數, 量, 量×rate]
    total_vol = 0.0
    for _id, mts, amount, rate, period in trades:
        v = abs(amount)
        b = bucket_period(int(period))
        by_bucket[b][0] += 1
        by_bucket[b][1] += v
        by_bucket[b][2] += v * rate
        total_vol += v
    print(f"\n【1】全體成交依天期分桶（量占比 / 平均年化）：")
    print(f"{'天期':<10}{'筆數':>9}{'量(USD)':>16}{'量占比':>9}{'平均年化':>10}")
    for b in ["2天", "3-7天", "8-30天", "31-120天"]:
        cnt, vol, vr = by_bucket[b]
        if cnt:
            print(f"{b:<10}{cnt:>9,}{vol:>16,.0f}{vol/total_vol*100:>8.1f}%{apy(vr/vol):>9.1f}%")

    # spike 分析：找「利率前 10% 的成交」，看它們主要是什麼天期
    rates = sorted(t[3] for t in trades)
    p90 = rates[int(len(rates) * 0.90)]
    print(f"\n【2】高利率成交（利率前 10%，門檻 = {apy(p90):.1f}% 年化以上）的天期分布：")
    spike_bucket = defaultdict(lambda: [0, 0.0])
    spike_vol = 0.0
    for _id, mts, amount, rate, period in trades:
        if rate >= p90:
            v = abs(amount)
            spike_bucket[bucket_period(int(period))][0] += 1
            spike_bucket[bucket_period(int(period))][1] += v
            spike_vol += v
    print(f"{'天期':<10}{'筆數':>9}{'量(USD)':>16}{'量占比':>9}")
    for b in ["2天", "3-7天", "8-30天", "31-120天"]:
        cnt, vol = spike_bucket[b]
        if cnt:
            print(f"{b:<10}{cnt:>9,}{vol:>16,.0f}{vol/spike_vol*100:>8.1f}%")
    long_share = (spike_bucket["8-30天"][1] + spike_bucket["31-120天"][1]) / spike_vol * 100
    print(f"  → 高利率時段，>=8天 長單占量 {long_share:.1f}%"
          f"（驗證『spike 時市場有人用長天期鎖高利』假設）")

    return _account_side(client)


def _account_side(client: BfxClient):
    print("\n" + "=" * 70)
    print("分析二：我們自己（Bitfinex 唯讀私有 API）")
    print("=" * 70)

    # 我們目前掛單的天期
    offers = client.active_offers(SYM)
    print(f"\n【3】我們『目前掛單』天期分布（{len(offers)} 筆）：")
    if offers:
        ob = defaultdict(lambda: [0, 0.0, 0.0])
        for o in offers:
            ob[bucket_period(o.period)][0] += 1
            ob[bucket_period(o.period)][1] += o.amount
            ob[bucket_period(o.period)][2] += o.amount * o.rate
        for b in ["2天", "3-7天", "8-30天", "31-120天"]:
            cnt, vol, vr = ob[b]
            if cnt:
                print(f"  {b:<10} {cnt} 筆｜${vol:,.0f}｜年化 {apy(vr/vol):.1f}%")
    else:
        print("  （目前無掛單）")

    # 我們目前放貸中（已成交）的天期
    creds = client.active_credits(SYM)
    print(f"\n【4】我們『目前放貸中（已成交）』天期分布（{len(creds)} 筆）：")
    if creds:
        cb = defaultdict(lambda: [0, 0.0, 0.0])
        for c in creds:
            cb[bucket_period(c.period)][0] += 1
            cb[bucket_period(c.period)][1] += c.amount
            cb[bucket_period(c.period)][2] += c.amount * c.rate
        for b in ["2天", "3-7天", "8-30天", "31-120天"]:
            cnt, vol, vr = cb[b]
            if cnt:
                print(f"  {b:<10} {cnt} 筆｜${vol:,.0f}｜年化 {apy(vr/vol):.1f}%")

    # 已結束的單：依「掛單天期」分桶，看實際放滿比例
    hist = client.credits_history(SYM, limit=500)
    print(f"\n【5】我們『已結束放貸』依天期看實際放滿比例（{len(hist)} 筆）：")
    if hist:
        hb = defaultdict(lambda: {"n": 0, "vol": 0.0, "held_pct": [], "vr": 0.0})
        for h in hist:
            if not h.mts_close or not h.period:
                continue
            held_days = (h.mts_close - h.mts_opening) / DAY
            pct = held_days / h.period * 100
            d = hb[bucket_period(h.period)]
            d["n"] += 1
            d["vol"] += h.amount
            d["vr"] += h.amount * h.rate
            d["held_pct"].append(pct)
        print(f"{'掛單天期':<10}{'筆數':>7}{'量(USD)':>14}{'平均年化':>10}{'平均放滿%':>11}{'早還率':>9}")
        for b in ["2天", "3-7天", "8-30天", "31-120天"]:
            d = hb[b]
            if d["n"]:
                avg_held = sum(d["held_pct"]) / len(d["held_pct"])
                early = sum(1 for p in d["held_pct"] if p < 90) / d["n"] * 100
                print(f"{b:<10}{d['n']:>7}{d['vol']:>14,.0f}{apy(d['vr']/d['vol']):>9.1f}%"
                      f"{avg_held:>10.0f}%{early:>8.0f}%")

    print("\n完成。")


if __name__ == "__main__":
    main()
