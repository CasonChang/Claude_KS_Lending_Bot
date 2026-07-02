"""入口：python -m lendbot [--once]

--once：只跑一個循環就結束（測試用）
"""
import socket
import sys
import threading

from .bfx_client import BfxClient
from .config import load_config
from .engine import Engine
from .logger import get_logger
from .store import Store
from .telegram_bot import TelegramBot

log = get_logger()

# 單一實例鎖：綁定本機 port，第二個實例會綁不到直接退出。
# （多實例同時跑會重複推播、重複寫 DB、互搶 Telegram 更新）
_LOCK_PORT = 47391


def acquire_single_instance_lock() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        log.error("偵測到已有 lendbot 在跑（port %d 被占用），本實例退出", _LOCK_PORT)
        sys.exit(1)


def main():
    lock = acquire_single_instance_lock()  # noqa: F841 程序存活期間持有
    cfg = load_config()
    client = BfxClient(cfg.env.bfx_key, cfg.env.bfx_secret)
    store = Store(cfg.env.supabase_url, cfg.env.supabase_key)
    tg = TelegramBot(cfg.env.tg_token, cfg.env.tg_chat_id)
    engine = Engine(cfg, client, store, tg)

    log.info("Supabase：%s｜Telegram：%s",
             "已連接" if store.enabled else "未設定",
             "已連接" if tg.enabled else "未設定")

    if "--once" in sys.argv:
        engine.run_cycle()
        log.info("單循環測試完成")
        return

    # 學習模式：唯讀側錄子帳戶（LEARNING_ENABLED=1 + MONITOR_BFX_KEY/SECRET）。
    # daemon thread、與主策略完全隔離；觀察者掛掉不影響正式循環。
    if cfg.env.learning_enabled:
        if cfg.env.has_monitor_auth:
            from .observer import LearningObserver
            observer = LearningObserver(cfg, store)
            threading.Thread(target=observer.run_forever, daemon=True,
                             name="learning-observer").start()
            tg.notify("🧪 學習模式已開啟：開始唯讀側錄子帳戶（不影響主策略）")
        else:
            log.warning("LEARNING_ENABLED 已開但缺 MONITOR_BFX_KEY/SECRET，觀察者未啟動")

    engine.run_forever()


if __name__ == "__main__":
    main()
