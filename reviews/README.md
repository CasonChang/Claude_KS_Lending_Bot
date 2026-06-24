# 每週放貸檢討（weekly reviews）

每個週末使用者說「**分析本週放貸狀況**」時，AI agent 依此流程產出一份檢討，
做為跨對話的「記憶」與網頁每週重點來源。

## 檔案

- `reviews/YYYY-MM-DD.md`：每週一份，檔名 = 該週起始日（使用者的一週是**週六～週五**）。
  含 YAML front matter（`week` / `period` / `title` / `metrics`）+ markdown 全文。
  這份是**人類/agent 可讀的正本**，也是推到 Supabase 給網頁的來源。

## 每週產出流程（agent 照做）

1. 用 `SUPABASE_SERVICE_KEY`（env）讀 Supabase：`actions_log`（成交/撤單/關單）、
   `earnings`（每日實收）、`credits_snapshots`（本金/加權年化）、`market_snapshots`（錨點/spike）、
   `capital_flows`（入出金）。範圍取使用者那一週（週六 00:00 ~ 下週六 00:00，TZ+8）。
2. 用 Bitfinex 公開 API 抓 fUSD/fUST 同期 1h K 棒（`candles/trade:1h:fXXX:a30:p2:p30/hist`）當市場基準。
3. 綜合評比：成交均年化 vs 市場、實收淨年化（利息/平均本金，已扣 15%）、用率、churn、提前還款比例、
   spike 命中、週末是否冷清、USD/UST 比較。
4. 寫成 `reviews/YYYY-MM-DD.md`（沿用上一份格式）。
5. `python tools/post_weekly_review.py reviews/YYYY-MM-DD.md` → upsert 到 Supabase（網頁讀得到）。
6. push（Pages 自動部署）。若有改 `web/`，記得把 `index.html` / `reviews.html` 的 `?v=` 版本號往上加。

## 網頁

- 網頁 `web/reviews.html`（從 Dashboard 右上「每週檢討」連結進入）用同一組 Dashboard 密碼解鎖，
  呼叫 `dashboard_data(token)` RPC 讀 `weekly_reviews` 欄位顯示。個人績效一律 token 保護、不公開。

## 一次性安裝

- `supabase/migrations/007_weekly_reviews.sql` 要先在 Supabase SQL Editor 跑一次
  （建 `weekly_reviews` 表 + 擴充 `dashboard_data` RPC）。之後 agent 用 service key 寫入即可，不需再手動。

## 未決議事項（每週檢討時務必檢查、做完決議就移除）

- **天期邏輯改法（2026-06-24 提出，待本週檢討後定奪）**：
  診斷見 `research/period_edge_findings.md`。核心：我們的 `periods` 把長天期發給高溢價檔（會被 refinance、白鎖），
  把 2 天短期發給近市場價的基檔（最黏卻一直落地閒置）——邏輯接反。
  建議改法：下修 `config.yaml` 的 `periods` 門檻，讓**近市場價的基/中檔**去鎖 30/120 天（黏住複利），
  頂檔保持短期靈活去接回流。**使用者要求等本週（06/20–06/26）檢討完、看數據再決定保守/激進程度**。
  檢討時請把這項拿出來，根據「31–120 天成交占比 / 長單放滿% / fUSD 實收淨年化」三指標給建議數值。
