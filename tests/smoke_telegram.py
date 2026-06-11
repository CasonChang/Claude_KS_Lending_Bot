"""手動測試：發一則 Telegram 測試訊息。
用法：python tests/smoke_telegram.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lendbot.config import load_config
from lendbot.telegram_bot import TelegramBot

cfg = load_config()
tg = TelegramBot(cfg.env.tg_token, cfg.env.tg_chat_id)
if not tg.enabled:
    print("❌ .env 沒有 Telegram 設定")
    sys.exit(1)

ok = tg.notify("✅ 放貸機器人連線測試成功！\n你會在這裡收到成交、利率飆漲、每日收益通知。")
print("已送出，請看手機 Telegram。" if ok else "❌ 送出失敗，請檢查 token / chat_id，並確認你已經先跟 bot 傳過訊息。")
