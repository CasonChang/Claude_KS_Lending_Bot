"""Supabase 寫入層：直接用 PostgREST API（不依賴 supabase-py，少一層依賴）。

沒設定 SUPABASE_URL/KEY 時全部變 no-op，本機純測試也能跑。
寫入失敗只記 log 不中斷主循環（DB 掛了不能影響放貸）。
"""
from __future__ import annotations

import requests

from .logger import get_logger

log = get_logger("store")
TIMEOUT = 10


class Store:
    def __init__(self, url: str = "", service_key: str = ""):
        self.enabled = bool(url and service_key)
        self.base = f"{url}/rest/v1" if url else ""
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, table: str, *, json=None, params=None,
                 extra_headers: dict | None = None) -> bool:
        if not self.enabled:
            return False
        headers = {**self.headers, **(extra_headers or {})}
        try:
            r = requests.request(method, f"{self.base}/{table}", headers=headers,
                                 json=json, params=params, timeout=TIMEOUT)
            if r.status_code >= 300:
                log.warning("supabase %s %s -> %s: %s", method, table,
                            r.status_code, r.text[:200])
                return False
            return True
        except requests.RequestException as e:
            log.warning("supabase %s %s 連線失敗: %s", method, table, e)
            return False

    def select(self, table: str, params: dict) -> list:
        """讀取（用 service key，繞過 RLS）。失敗回空 list 不中斷。"""
        if not self.enabled:
            return []
        try:
            r = requests.get(f"{self.base}/{table}", headers=self.headers,
                             params=params, timeout=TIMEOUT)
            if r.status_code >= 300:
                log.warning("supabase GET %s -> %s: %s", table, r.status_code, r.text[:200])
                return []
            return r.json()
        except requests.RequestException as e:
            log.warning("supabase GET %s 連線失敗: %s", table, e)
            return []

    def insert(self, table: str, row: dict) -> bool:
        return self._request("POST", table, json=row)

    def upsert(self, table: str, row: dict, on_conflict: str) -> bool:
        return self._request(
            "POST", table, json=row, params={"on_conflict": on_conflict},
            extra_headers={"Prefer": "resolution=merge-duplicates"})

    # ── 業務方法 ──

    def save_market_snapshot(self, symbol: str, view, ts_iso: str) -> bool:
        from .strategy import daily_to_apy
        return self.insert("market_snapshots", {
            "ts": ts_iso, "symbol": symbol,
            "frr": view.frr, "best_ask": view.best_ask,
            "depth_rate": view.depth_rate, "trade_iqm": view.trade_iqm,
            "recent_high": view.recent_high, "spike": view.spike,
            "anchor": view.anchor,
            "anchor_apy": round(daily_to_apy(view.anchor) * 100, 4),
        })

    def log_action(self, action: str, detail: dict, ts_iso: str) -> bool:
        return self.insert("actions_log", {"ts": ts_iso, "action": action, "detail": detail})

    def save_credits_snapshot(self, symbol: str, total: float, weighted_rate: float,
                              count: int, details: list, ts_iso: str) -> bool:
        from .strategy import daily_to_apy
        return self.insert("credits_snapshots", {
            "ts": ts_iso, "symbol": symbol, "total_lent": round(total, 2),
            "weighted_rate": weighted_rate,
            "weighted_apy": round(daily_to_apy(weighted_rate) * 100, 4) if weighted_rate else 0,
            "count": count, "details": details,
        })

    def save_earning(self, date_str: str, currency: str, amount: float,
                     balance: float | None = None) -> bool:
        row = {"date": date_str, "currency": currency, "amount": round(amount, 6)}
        if balance is not None:
            row["balance"] = round(balance, 2)
        return self.upsert("earnings", row, on_conflict="date,currency")

    def update_bot_status(self, symbol: str, status: dict) -> bool:
        return self.upsert("bot_status", {"symbol": symbol, **status}, on_conflict="symbol")

    def save_capital_flow(self, ledger_id: int, ts_iso: str, currency: str,
                          amount: float, kind: str, description: str) -> bool:
        """資金變動（入金/出金/兌換），以 Bitfinex ledger id 為主鍵去重。"""
        return self.upsert("capital_flows", {
            "id": ledger_id, "ts": ts_iso, "currency": currency,
            "amount": round(amount, 6), "kind": kind, "description": description,
        }, on_conflict="id")

    # ── 學習模式（子帳戶唯讀側錄，見 lendbot/observer.py）──

    def update_learning_status(self, symbol: str, status: dict) -> bool:
        """子帳戶現況單列 upsert（每次輪詢更新，網頁看最後觀測時間）。"""
        return self.upsert("learning_status", {"symbol": symbol, **status},
                           on_conflict="symbol")

    def save_learning_snapshot(self, row: dict) -> bool:
        return self.insert("learning_snapshots", row)

    def save_learning_event(self, ts_iso: str, event: str, symbol: str, *,
                            offer_id: int | None = None, amount: float | None = None,
                            rate: float | None = None, apy: float | None = None,
                            period: int | None = None, detail: dict | None = None) -> bool:
        return self.insert("learning_events", {
            "ts": ts_iso, "event": event, "symbol": symbol, "offer_id": offer_id,
            "amount": amount, "rate": rate, "apy": apy, "period": period,
            "detail": detail,
        })

    def save_learning_earning(self, date_str: str, currency: str, amount: float,
                              balance: float | None = None) -> bool:
        row = {"date": date_str, "currency": currency, "amount": round(amount, 6)}
        if balance is not None:
            row["balance"] = round(balance, 2)
        return self.upsert("learning_earnings", row, on_conflict="date,currency")

    def prune_old(self, days_snapshots: int = 30, days_actions: int = 90,
                  days_learning: int = 90) -> None:
        """清掉過舊資料，避免免費額度爆掉。"""
        from datetime import datetime, timedelta, timezone
        cut_snap = (datetime.now(timezone.utc) - timedelta(days=days_snapshots)).isoformat()
        cut_act = (datetime.now(timezone.utc) - timedelta(days=days_actions)).isoformat()
        cut_learn = (datetime.now(timezone.utc) - timedelta(days=days_learning)).isoformat()
        self._request("DELETE", "market_snapshots", params={"ts": f"lt.{cut_snap}"})
        self._request("DELETE", "credits_snapshots", params={"ts": f"lt.{cut_snap}"})
        self._request("DELETE", "actions_log", params={"ts": f"lt.{cut_act}"})
        # 學習表留 90 天（學習期 1 週～1 個月，留足回顧空間）
        self._request("DELETE", "learning_snapshots", params={"ts": f"lt.{cut_learn}"})
        self._request("DELETE", "learning_events", params={"ts": f"lt.{cut_learn}"})
