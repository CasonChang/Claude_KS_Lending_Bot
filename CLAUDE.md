# CLAUDE.md — 給接手這個專案的 AI agent

Bitfinex P2P 放貸自動化機器人。使用者說**繁體中文**，回覆請用繁中。
這份檔案讓任何新對話（桌機或 Claude Code Web）快速接手；細節見 [README.md](README.md) 與 [DESIGN.md](DESIGN.md)。

## ⚠️ 最重要：策略已部署在 Zeabur，不要在本機啟動機器人

- **正式策略 2026-06-18 起跑在 Zeabur**（雲端、真實模式、24/7）。
- **絕對不要執行 `python -m lendbot`**（或任何啟動引擎的方式）。本機再跑一個會跟
  Zeabur **雙重下單**、Telegram long-polling 互搶（回 409）。單例鎖（port 47391）
  只擋同一台機器、擋不到本機↔Zeabur。
- 本機這裡只用來：**改程式、跑單元測試、預覽網頁**。不碰運行中的策略。
- 要改策略行為 → 改 code → push → Zeabur 會自動 redeploy（或請使用者手動 Redeploy）。

## 架構

| 部分 | 位置 | 部署 |
|---|---|---|
| 策略機器人（Python） | `lendbot/` | **Zeabur**（Dockerfile，真實模式）|
| 網頁 Dashboard（靜態） | `web/` | **GitHub Pages**（push 自動部署，workflow 在 `.github/workflows/pages.yml`）|
| 歷史/狀態 DB | `supabase/` | Supabase（PostgREST RPC `dashboard_data`）|
| 推播 + 指令 | Telegram | bot 由 Zeabur 那份在輪詢 |

策略：IQM 錨點 + 階梯掛單 + spike 追高 + 高利鎖長天期 + 過時自動重掛。
參數全在 `config.yaml`（改了要 push + Zeabur redeploy 才生效）。

## 怎麼做變更

- **策略/引擎**：改 `lendbot/`（純函式邏輯在 `strategy.py`，循環在 `engine.py`）→
  `python -m pytest`（目前 33 passed）→ push → Zeabur redeploy。
- **網頁**：改 `web/`（`app.js`/`index.html`/`style.css`）→ push → Pages 自動部署。
  ⚠️ 改完**務必把 `index.html` 裡 `?v=YYYYMMDD…` 版本號往上加**，否則使用者瀏覽器/CDN
  會吃到舊快取（踩過幾次）。本機可用 preview 工具驗證（launch.json 已設 `dashboard`）。
- **DB schema**：新增 `supabase/migrations/NNN_*.sql`，請使用者到 Supabase SQL Editor 貼上執行。
  目前已套用到 `006_capital_flows.sql`。

## 重要慣例 / 不變量

- **手續費**：Bitfinex 對放貸利息收 **15%**（`FUNDING_FEE = 0.15`）。
- **網頁費用基準分兩類**（別搞混）：
  - **掛單利率類＝稅前**（市場真實利率，對照市場 K 線）：放貸中明細「年化」、
    幣別明細「加權年化」、Telegram 成交/結束通知。
  - **實際入袋/效率類＝稅後扣 15%**：每日預估收益、放滿預估報酬、總結列、
    總預估年化（卡片＋幣別明細）、已結束放貸淨獲利。
- **資金安全**：Bitfinex API key 只開 Account/Wallets 讀、Margin Funding 讀寫，**不開提幣**。
- **秘密**：`.env` 永不進 git（已在 `.gitignore`）；Supabase `service_role` key 只在伺服器端
  （Zeabur env / 本機 .env），網頁只用 `anon` key。正式 secrets 現在在 Zeabur 環境變數。

## 每週放貸檢討（weekly review）

使用者每個週末會說「**分析本週放貸狀況**」。流程與格式見 [`reviews/README.md`](reviews/README.md)：
用 `SUPABASE_SERVICE_KEY` 讀 DB（actions_log/earnings/credits_snapshots/market_snapshots/capital_flows）
＋ Bitfinex 公開 K 棒做市場基準 → 綜合評比 → 寫 `reviews/YYYY-MM-DD.md`（檔名=該週起始日，使用者一週是**週六～週五**）
→ `python tools/post_weekly_review.py reviews/YYYY-MM-DD.md` upsert 到 Supabase → push。
網頁從 Dashboard 右上「📝 每週檢討」連結（`web/reviews.html`）用同組密碼解鎖檢視。
一次性安裝：`supabase/migrations/007_weekly_reviews.sql`（建表＋擴充 RPC）需先在 Supabase SQL Editor 跑一次。

## 策略學習模式（2026-07-02 建置）

主帳戶跑我們的正式策略、**子帳戶交由外部專業放貸策略操作**（⚠️ repo 公開，
程式/文件/commit 一律稱「子帳戶策略」，**不寫是哪個服務**），雙方各約 10,000 USD 比績效。

- **觀察者** `lendbot/observer.py`：Zeabur env `LEARNING_ENABLED=1` ＋子帳戶唯讀 key
  `MONITOR_BFX_KEY/SECRET` 時，以 daemon thread 啟動（跟正式 bot 同一個 service）。
  每 60 秒唯讀輪詢子帳戶、差異偵測寫事件、每 15 分完整快照＋影子決策（我們的策略
  對同一狀態會掛什麼，純計算）。**程式路徑不含任何下單呼叫，我們無法操作子帳戶。**
- **隱藏比較頁**：`web/learn.html`（**主頁不放連結**，網址
  `casonchang.github.io/Claude_KS_Lending_Bot/learn.html`，同 Dashboard 密碼，
  RPC `learning_data`）。
- **每日學習檢討**：SOP 見 [`reviews/learning/README.md`](reviews/learning/README.md)。
  結算窗口＝UTC 日（Bitfinex 利息 00:00 UTC＝台北 08:00 入帳），每天台北 09:30 後跑，
  寫 `reviews/learning/YYYY-MM-DD.md` → `python tools/post_learning_review.py <檔>` → push。
- **鐵則**：主帳戶策略只有使用者明確下令才能改，改了記在當日檢討「主帳戶策略變更紀錄」。
- 一次性安裝：`supabase/migrations/010_learning.sql` 先在 Supabase SQL Editor 跑一次。
- 設計脈絡：`research/learning_monitor_design.md`。

## Telegram 指令

`/status` `/rates` `/earnings` `/review`（昨日策略檢討）`/capital`（立即偵測入金/出金/兌換）
`/go` `/lend` `/pause` `/resume`。

## 現況快照（2026-07-02）

- Zeabur 真實模式運行中；本機已停。帳戶 fUSD + fUST 放貸中（規模約 1 萬鎬，使用者陸續加碼，
  目標實測一個月真實月報酬）。
- 已上線功能：churn 修復、每日 9am 報告 + 策略檢討、錨點年化 7 天圖、資金變動自動偵測
  （入金/出金/兌換 → DB + 網頁 + 推播，每 15 分同步）、成交/結束推播合併、手機 RWD、
  網頁費用基準釐清、錢包趨勢圖與每日年化圖的加總/分幣別切換。
- 學習模式程式已就緒，等使用者：跑 migration 010、開子帳戶、雙邊各入 1 萬 USD、
  在 Zeabur 設 `LEARNING_ENABLED=1`＋`MONITOR_BFX_KEY/SECRET`（唯讀）。
- repo：`github.com/CasonChang/Claude_KS_Lending_Bot`｜Pages：`casonchang.github.io/Claude_KS_Lending_Bot/`
