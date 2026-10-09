"""設定指定聊天室的指令選單與底部鍵盤，不啟動 bot／getUpdates。

唯讀檢查：python tools/setup_telegram_menu.py --check
設定選單：python tools/setup_telegram_menu.py --apply
讀取系統 TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID；不讀取或寫入金鑰檔。
"""
from __future__ import annotations

import argparse
import os

import requests


COMMANDS = [
    {"command": "status", "description": "狀態、餘額、放貸上限"},
    {"command": "rates", "description": "目前市場利率與機器人錨點"},
    {"command": "earnings", "description": "收益總覽"},
    {"command": "review", "description": "昨日策略檢討"},
    {"command": "longcap", "description": "查詢 USD／USDT 的120天上限"},
    {"command": "capital", "description": "查詢並同步近期資金變動"},
    {"command": "learning", "description": "子帳戶最後觀測資料"},
    {"command": "pause", "description": "暫停自動掛單，既有部位保留"},
    {"command": "resume", "description": "恢復自動掛單"},
    {"command": "help", "description": "全部指令與參數說明"},
]
KEYBOARD = [["/status", "/rates"], ["/earnings", "/review"], ["/longcap", "/help"]]
KEYBOARD_MESSAGE = (
    "快捷選單已設定，可點下方按鍵查詢：\n"
    "/status 狀態、餘額、額度\n/rates 市場利率\n"
    "/earnings 收益\n/review 昨日檢討\n/longcap 120天額度\n/help 全部指令\n\n"
    "左側指令選單另有 /capital、/learning、/pause、/resume。"
)


class TelegramMenu:
    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise RuntimeError("缺少 TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID；請在環境設定安全提供")
        self.token = token
        self.chat_id = chat_id
        self.scope = {"type": "chat", "chat_id": chat_id}
        self.session = requests.Session()

    def call(self, method: str, payload: dict | None = None):
        try:
            response = self.session.post(
                f"https://api.telegram.org/bot{self.token}/{method}",
                json=payload or {}, timeout=20,
            )
        except requests.RequestException as error:
            # requests 的原始錯誤包含帶 token 的 URL，不能直接列印。
            raise RuntimeError(f"Telegram {method} 網路呼叫失敗（{type(error).__name__}）；請確認 api.telegram.org 存取") from None
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"Telegram {method} 回傳無效 JSON（HTTP {response.status_code}）") from None
        if not response.ok or not data.get("ok"):
            description = str(data.get("description", "request failed")).replace(self.token, "[redacted]")
            raise RuntimeError(f"Telegram {method} 失敗（HTTP {response.status_code}）：{description}")
        return data.get("result")

    def check(self) -> dict:
        bot = self.call("getMe")
        chat = self.call("getChat", {"chat_id": self.chat_id})
        commands = self.call("getMyCommands", {"scope": self.scope})
        return {"bot": bot.get("username"), "chat_type": chat.get("type"),
                "commands": commands}

    def apply(self) -> dict:
        current = self.check()
        if current["chat_type"] == "channel":
            raise RuntimeError("頻道不支援底部回覆鍵盤；請使用與 bot 的私人聊天室")
        names = {row["command"] for row in COMMANDS}
        # 只修改這個 chat 的選單，保留其他既有指令及其他聊天室設定。
        commands = COMMANDS + [row for row in current["commands"] if row["command"] not in names]
        if len(commands) > 100:
            raise RuntimeError("保留既有指令後超過 Telegram 100 個上限，尚未修改設定")
        self.call("setMyCommands", {"scope": self.scope, "commands": commands})
        if self.call("getMyCommands", {"scope": self.scope}) != commands:
            raise RuntimeError("指令選單回讀不一致，未發送底部鍵盤")
        if current["chat_type"] == "private":
            self.call("setChatMenuButton", {"chat_id": self.chat_id, "menu_button": {"type": "commands"}})
            menu = self.call("getChatMenuButton", {"chat_id": self.chat_id})
            if menu.get("type") != "commands":
                raise RuntimeError("指令選單按鈕回讀不一致，未發送底部鍵盤")
        message = self.call("sendMessage", {
            "chat_id": self.chat_id, "text": KEYBOARD_MESSAGE,
            "reply_markup": {
                "keyboard": [[{"text": text} for text in row] for row in KEYBOARD],
                "resize_keyboard": True, "is_persistent": True, "one_time_keyboard": False,
                "input_field_placeholder": "點選下方按鍵查詢",
            },
        })
        return {"bot": current["bot"], "chat_type": current["chat_type"],
                "command_count": len(commands), "keyboard_message_id": message.get("message_id")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只檢查 bot、chat 與既有選單")
    mode.add_argument("--apply", action="store_true", help="設定指定 chat 選單，並發送底部快捷鍵盤")
    args = parser.parse_args()
    try:
        menu = TelegramMenu(os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
                            os.getenv("TELEGRAM_CHAT_ID", "").strip())
        result = menu.apply() if args.apply else menu.check()
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")
    print("已設定" if args.apply else "檢查成功", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
