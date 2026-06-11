"""手動測試：用 .env 的真實 key 讀 Bitfinex 帳戶（不下單）。
用法：python tests/smoke_auth.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.bfx_client import BfxClient
from lendbot.config import load_config
from lendbot.strategy import daily_to_apy

cfg = load_config()
if not cfg.env.has_bfx_auth:
    print("❌ .env 沒有 Bitfinex key")
    sys.exit(1)

c = BfxClient(cfg.env.bfx_key, cfg.env.bfx_secret)
cur = cfg.currency

print("== 測試讀取帳戶（驗證 key 與權限）==")
avail = c.funding_available(cur)
print(f"✅ Funding 錢包可用 {cur}：{avail:,.2f}")

offers = c.active_offers(cfg.symbol)
print(f"✅ 目前掛單：{len(offers)} 筆")
for o in offers:
    print(f"   {o.amount:,.2f} @ {daily_to_apy(o.rate)*100:.2f}% / {o.period}天")

credits = c.active_credits(cfg.symbol)
total = sum(x.amount for x in credits)
print(f"✅ 放貸中：{len(credits)} 筆，共 {total:,.2f} {cur}")

earn = c.funding_earnings(cur, limit=10)
print(f"✅ 最近利息紀錄：{len(earn)} 筆")
for e in earn[:5]:
    print(f"   +{e.amount:.6f} {cur}")

print("\n全部讀取成功，key 與權限正確。")
