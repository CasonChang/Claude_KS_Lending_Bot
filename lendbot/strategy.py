"""策略引擎：全部是純函式（輸入→輸出），不打 API、不碰 DB，方便單元測試。

利率單位約定：全程使用 Bitfinex 的「日利率」（如 0.0002 = 0.02%/天），
只在顯示與天期判斷時換算年化。
"""
from __future__ import annotations

from dataclasses import dataclass

from .bfx_client import BookEntry, FundingTicker, FundingTrade, Offer


# ── 利率換算 ──────────────────────────────────────────────

def daily_to_apy(rate: float) -> float:
    """日利率 → 年化（複利）。0.0002 → 約 0.0758 (7.58%)"""
    return (1 + rate) ** 365 - 1


def apy_to_daily(apy: float) -> float:
    """年化（複利）→ 日利率。"""
    return (1 + apy) ** (1 / 365) - 1


def iqm(values: list[float]) -> float:
    """四分位距內平均（Interquartile Mean）：去掉最低/最高各 25% 後取平均。
    比平均值抗極端值，比中位數平滑。樣本 < 4 時退化為一般平均。"""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n < 4:
        return sum(s) / n
    q = n // 4
    mid = s[q:n - q]
    return sum(mid) / len(mid)


# ── 市場分析 ──────────────────────────────────────────────

@dataclass
class MarketView:
    frr: float           # Flash Return Rate（參考用）
    best_ask: float      # 掛單簿最低放貸利率（隊伍最前面）
    depth_rate: float    # 前 N 美元深度處的利率
    trade_iqm: float     # 近期成交 IQM（主要錨點）
    recent_high: float   # spike 視窗內最高成交利率
    spike: bool          # 是否偵測到利率飆漲
    anchor: float        # 最終錨點利率（階梯的基準）
    rate_floor: float = 0.0  # 24 小時行情保底（避免短暫低迷掛太低）
    long_trade_iqm: float = 0.0  # 近期 120 天固定成交 IQM
    long_best_bid: float = 0.0   # 當下 120 天固定借款 bid 最高利率
    long_trade_count: int = 0


def analyze_market(ticker: FundingTicker, book: list[BookEntry],
                   trades: list[FundingTrade], scfg: dict,
                   now_mts: int, recent_closes: list[float] | None = None) -> MarketView:
    # 1) 掛單簿：累計 ask 深度到 book_depth_usd，該處利率 = 要排進隊伍前段的利率
    depth_target = float(scfg.get("book_depth_usd", 300_000))
    asks = sorted((b for b in book if b.amount > 0), key=lambda b: b.rate)
    cum, depth_rate = 0.0, (asks[-1].rate if asks else 0.0)
    for a in asks:
        cum += a.amount
        if cum >= depth_target:
            depth_rate = a.rate
            break
    best_ask = asks[0].rate if asks else 0.0

    # 2) 成交 IQM 錨點
    lookback = int(scfg.get("trades_lookback", 120))
    rates = [t.rate for t in trades[:lookback]]
    anchor_iqm = iqm(rates)
    long_rates = [t.rate for t in trades[:lookback] if t.period >= 120]
    long_trade_iqm = iqm(long_rates)
    long_bids = [b.rate for b in book if b.amount < 0 and b.period >= 120]
    long_best_bid = max(long_bids, default=0.0)

    # 3) spike 偵測：近 N 分鐘最高成交 vs IQM
    window_mts = now_mts - int(scfg.get("spike_window_minutes", 15)) * 60_000
    recent = [t.rate for t in trades if t.mts >= window_mts]
    recent_high = max(recent, default=0.0)
    spike = bool(anchor_iqm) and recent_high > anchor_iqm * float(scfg.get("spike_mult", 1.8))

    # 4) 行情保底：近 24 小時 1h K 收盤的第 P 百分位。
    #    成交 IQM 只涵蓋幾分鐘，市場短暫低迷時會把階梯整組拉低，
    #    低利成交一卡就是 2 天 —— 用較長期的行情撐住下限（掛太高頂多晚點成交）。
    rate_floor = 0.0
    if recent_closes:
        s = sorted(recent_closes)
        k = int(len(s) * float(scfg.get("floor_percentile", 25)) / 100)
        rate_floor = s[min(k, len(s) - 1)]

    # 5) 錨點 = max(成交IQM, 深度利率, 行情保底, 最低利率底線)
    min_rate = apy_to_daily(float(scfg.get("min_rate_apy", 3.0)) / 100)
    anchor = max(anchor_iqm, depth_rate, rate_floor, min_rate)

    return MarketView(frr=ticker.frr, best_ask=best_ask, depth_rate=depth_rate,
                      trade_iqm=anchor_iqm, recent_high=recent_high,
                      spike=spike, anchor=anchor, rate_floor=rate_floor,
                      long_trade_iqm=long_trade_iqm, long_best_bid=long_best_bid,
                      long_trade_count=len(long_rates))


# ── 天期選擇 ──────────────────────────────────────────────

def choose_period(rate: float, scfg: dict) -> int:
    """利率年化越高 → 鎖越長天期。periods 設定由年化門檻大到小判斷。"""
    apy_pct = daily_to_apy(rate) * 100
    periods = sorted(scfg.get("periods", [{"apy": 0, "days": 2}]),
                     key=lambda p: -float(p["apy"]))
    for p in periods:
        if apy_pct >= float(p["apy"]):
            return int(p["days"])
    return 2


# ── 階梯掛單 ──────────────────────────────────────────────

def floor2(x: float) -> float:
    """金額無條件捨去到分。用四捨五入會把 87.578 進成 87.58，
    各檔加總可能超過可用餘額，下單被拒（not enough balance）。"""
    return int(x * 100) / 100


@dataclass
class OfferPlan:
    amount: float
    rate: float          # 日利率
    period: int

    @property
    def apy_pct(self) -> float:
        return daily_to_apy(self.rate) * 100


def build_ladder(available: float, view: MarketView, scfg: dict) -> list[OfferPlan]:
    """把可用資金按 ladder 設定拆成多檔。不足最小掛單額的檔位往前一檔合併。
    偵測到 spike 時改用 spike_ladder（加重高利率檔位）。"""
    min_offer = float(scfg.get("min_offer_usd", 150))
    if available < min_offer:
        return []

    ladder = scfg.get("ladder", [{"weight": 1.0, "mult": 1.0}])
    if view.spike and scfg.get("spike_ladder"):
        ladder = scfg["spike_ladder"]
    rungs: list[OfferPlan] = []
    for i, rung in enumerate(ladder):
        amount = available * float(rung["weight"])
        rate = view.anchor * float(rung["mult"])
        # spike 時最後一檔改追近期最高成交利率
        if view.spike and i == len(ladder) - 1:
            rate = max(rate, view.recent_high * float(scfg.get("spike_discount", 0.95)))
        rungs.append(OfferPlan(amount=floor2(amount), rate=round(rate, 8),
                               period=choose_period(rate, scfg)))

    # 太小的檔位由低利率往高利率合併（優先保住容易成交的低檔）
    merged: list[OfferPlan] = []
    carry = 0.0
    for plan in rungs:
        amt = plan.amount + carry
        if amt < min_offer:
            carry = amt
            continue
        merged.append(OfferPlan(amount=floor2(amt), rate=plan.rate, period=plan.period))
        carry = 0.0
    if carry >= min_offer and merged:
        last = merged[-1]
        merged[-1] = OfferPlan(amount=floor2(last.amount + carry),
                               rate=last.rate, period=last.period)
    if not merged and available >= min_offer:
        merged = [OfferPlan(amount=floor2(available), rate=rungs[0].rate,
                            period=rungs[0].period)]
    return merged


# ── FRR 試點 ──────────────────────────────────────────────
# 背景：FRR（浮動）長期高於我們階梯的成交利率（14 天實測 FRR 12.8% vs 我們 book 10.5%），
# 但 FRR 價位的單很難成交（我們掛在 ≥FRR−15% 的 168 筆只成交 3 筆＝2%），
# 子帳戶的 FRR 單靜置約 45 小時才成交 → 必須「長時間掛著等」，短逾時等於白掛。
# 因此此試點：只用當下可用（剛回流）的錢、總量設硬上限、需求觸發才掛、逾時很長（預設 24h）。


@dataclass(frozen=True)
class FrrPlan:
    """120 天試點掛單；可為浮動 FRR 或固定利率。"""
    amount: float
    period: int
    rate: float = 0.0
    offer_type: str = "FRRDELTAVAR"


def is_frr_offer(offer) -> bool:
    """FRR 浮動單/放貸的 rate 欄為 0（Bitfinex 慣例），用來和一般 LIMIT 單分流。
    Offer 與 Credit 都有 .rate，兩者共用。"""
    return not (offer.rate and offer.rate > 0)


def effective_rate(rate: float, frr: float) -> float:
    """FRR 單/部位的 rate 欄存的是「相對 FRR 的偏移量」（我們用 0＝純 FRR），不是實際利率。
    顯示與統計要換成當下 FRR，否則會被當 0% 計入、把加權年化拖低。"""
    return frr if (not rate or rate <= 0) else rate


def frr_pilot_plan(available: float, frr_exposure: float, total_capital: float,
                   view: MarketView, scfg: dict,
                   allow_fixed_fallback: bool = False) -> FrrPlan | None:
    """需求觸發時，把當下可用資金撥一筆去掛浮動 FRR。額度用滿或沒觸發就回 None。

    觸發（任一）：(a) spike 偵測；(b) 近期最高成交 ≥ FRR × trigger_near_frr。
    實測 14 天：兩者合計約佔 13.6% 時間（日均 ~195 分鐘），每天都有機會觸發。
    """
    pcfg = scfg.get("frr_pilot") or {}
    if not pcfg.get("enabled") or total_capital <= 0:
        return None
    near = float(pcfg.get("trigger_near_frr", 0.98))
    min_samples = int(pcfg.get("min_long_trade_samples", 5))
    premium = float(pcfg.get("fixed_premium_ratio", 1.005))
    fallback = float(pcfg.get("fixed_fallback_ratio", 0.95))
    fixed_threshold = fallback if allow_fixed_fallback else premium
    fixed_attractive = (view.long_trade_count >= min_samples and view.long_best_bid > 0
                        and view.long_best_bid >= view.frr * fixed_threshold)
    triggered = (bool(pcfg.get("trigger_spike", True)) and view.spike) or (
        view.frr > 0 and view.recent_high >= view.frr * near) or fixed_attractive
    if not triggered:
        return None
    room = long_term_exposure_cap(total_capital, scfg) - frr_exposure
    min_offer = float(pcfg.get("min_offer_usd", scfg.get("min_offer_usd", 150)))
    amount = min(available, room)
    if amount < min_offer:
        return None
    enough_long_data = view.long_trade_count >= min_samples
    if (enough_long_data and view.long_best_bid > 0
            and view.long_best_bid >= view.frr * fixed_threshold):
        return FrrPlan(amount=floor2(amount), period=int(pcfg.get("period_days", 120)),
                       rate=view.long_best_bid, offer_type="LIMIT")
    return FrrPlan(amount=floor2(amount), period=int(pcfg.get("period_days", 120)))


def long_term_exposure_cap(total_capital: float, scfg: dict) -> float:
    """回傳單一幣別所有 120 天掛單＋放貸的金額上限。

    ``long_term_max_amount`` 是所有 120 天 FRR／固定部位的共同硬上限；保留舊欄位
    fallback，讓既有部署升級時不會突然停擺。固定上限不隨入金／提幣改變。
    """
    pcfg = scfg.get("frr_pilot") or {}
    if "long_term_max_amount" in pcfg:
        return max(0.0, float(pcfg["long_term_max_amount"]))
    if "max_amount" in pcfg:  # 2026-08-20 舊設定相容
        return max(0.0, float(pcfg["max_amount"]))
    return max(0.0, total_capital * float(pcfg.get("max_alloc_pct", 0.05)))


# 舊名稱保留，避免既有研究腳本或外部引用中斷。
frr_exposure_cap = long_term_exposure_cap


def should_cancel_frr(offer: Offer, scfg: dict, now_mts: int) -> bool:
    """FRR 試點單掛太久仍沒成交 → 撤回還給階梯，避免無限期閒置。
    timeout_minutes 設 0 = 永不撤（一直等成交）。"""
    pcfg = scfg.get("frr_pilot") or {}
    timeout = float(pcfg.get("timeout_minutes", 1440))
    if timeout <= 0:
        return False
    return (now_mts - offer.mts_created) / 60_000 >= timeout


# ── 重掛判斷 ──────────────────────────────────────────────

def should_cancel(offer: Offer, view: MarketView, scfg: dict, now_mts: int) -> bool:
    """掛太久沒成交 → 撤單重掛，減少資金閒置。兩種情況會撤：

    (a)〈錨點崩跌〉利率高到連階梯最高檔都追不上（錨點 × 最大 mult × 門檻）。
       比較基準是「現在會掛的最高檔利率」而非錨點本身：階梯頂檔本來就掛在錨點 ×1.45，
       若拿「錨點 ×1.05」當門檻，頂檔每過 stale 分鐘就被判定過貴撤掉重掛 —— 利率往往
       只差 0.0x%，卻一直洗掉排隊順位（無意義 churn）。只有市場真的跌到「連頂檔都過高」才重排。

    (b)〈平靜期上層檔閒置〉沒有 spike、且掛超過 idle_redeploy_minutes（比 stale 久很多）
       還沒成交、利率又明顯高於錨點（> 錨點 ×(1+門檻)，即中／高檔）→ 釋出重掛。
       重掛後 build_ladder 會把釋出資金重新分配（大部分落到容易成交的最低檔），自然下修，
       避免高利檔在安靜行情乾等領 0%。spike 期間完全不套用（要留著追高）。
       idle_redeploy_minutes 設 0 = 關閉此行為（預設關，向後相容）。"""
    age_minutes = (now_mts - offer.mts_created) / 60_000
    if age_minutes < float(scfg.get("stale_minutes", 10)):
        return False
    threshold = 1 + float(scfg.get("cancel_threshold", 0.05))
    key = "spike_ladder" if (view.spike and scfg.get("spike_ladder")) else "ladder"
    ladder = scfg.get(key) or [{"mult": 1.0}]
    top_mult = max(float(r.get("mult", 1.0)) for r in ladder)
    # (a) 錨點崩跌：連頂檔都顯得過高
    if offer.rate > view.anchor * top_mult * threshold:
        return True
    # (b) 平靜期上層檔閒置太久 → 釋出重掛（下一輪重新分配、自然下修）
    idle_minutes = float(scfg.get("idle_redeploy_minutes", 0))
    if (idle_minutes > 0 and not view.spike and age_minutes >= idle_minutes
            and offer.rate > view.anchor * threshold):
        return True
    return False
