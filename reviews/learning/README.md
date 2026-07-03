# 每日學習檢討 SOP（策略學習期）

**背景**：主帳戶跑我們的正式策略、子帳戶交由外部專業放貸策略操作（不具名，repo 公開），
雙方各投入約 10,000 USD。目標：每天並列比較、推測對方策略，好的地方學起來優化我們的主策略。
學習期約 1 週～1 個月。子帳戶只有唯讀 key，我們**無法**對它下單。

觀察資料由 `lendbot/observer.py`（Zeabur 上 `LEARNING_ENABLED=1` 時啟動）自動寫入
Supabase `learning_*` 表；本 SOP 是「每天一次」的分析產出流程，由 AI agent 照做。

## 結算窗口（重要，別搞錯歸屬）

- Bitfinex 放貸利息**每天 00:00 UTC（台北 08:00）入帳一次**——這就是每日歸零點。
- **檢討日 D ＝ UTC 日 D**（台北 D 日 08:00 ～ D+1 日 08:00）。
- 事件/快照的篩選窗口：`ts` 在 `[D 00:00 UTC, D+1 00:00 UTC)`。
- **檢討日 D 的實收利息＝入帳日期標為 D+1 的 earnings 列**（D+1 凌晨 00:00 UTC 入帳的
  是 D 日整天的利息）。`earnings` / `learning_earnings` 的 date 欄用入帳當地日（UTC+8）標。
- 排程：每天**台北 09:30 後**跑（利息已入帳、bot 每小時的收益同步也已跑過）。

## 產出流程（agent 照做）

1. **前置檢查**：讀 `learning_status`（用 `SUPABASE_SERVICE_KEY` env，
   `GET {SUPABASE_URL}/rest/v1/learning_status`）。若無資料或 `ts` 已過時 →
   學習模式還沒開/觀察者掛了，跟使用者回報即可，**不要**硬產檢討檔。
2. **抓資料**（PostgREST，`Authorization: Bearer $SUPABASE_SERVICE_KEY`）：
   - 子帳戶：`learning_events`（窗口內全部）、`learning_snapshots`（窗口內）、
     `learning_earnings`、`learning_status`（現況）。
   - 主帳戶：`actions_log`（窗口內 submit/cancel/fill/closed_*，只取 detail.symbol=fUSD）、
     `earnings`（USD）、`credits_snapshots`（fUSD，算平均本金）、`market_snapshots`（錨點對照）。
   - 市場基準：Bitfinex 公開 K 棒 `candles/trade:1h:fUSD:a30:p2:p30/hist`（窗口同日）。

   ⚠️ **一定要抓「整天」、而且要分頁**（別用網頁那條 RPC，也別只抓最近幾筆）：
   - 直接查表、用**當天 UTC 日窗口**過濾：`ts=gte.D T00:00:00Z` ＋ `ts=lt.(D+1) T00:00:00Z`。
     （網頁的 60 筆顯示、RPC 的 400 筆都只是「顯示上限」，跟檢討無關。）
   - **PostgREST 單次最多回 1000 列**，`learning_events`（對方 2 天短單週轉）與 `actions_log`
     單日很容易破千 → **務必分頁**（`Range: 0-999`、`1000-1999`… 或 `limit`＋`offset`，
     一直翻到某頁回傳 < 1000 為止），否則會**默默被截斷**、統計失真。
   - 想先知道總筆數：帶 `Prefer: count=exact`＋`Range: 0-0`，讀回應的 `Content-Range`
     （`0-0/1234` 的 1234 就是總數），確認有沒有超過 1000、要翻幾頁。
3. **對比分析**（至少涵蓋）：
   - 績效：當日實收利息、單位資金淨年化（利息÷平均本金×365）、資金利用率、成交筆數/金額、
     成交加權年化（稅前，對照市場 K 棒）、提前還款率、平均放滿%。
   - 對方節奏：掛單→成交耗時、撤單頻率、同輪「撤單＋新掛」（＝調單）次數與間隔、
     掛單利率 vs 當時錨點/FRR/隊首（用 snapshots 的 market 欄對時間軸比）、天期分布。
   - 影子對照：同一時刻 shadow（我們會掛的）vs 對方實掛，利率/天期/階梯形狀差在哪。
4. **推測對方策略**：錨點跟誰（FRR？隊首？成交價）、有沒有階梯、天期邏輯、重掛週期。
   每天累積修正前一天的推測（寫明「較昨日更新的推測」）。
5. **寫檔** `reviews/learning/YYYY-MM-DD.md`（檔名＝檢討日 D），格式見下。
6. **上傳**：`python tools/post_learning_review.py reviews/learning/YYYY-MM-DD.md`
   （網頁 learn.html 的「每日學習檢討」區就看得到）。
7. **push**（不用改 web/ 的話不用動版本號）。
8. Telegram/對話裡給使用者 3～5 行摘要。

## 檢討檔格式

```markdown
---
date: "2026-07-05"
title: "一句話重點"
metrics: { main_apy: 0.0, sub_apy: 0.0, main_util: 0.0, sub_util: 0.0 }
---
# 學習檢討 2026-07-05（UTC 日）

## 當日數據對比
（表格：實收利息｜淨年化｜利用率｜成交筆數/金額｜成交加權年化｜提前還款率…主 vs 子）

## 我們的策略方向（現況）
（config.yaml 摘要：錨點=IQM+保底、階梯 50/30/20×1.00/1.15/1.45、spike、天期三段式、重掛 10 分）

## 子帳戶推測策略方向
（今天觀察到的行為 + 累積推測，標注信心程度與較昨日的修正）

## 觀察到的東西
（值得注意的事件、影子對照差異、市場背景）

## 可調整的策略方向（僅建議，未動主帳戶）
（若對方做得好：學什麼、怎麼改參數；若我們較好：對方哪招仍可借鏡）

## 主帳戶策略變更紀錄
（無變更就寫「無」；使用者下令調整時記：日期、改了什麼、為什麼、預期效果）
```

## 鐵則

- **絕不主動調整主帳戶策略**——只列建議，等使用者明確下令才改 `config.yaml`，
  改了要記在當日檢討的「主帳戶策略變更紀錄」，之後回到觀察循環驗證效果。
- 檢討內文**不寫**子帳戶交給哪個網站/服務（repo 公開），一律稱「子帳戶策略」。
- 只讀不動：整個流程不碰任何下單路徑、不重啟 Zeabur。

## 排程

- 以 Claude Code 的 session cron 為主（每天台北 09:33）。session 結束或超過 7 天
  cron 會失效——發現某天沒有新檢討時，開個對話說「**做昨日學習檢討**」手動補跑，
  順便說「**重新設定每日學習檢討排程**」重新掛上 cron。
- 一次性安裝：`supabase/migrations/010_learning.sql` 要先在 Supabase SQL Editor 跑過。
