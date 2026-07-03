"""學習觀察者：唯讀側錄「子帳戶」（交由外部專業放貸策略操作）。

目的：把子帳戶的掛單/放貸/收益完整側錄進 Supabase learning_* 表，
與主帳戶（我們的正式策略）並列比較，做為每日學習檢討的資料來源。

安全紅線（沿用專案慣例）：
- 只呼叫「讀取」API：active_offers / active_credits / funding_wallet /
  credits_history / funding_earnings ＋ 公開市場數據。
  本模組程式路徑完全不含 submit/cancel —— 不可能對子帳戶下單。
- 用獨立的唯讀 key（MONITOR_BFX_KEY/SECRET，只開 Wallets/Funding/Ledgers 讀）。
- 與主策略 Engine 完全隔離：daemon thread、自己的 BfxClient，任何例外
  只記 log 並退避重試，絕不影響正式循環。

輪詢設計（子帳戶的掛單頻率未知 → 高頻輪詢＋差異偵測，不會灌爆 DB）：
- 每 LEARNING_POLL_SECONDS（預設 60s）拉一次現況，跟上一輪比對，
  只有「變動」才寫 learning_events：
    offer_new           新掛單出現
    offer_canceled      掛單消失、且沒有對應的新放貸 → 判定撤單
    offer_filled        掛單消失、同利率的新放貸出現 → 判定成交
    offer_partial_fill  掛單金額變小（部分成交）
    credit_new          新放貸出現（成交）
    credit_closed       放貸消失（還款/到期；含 credits_history 盲區回補）
  撤單＋新掛在同一輪出現時，事後分析即可推斷為「調單」。
- 每次輪詢 upsert learning_status（單列現況，網頁顯示「最後觀測時間」）。
- 每 LEARNING_SNAPSHOT_MINUTES（預設 15 分）寫一筆 learning_snapshots
  完整快照，含市場 view 與「影子決策」：用我們 config.yaml 的策略純函式
  對子帳戶同一刻的可用餘額算出「我們會掛什麼」（純計算、絕不下單）。
- 每小時從 ledger 同步每日利息 → learning_earnings。
  日期用 UTC+8 標（與主帳戶 earnings 同慣例）；Bitfinex 利息固定在
  00:00 UTC＝台北 08:00 入帳，UTC 日與台北日兩種標法在此落在同一天。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .bfx_client import BfxClient, BfxError, Credit, Offer
from .config import Config
from .logger import get_logger
from .store import Store
from .strategy import analyze_market, build_ladder, daily_to_apy

log = get_logger("observer")
TZ = timezone(timedelta(hours=8))  # 與 engine 的收益日期慣例一致


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apy(rate: float) -> float:
    return round(daily_to_apy(rate) * 100, 2)


def diff_events(prev_offers: dict[int, Offer], cur_offers: dict[int, Offer],
                prev_credits: dict[int, Credit], cur_credits: dict[int, Credit],
                now_mts: int) -> list[dict]:
    """兩輪快照的差異 → 事件清單（純函式，方便單元測試）。

    掛單消失的成交/撤單判定：本輪新出現的放貸中，若有「同利率、同天期、
    金額不大於掛單」的，視為該掛單成交；否則視為撤單。
    """
    events: list[dict] = []
    new_credit_pool = [cur_credits[cid] for cid in cur_credits.keys() - prev_credits.keys()]

    # 掛單：新增
    for oid in sorted(cur_offers.keys() - prev_offers.keys()):
        o = cur_offers[oid]
        events.append({"event": "offer_new", "offer_id": o.id, "amount": o.amount,
                       "rate": o.rate, "apy": _apy(o.rate), "period": o.period,
                       "detail": None})

    # 掛單：消失（成交 or 撤單）
    matched: set[int] = set()
    for oid in sorted(prev_offers.keys() - cur_offers.keys()):
        o = prev_offers[oid]
        fill = next((c for c in new_credit_pool
                     if c.id not in matched
                     and abs(c.rate - o.rate) < 1e-9 and c.period == o.period
                     and c.amount <= o.amount * 1.01), None)
        if fill is not None:
            matched.add(fill.id)
            events.append({"event": "offer_filled", "offer_id": o.id,
                           "amount": fill.amount, "rate": o.rate, "apy": _apy(o.rate),
                           "period": o.period, "detail": {"credit_id": fill.id}})
        else:
            events.append({"event": "offer_canceled", "offer_id": o.id,
                           "amount": o.amount, "rate": o.rate, "apy": _apy(o.rate),
                           "period": o.period, "detail": None})

    # 掛單：金額變小 = 部分成交
    for oid in sorted(cur_offers.keys() & prev_offers.keys()):
        prev_o, cur_o = prev_offers[oid], cur_offers[oid]
        if cur_o.amount < prev_o.amount - 0.01:
            events.append({"event": "offer_partial_fill", "offer_id": oid,
                           "amount": round(prev_o.amount - cur_o.amount, 2),
                           "rate": cur_o.rate, "apy": _apy(cur_o.rate),
                           "period": cur_o.period,
                           "detail": {"from": prev_o.amount, "to": cur_o.amount}})

    # 放貸：新增（成交）。已由上面 offer_filled 記到的成交（matched）不再重複記，
    # 同一筆成交只留一則事件。credit_new 只剩「沒對應到消失掛單」的情況——
    # 也就是掛單在兩次輪詢之間「掛出又秒成交」、我們沒捕捉到 offer 的快速成交。
    for cid in sorted(cur_credits.keys() - prev_credits.keys()):
        if cid in matched:
            continue
        c = cur_credits[cid]
        events.append({"event": "credit_new", "offer_id": c.id, "amount": c.amount,
                       "rate": c.rate, "apy": _apy(c.rate), "period": c.period,
                       "detail": {"fast_fill": True}})

    # 放貸：消失（還款/到期）
    for cid in sorted(prev_credits.keys() - cur_credits.keys()):
        c = prev_credits[cid]
        held_days = max(0.0, (now_mts - c.mts_opening) / 86_400_000)
        events.append({"event": "credit_closed", "offer_id": c.id, "amount": c.amount,
                       "rate": c.rate, "apy": _apy(c.rate), "period": c.period,
                       "detail": {"held_days": round(held_days, 2),
                                  "matured": held_days >= c.period * 0.98}})
    return events


class LearningObserver:
    """唯讀觀察迴圈。由 __main__ 以 daemon thread 啟動（LEARNING_ENABLED=1）。"""

    def __init__(self, cfg: Config, store: Store):
        self.cfg = cfg
        self.scfg = cfg.strategy
        self.store = store
        self.client = BfxClient(cfg.env.monitor_bfx_key, cfg.env.monitor_bfx_secret)
        self.symbol = cfg.env.learning_symbol
        self.currency = self.symbol[1:]
        self.poll_seconds = max(15, int(cfg.env.learning_poll_seconds))
        self.snapshot_seconds = max(60, int(cfg.env.learning_snapshot_minutes) * 60)

        self.prev_offers: dict[int, Offer] = {}
        self.prev_credits: dict[int, Credit] = {}
        self.first_poll = True
        self.processed_closed: set[int] = set()
        self.first_hist_sync = True
        self.last_snapshot = 0.0
        self.last_earnings_sync = 0.0
        self.errors_in_row = 0

    # ── 主迴圈 ──────────────────────────────────────────────

    def _seed_processed_closed(self):
        """從 DB 載入近 3 天已記錄過的結束單 id，避免重啟（Zeabur redeploy）後
        in-memory 去重集合被清空、backfill 把同一筆結束重複記進 learning_events。"""
        cut = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        rows = self.store.select("learning_events", {
            "select": "offer_id", "event": "eq.credit_closed",
            "ts": f"gte.{cut}", "limit": "10000"})
        ids = {r["offer_id"] for r in rows if r.get("offer_id") is not None}
        self.processed_closed.update(ids)
        if ids:
            log.info("學習觀察者：從 DB 載入 %d 筆已記錄結束單（防重複）", len(ids))

    def run_forever(self):
        log.info("學習觀察者啟動（唯讀）：%s｜輪詢 %ds｜快照 %d 分",
                 self.symbol, self.poll_seconds, self.snapshot_seconds // 60)
        try:
            self._seed_processed_closed()
        except Exception:
            log.exception("學習觀察者：載入已記錄結束單失敗（不影響後續）")
        while True:
            try:
                self.poll_once()
                self.errors_in_row = 0
                sleep = self.poll_seconds
            except Exception:
                self.errors_in_row += 1
                log.exception("學習觀察者輪詢失敗（連續 %d 次）", self.errors_in_row)
                # 指數退避（上限 15 分鐘），API 出問題時別狂打
                sleep = min(self.poll_seconds * 2 ** min(self.errors_in_row, 4), 900)
            time.sleep(sleep)

    def poll_once(self):
        now_mts = int(time.time() * 1000)
        ts = now_iso()

        offers = self.client.active_offers(self.symbol)
        credits = self.client.active_credits(self.symbol)
        wallet_total, available = self.client.funding_wallet(self.currency)

        cur_offers = {o.id: o for o in offers}
        cur_credits = {c.id: c for c in credits}

        # 差異事件（第一輪只建基準）
        if not self.first_poll:
            for ev in diff_events(self.prev_offers, cur_offers,
                                  self.prev_credits, cur_credits, now_mts):
                if ev["event"] == "credit_closed":
                    self.processed_closed.add(ev["offer_id"])
                self.store.save_learning_event(ts, ev["event"], self.symbol,
                                               offer_id=ev["offer_id"],
                                               amount=ev["amount"], rate=ev["rate"],
                                               apy=ev["apy"], period=ev["period"],
                                               detail=ev["detail"])
        self.prev_offers, self.prev_credits = cur_offers, cur_credits
        self.first_poll = False

        # 盲區回補：兩輪之間成交又秒還的單，用結束歷史撈回來
        self._reconcile_closed_history(ts)

        # 快照（含市場 view + 影子決策）或輕量現況更新
        market = shadow = None
        if time.time() - self.last_snapshot >= self.snapshot_seconds:
            self.last_snapshot = time.time()
            # 影子決策的本金＝子帳戶「可重新配置」的資金＝可用 ＋ 掛單中（尚未成交、
            # 隨時能撤換的錢）。放貸中的本金已鎖住、不能收回，故不計入。
            # 若只用 available，對方把錢全掛在單上時 available=0，我們就永遠算不出影子單。
            offers_total = sum(o.amount for o in offers)
            market, shadow = self._market_and_shadow(available + offers_total, now_mts)
        self._write_status(ts, offers, credits, wallet_total, available,
                           market, shadow,
                           snapshot=market is not None)

        # 每日利息（每小時同步一次就夠：利息一天只入帳一次）
        if time.time() - self.last_earnings_sync > 3600:
            self._sync_earnings()

    # ── 各步驟 ──────────────────────────────────────────────

    def _reconcile_closed_history(self, ts: str):
        try:
            hist = self.client.credits_history(self.symbol, limit=25)
        except BfxError as e:
            log.warning("子帳戶結束歷史查詢失敗: %s", e)
            return
        if self.first_hist_sync:  # 啟動時把既有歷史標為已處理
            self.processed_closed.update(h.id for h in hist)
            self.first_hist_sync = False
            return
        for h in hist:
            if h.id in self.processed_closed:
                continue
            self.processed_closed.add(h.id)
            # 歷史有時缺結束時間戳（mts_close=0）→ 無法算持有天數，記 None 而不是誤報 0 天
            has_close = h.mts_close > 0 and h.mts_close >= h.mts_opening
            held_days = round((h.mts_close - h.mts_opening) / 86_400_000, 2) if has_close else None
            self.store.save_learning_event(ts, "credit_closed", self.symbol,
                                           offer_id=h.id, amount=h.amount,
                                           rate=h.rate, apy=_apy(h.rate),
                                           period=h.period,
                                           detail={"held_days": held_days,
                                                   "matured": (held_days is not None
                                                               and held_days >= h.period * 0.98),
                                                   "backfill": True})

    def _market_and_shadow(self, shadow_capital: float, now_mts: int):
        """市場 view ＋ 我們策略的影子決策（純計算，一張單都不會送出）。

        shadow_capital＝子帳戶可重新配置的資金（可用＋掛單中），不含已鎖的放貸中本金。
        """
        ticker = self.client.funding_ticker(self.symbol)
        book = self.client.funding_book(self.symbol, length=100)
        trades = self.client.funding_trades(
            self.symbol, limit=int(self.scfg.get("trades_lookback", 120)))
        closes: list[float] = []
        floor_hours = int(self.scfg.get("floor_hours", 24))
        if floor_hours > 0:
            try:
                closes = [c["close"] for c in
                          self.client.funding_candles(self.symbol, tf="1h",
                                                      limit=floor_hours, sort=-1)]
            except BfxError as e:
                log.warning("子帳戶快照抓 1h K 失敗（保底略過）: %s", e)
        view = analyze_market(ticker, book, trades, self.scfg, now_mts,
                              recent_closes=closes)
        market = {
            "anchor_apy": _apy(view.anchor), "frr_apy": _apy(view.frr),
            "iqm_apy": _apy(view.trade_iqm), "best_ask_apy": _apy(view.best_ask),
            "floor_apy": _apy(view.rate_floor), "spike": view.spike,
            "snap_ts": now_iso(),  # 影子/市場的計算時間（每 15 分隨快照更新）
        }
        shadow = [{"amount": p.amount, "rate": p.rate,
                   "apy": round(p.apy_pct, 2), "period": p.period}
                  for p in build_ladder(shadow_capital, view, self.scfg)]
        return market, shadow

    def _write_status(self, ts: str, offers: list[Offer], credits: list[Credit],
                      wallet_total: float, available: float,
                      market: dict | None, shadow: list | None, snapshot: bool):
        total = sum(c.amount for c in credits)
        wrate = (sum(c.amount * c.rate for c in credits) / total) if total else 0.0
        row = {
            "ts": ts,
            "wallet_total": round(wallet_total, 2),
            "available": round(available, 2),
            "lent_total": round(total, 2),
            "lent_count": len(credits),
            "offers_count": len(offers),
            "weighted_apy": round(daily_to_apy(wrate) * 100, 2) if wrate else 0,
            "offers": [{
                "id": o.id, "amount": o.amount, "rate": o.rate,
                "apy": _apy(o.rate), "period": o.period,
                "created": datetime.fromtimestamp(o.mts_created / 1000,
                                                  timezone.utc).isoformat(),
            } for o in sorted(offers, key=lambda x: x.rate)],
            "credits": [{
                "id": c.id, "amount": c.amount, "rate": c.rate,
                "apy": _apy(c.rate), "period": c.period,
                "opened": datetime.fromtimestamp(c.mts_opening / 1000,
                                                 timezone.utc).isoformat(),
            } for c in sorted(credits, key=lambda x: -x.amount)],
        }
        if market is not None:
            row["market"] = market
            row["shadow"] = shadow
        self.store.update_learning_status(self.symbol, row)
        if snapshot:
            self.store.save_learning_snapshot({"symbol": self.symbol, **row})

    def _sync_earnings(self):
        self.last_earnings_sync = time.time()
        try:
            start = int((datetime.now(TZ) - timedelta(days=35)).timestamp() * 1000)
            entries = self.client.funding_earnings(self.currency, start_mts=start)
        except BfxError as e:
            log.warning("子帳戶收益同步失敗: %s", e)
            return
        daily: dict[str, float] = {}
        latest_balance: dict[str, float] = {}
        for e in sorted(entries, key=lambda x: x.mts):
            d = datetime.fromtimestamp(e.mts / 1000, TZ).strftime("%Y-%m-%d")
            daily[d] = daily.get(d, 0.0) + e.amount
            latest_balance[d] = e.balance
        for d, amt in daily.items():
            self.store.save_learning_earning(d, self.currency, amt, latest_balance.get(d))
        if daily:
            log.info("子帳戶收益同步完成：%d 天", len(daily))
