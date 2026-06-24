# fuly.ai 側錄 / 影子比對 監控系統設計

**狀態**：架構草案，求共識中。有共識後再寫骨架。
**日期**：2026-06-24

## 目標

不做嚴格報酬率賽跑（兩邊資金軌跡會分岔，不公平），改做**「同一個帳戶狀態下，fuly 怎麼決策 vs 我們會怎麼決策」的並列比對**，藉此：
1. 學到 fuly 的實際參數（掛單利率、天期、階梯形狀、撤單/重掛節奏）。
2. 在**完全相同的起始狀態**下，記錄我們策略的「影子決策」（dry，不真的下單），看跟 fuly 差在哪。

## 帳戶配置（使用者已拍板）

- **主帳戶**：照常跑我們的正式 bot（Zeabur），完全不動。
- **一個子帳戶**：使用者放一筆錢 → 把**寫權限** API key 交給 fuly.ai → fuly **真實**在這個子帳戶下單。
- 我們拿這個子帳戶的**唯讀** key（只開 Account/Wallets 讀、Margin Funding 讀，**不開寫、不開提幣**）做側錄。
- 兩邊金額不必相等（這個設計不需要等額）。

## 核心機制：真實 fuly + 影子我們

監控迴圈（**獨立程式、唯讀、永不 submit/cancel**，跟正式 `engine.py` 完全隔離）：

```
每隔 N 分鐘（建議 5 分）對「子帳戶」做一次快照：
  1. 讀帳戶現況（fuly 造成的真實狀態）：
       wallet（總額/可用）、active_offers（fuly 當下掛的單）、active_credits（fuly 放出去的）、
       近期成交/已結束（credits_history）。
  2. 讀市場：funding_ticker / funding_book / funding_trades（公開，跟正式引擎同一套 view）。
  3. 跑「我們的策略」純函式（build view → build_ladder → 天期選擇 → should_cancel），
     用「子帳戶的可用餘額 + 同一份市場 view」算出「我們在這個狀態下會掛的單」。
     —— 這就是 dry：算出 shadow_orders，但一張都不送出。
  4. 把三組資料連同時間戳寫進 DB：
       a) fuly 實際：offers / credits / wallet
       b) 我們影子：shadow_orders（rate / period / amount / ladder 形狀）
       c) 市場 view：anchor / spike / frr 等當下基準
```

> 重點：兩邊看的是**同一個子帳戶餘額、同一刻的市場**，所以「fuly 掛 11%×120天 vs 我們會掛 14.5%×30天」
> 這種差異是乾淨可比的——消掉了「不同帳戶、不同成交史」的干擾（正是使用者原本擔心的那點）。

## 限制與誠實話

- 帳戶軌跡由 **fuly 驅動**（它在真的下單），所以我們看到的後續狀態是「fuly 決策的結果」。
  我們的影子決策**不會**反過來改變帳戶 → 學不到「若全程由我們跑，報酬會如何」。
  這設計學的是**決策差異與 fuly 參數**，不是終局報酬。使用者已接受此取捨。
- fuly 的成交/放滿/實收**是真的**（它真的在放），可以直接量它的 util、早還率、實收年化，
  拿來跟我們主帳戶（正式 bot）的同期數據對照。

## 要記錄 / 之後分析的指標

| 維度 | fuly（實際） | 我們（影子 or 主帳戶實際） |
|---|---|---|
| 掛單利率分布 | active_offers 的 rate | shadow_orders 的 rate |
| 天期配置 | offers/credits 的 period 占比 | shadow_orders 的 period |
| 階梯形狀 | offers 的 rate×amount 分布 | build_ladder 輸出 |
| 重掛節奏 | 前後快照 offers diff（新增/撤掉） | should_cancel 影子觸發 |
| 成交利率/天期 | credits 實際 | （主帳戶）我們實際成交 |
| util / 早還率 / 放滿% | credits_history 算 | （主帳戶）同期 |
| 實收淨年化 | ledger 利息 / 本金 | （主帳戶）同期 |

## 元件（骨架預定長相）

- `tools/fuly_monitor.py`（新）：上面的迴圈。唯讀、獨立進程，可在 Zeabur 當第二個 service 或本機 cron 跑。
  - 重用 `lendbot/bfx_client.py`（已有 funding_wallet / active_offers / active_credits / credits_history / 市場 API）。
  - 重用 `lendbot/strategy.py` 的純函式算影子單（**不碰 engine.py、不觸發任何下單路徑**）。
  - 用「另一組 env」連子帳戶：`MONITOR_BFX_KEY` / `MONITOR_BFX_SECRET`（唯讀）。
- DB migration `supabase/migrations/009_fuly_monitor.sql`（新）：
  - `fuly_snapshots`（ts, wallet_total, available, market jsonb, fuly_offers jsonb, fuly_credits jsonb, shadow_orders jsonb）
  - 可選：`fuly_events`（撤掉/新增的 offer diff，給「重掛節奏」用）
- 網頁（之後）：一個受同組密碼保護的比對頁，把 fuly vs 我們並列。

## 安全紅線（沿用專案慣例）

- 監控 key **唯讀無提幣**；監控程式**永不** submit/cancel，跟正式策略不共用 loop、不會雙重下單。
- key 只進 env（Zeabur / 本機 `.env`），永不進 git。
- 正式 bot（主帳戶）完全不受影響。

## 待使用者確認的點（求共識）

1. 監控頻率 5 分鐘可以嗎？（要抓 fuly 重掛節奏，太久會漏；太密會多打 API。）
2. 監控程式跑哪：**Zeabur 第二個 service**（24/7，推薦）還是本機定時跑（會漏夜間）？
3. 影子決策用「現在的 config.yaml」還是「天期改版後的 config」？建議**等天期改版上線後**再側錄，
   才是拿「我們的新策略」對打 fuly，比較有意義。
4. 子帳戶金額沒硬性要求，但建議別太小（太小 fuly 可能只掛一兩檔、樣本少）。
