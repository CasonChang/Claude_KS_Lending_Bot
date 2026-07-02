"""設定載入：config.yaml（策略參數）+ .env（金鑰）。"""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Env:
    bfx_key: str = ""
    bfx_secret: str = ""
    dry_run: bool = True
    tg_token: str = ""
    tg_chat_id: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    # 學習模式：唯讀側錄子帳戶（交由外部專業策略操作），見 lendbot/observer.py
    learning_enabled: bool = False
    monitor_bfx_key: str = ""       # 子帳戶「唯讀」key（只開 Wallets/Funding/Ledgers 讀）
    monitor_bfx_secret: str = ""
    learning_symbol: str = "fUSD"
    learning_poll_seconds: int = 60
    learning_snapshot_minutes: int = 15

    @property
    def has_bfx_auth(self) -> bool:
        return bool(self.bfx_key and self.bfx_secret)

    @property
    def has_monitor_auth(self) -> bool:
        return bool(self.monitor_bfx_key and self.monitor_bfx_secret)

    @property
    def has_telegram(self) -> bool:
        return bool(self.tg_token and self.tg_chat_id)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


@dataclass
class Config:
    env: Env = field(default_factory=Env)
    raw: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        syms = self.raw.get("symbols")
        if not syms:  # 向後相容舊的單幣別設定
            syms = [self.raw.get("symbol", "fUSD")]
        return list(syms)

    @property
    def rebalance(self) -> dict:
        return self.raw.get("rebalance", {})

    @property
    def cycle_minutes(self) -> float:
        return float(self.raw.get("cycle_minutes", 5))

    @property
    def strategy(self) -> dict:
        return self.raw.get("strategy", {})

    @property
    def telegram(self) -> dict:
        return self.raw.get("telegram", {})

    @property
    def simulated_balance(self) -> float:
        return float(self.raw.get("dry_run", {}).get("simulated_balance", 1000))


def load_config(config_path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    path = config_path or ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    env = Env(
        bfx_key=os.getenv("BFX_API_KEY", "").strip(),
        bfx_secret=os.getenv("BFX_API_SECRET", "").strip(),
        dry_run=os.getenv("DRY_RUN", "true").strip().lower() != "false",
        tg_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        tg_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_key=os.getenv("SUPABASE_SERVICE_KEY", "").strip(),
        learning_enabled=os.getenv("LEARNING_ENABLED", "").strip().lower()
                         in ("1", "true", "yes"),
        monitor_bfx_key=os.getenv("MONITOR_BFX_KEY", "").strip(),
        monitor_bfx_secret=os.getenv("MONITOR_BFX_SECRET", "").strip(),
        learning_symbol=os.getenv("LEARNING_SYMBOL", "fUSD").strip() or "fUSD",
        learning_poll_seconds=int(os.getenv("LEARNING_POLL_SECONDS", "60") or 60),
        learning_snapshot_minutes=int(os.getenv("LEARNING_SNAPSHOT_MINUTES", "15") or 15),
    )
    return Config(env=env, raw=raw)
