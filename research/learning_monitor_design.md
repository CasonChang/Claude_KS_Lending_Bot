# 子帳戶側錄 / 學習比對 監控系統設計

**狀態**：✅ 已實作（2026-07-02），實際版本見 `lendbot/observer.py`、
`supabase/migrations/010_learning.sql`、`web/learn.html`、`reviews/learning/README.md`。
本檔保留設計脈絡；「外部策略」指使用者委託操作子帳戶的專業放貸服務（不具名，repo 公開）。
**初版草案**：2026-06-24。實作與草案的差異記在文末。

## 目標

比較「我們的正式策略（主帳戶）」與「外部專業策略（子帳戶）」，藉此：
1. 學到外部策略的實際參數（掛單利率、天期、階梯形狀、撤單/重掛節奏）。
2. 好的地方學起來，優化我們的主策略；我們較強的地方也可借鏡對方細節。

## 帳戶配置（使用者已拍板）

- **主帳戶**：照常跑我們的正式 bot（Zeabur），完全不動。
- **子帳戶**：使用者放一筆錢 → 寫權限 API key 交給外部服務 → 對方**真實**下單。
- 我們拿子帳戶的**唯讀** key（只開 Account/Wallets 讀、Margin Funding 讀、Ledgers 讀，
  **不開寫、不開提幣**）做側錄。
- 2026-07 最終方案：**雙方各投入約 10,000 USD**（等額）→ 可直接比實際績效。

## 核心機制：真實外部策略 + 影子我們

監控迴圈（唯讀、永不 submit/cancel，跟正式 `engine.py` 完全隔離）：

```
每 60 秒對「子帳戶」輪詢一次：
  1. 讀帳戶現況：wallet、active_offers、active_credits、credits_history（盲區回補）。
  2. 與上一輪比對 → 只有變動才寫事件（offer_new / offer_canceled / offer_filled /
     offer_partial_fill / credit_new / credit_closed）。
  3. 每次輪詢 upsert learning_status（現況單列，網頁顯示最後觀測時間）。
每 15 分鐘另寫一筆完整快照（learning_snapshots）：
  4. 讀市場（ticker/book/trades/1h K，跟正式引擎同一套 view）。
  5. 跑「我們的策略」純函式（analyze_market → build_ladder），用子帳戶的可用餘額
     算出「我們在這個狀態下會掛的單」= shadow —— 純計算，一張都不送出。
每小時從 ledger 同步子帳戶每日利息 → learning_earnings。
```

> 影子對照的意義：兩邊看的是**同一個子帳戶餘額、同一刻的市場**，
> 「對方掛 11%×120天 vs 我們會掛 14.5%×30天」這種差異是乾淨可比的。

## 限制與誠實話

- 子帳戶軌跡由外部策略驅動，影子決策不會反過來改變帳戶 →
  影子學的是**決策差異與對方參數**，不是「若全程由我們跑」的終局報酬。
- 但這次雙方等額（各 1 萬 USD），**主帳戶實際 vs 子帳戶實際**的績效賽跑本身就公平，
  影子是額外的顯微鏡。

## 元件（實作版）

- `lendbot/observer.py`：觀察迴圈。daemon thread，由 `__main__.py` 在
  `LEARNING_ENABLED=1` 時啟動（跟正式 bot 同一個 Zeabur service，例外完全隔離）。
- env：`LEARNING_ENABLED`、`MONITOR_BFX_KEY/SECRET`（唯讀）、`LEARNING_SYMBOL`（預設 fUSD）、
  `LEARNING_POLL_SECONDS`（60）、`LEARNING_SNAPSHOT_MINUTES`（15）。
- DB：`supabase/migrations/010_learning.sql`（learning_status / learning_snapshots /
  learning_events / learning_earnings / learning_reviews ＋ `learning_data(token)` RPC）。
- 網頁：`web/learn.html`（隱藏頁，主頁不放連結，同 Dashboard 密碼）。
- 每日檢討：`reviews/learning/README.md` SOP，agent 每天台北 09:30 後產出。

## 安全紅線（沿用專案慣例）

- 監控 key 唯讀無提幣；觀察者程式路徑完全不含 submit/cancel，不可能對子帳戶下單。
- key 只進 env（Zeabur / 本機 `.env`），永不進 git。
- 正式 bot（主帳戶）完全不受影響；主帳戶策略只有使用者下令才改。

## 與 06-24 草案的差異

1. 輪詢 5 分 → **1 分鐘**＋差異偵測（要抓對方快速重掛節奏；只有變動才寫 DB）。
2. 監控程式不開第二個 service → **併入現有 Zeabur service**（daemon thread、例外隔離）。
3. 金額從「不必相等」→ **等額 1 萬 USD**（可直接比實際績效）。
4. 新增每日學習檢討流程與隱藏比較頁。
