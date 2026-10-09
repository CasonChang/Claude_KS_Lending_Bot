# Bitfinex 放貸機器人

穩定高年化的 Bitfinex USD 自動放貸機器人。
策略與架構細節見 [DESIGN.md](DESIGN.md)。

- 🤖 **機器人**：Python，IQM 錨點 + 階梯掛單 + spike 追高 + 高利鎖長天期 + 自動重掛
- 📱 **Telegram**：成交/飆漲/錯誤即時推播，`/status` `/rates` `/earnings` `/pause` 指令
- 📊 **網頁 Dashboard**（GitHub Pages）：即時市場數據（WebSocket）+ 個人放貸總覽
- 🗄 **Supabase**：歷史快照、每日收益、機器人狀態

## 專案結構

```
lendbot/             機器人本體
├── __main__.py      入口（python -m lendbot）
├── config.py        設定載入（config.yaml + .env）
├── bfx_client.py    Bitfinex REST API（公開 + HMAC 私有）
├── strategy.py      策略引擎（純函式，有單元測試）
├── engine.py        核心循環（決策 → 下單 → 記錄 → 推播）
├── store.py         Supabase 寫入層
└── telegram_bot.py  Telegram 推播 + 指令
config.yaml          ★ 策略參數都在這，調整不用改程式
supabase/schema.sql  資料庫 schema（全新安裝用；後續變更放 migrations/）
supabase/run_sql.py  直連 DB 執行 SQL（python supabase/run_sql.py <檔> <db密碼>）
web/                 GitHub Pages 靜態網頁
tests/               單元測試 + 煙霧測試
research/            策略研究腳本與結論（RESULTS.md 必讀）
```

## 快速開始（本機模擬）

```bash
pip install -r requirements.txt
copy .env.example .env        # 什麼都不填 = 模擬模式
python -m lendbot --once      # 跑一個循環看決策
python -m lendbot             # 持續跑
python -m pytest tests/test_strategy.py   # 單元測試
```

模式由 `.env` 決定：

| BFX key | DRY_RUN | 行為 |
|---|---|---|
| 沒填 | — | **模擬模式**：模擬餘額 + 模擬成交，安全測試 |
| 有填 | `true` | **觀察模式**：讀真實帳戶，只記錄「會做什麼」不下單 |
| 有填 | `false` | **真實模式**：真正下單 |

## 上線設定

### 1. Bitfinex API Key
Bitfinex → API Keys → 建立，**只開** Account Info(讀)、Wallets(讀)、
Margin Funding(讀+寫)。**不要開提幣權限！**

### 2. Telegram
1. 找 @BotFather `/newbot` 拿 token
2. 找 @userinfobot 拿自己的 chat id
3. 先跟你的 bot 說一句話（bot 不能主動開聊）

### 3. Supabase
1. 建專案 → SQL Editor → 貼上 `supabase/schema.sql`
   （先把裡面的 `CHANGE_ME_TO_YOUR_SECRET_TOKEN` 改成你的 Dashboard 密碼）
2. Settings → API：`service_role` key 填到 `.env`（伺服器用），
   `anon` key 填到 `web/config.js`（網頁用，公開沒關係）

### 4. Zeabur 部署（24/7 雲端長跑）

機器人是純背景 worker（不對外開 port，Dashboard 在 GitHub Pages），
Zeabur 偵測到 `Dockerfile` 就會用它建置。env 直接在 Zeabur 後台設定，
**不需要也不要**把 `.env` 進 repo（程式找不到 `.env` 會自動改讀系統環境變數）。

**部署步驟**
1. repo 推上 GitHub（已是 `CasonChang/Claude_KS_Lending_Bot`）。
2. Zeabur → New Project → Add Service → Deploy from GitHub → 選此 repo。
   會自動偵測 `Dockerfile`，不用選 framework。
3. Service → Variables，逐一填入（值同你本機 `.env`）：

   | 變數 | 值 |
   |---|---|
   | `BFX_API_KEY` | Bitfinex key（只開 Account/Wallets 讀、Margin Funding 讀寫，**不開提幣**）|
   | `BFX_API_SECRET` | Bitfinex secret |
   | `TELEGRAM_BOT_TOKEN` | 同本機 |
   | `TELEGRAM_CHAT_ID` | 同本機 |
   | `SUPABASE_URL` | 同本機 |
   | `SUPABASE_SERVICE_KEY` | `service_role` key（伺服器端，勿外流）|
   | `DRY_RUN` | **先填 `true`**（觀察驗證），確認無誤再改 `false` |
   | `LENDING_MAX_USD` | 選填；USD 全部放貸中＋掛單中的本金上限。留白不限制；`0` 停止新增 |
   | `LENDING_MAX_USDT` | 選填；USDT 全部放貸中＋掛單中的本金上限（Bitfinex 幣別為 `fUST`）|
   | `LONG_TERM_MAX_AMOUNT` | 選填；每個幣別所有 120 天掛單＋放貸的固定金額上限（FRR／固定都算，預設 `1000`）|
   | `LONG_TERM_MAX_USD` | 選填；USD 的 120 天部位上限，優先於舊共用設定；`0` 不新增120天部位 |
   | `LONG_TERM_MAX_USDT` | 選填；USDT 的 120 天部位上限，優先於舊共用設定；`0` 不新增120天部位 |

4. Deploy，看 Logs 出現 `啟動：觀察模式` + `Supabase：已連接｜Telegram：已連接`。

> ⚠️ **絕對不要本機與 Zeabur 同時跑！** 單例鎖只擋同一台機器，擋不到跨機；
> 兩個實例會同時下單、Telegram long-polling 互相搶（回 409）。務必照下方 SOP 乾淨切換。

**本機 → Zeabur 乾淨切換 SOP**
1. （無風險）Zeabur 先用 `DRY_RUN=true` 部好、設好所有 env，但**先別停本機**。
2. **停掉本機機器人**（關掉那個背景 process）。此時只有 Zeabur 在跑、且是觀察模式
   → 不會動你的單，交易所上既有掛單原封不動繼續生息。
3. 看 Zeabur Logs／Telegram：啟動訊息有到、`/status` 有回應、Supabase 有更新 → 代表 env 全對。
4. Zeabur Variables 把 `DRY_RUN` 改成 `false` → Redeploy。機器人開始真實接管。
5. Telegram 收到「真實模式」啟動訊息後，**本機保持關閉**，切換完成。

### 5. GitHub Pages（網頁）
1. `web/config.js` 填入 Supabase URL + anon key 後 commit
2. GitHub repo → Settings → Pages → Source 選 **GitHub Actions**
3. push 到 main 自動部署（workflow 在 `.github/workflows/pages.yml`）
4. 手機開 `https://<帳號>.github.io/<repo>/`，輸入 Dashboard 密碼

> ⚠️ 用 GitHub Actions 部署 Pages，repo 可以維持 **private**，
> 但 Pages 網址本身是公開的——個人數據有密碼（token）保護，市場數據本來就公開。

## Telegram 快捷選單

常用查詢：`/status`（狀態、餘額與額度）、`/rates`（利率）、`/earnings`（收益）、
`/review`（昨日檢討）、`/longcap`（120天額度）、`/help`（全部指令）。
`/capital` 同步資金變動，`/learning` 查子帳戶最後觀測資料，`/pause`／`/resume` 控制自動掛單。

環境已提供 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 時，可只設定指定聊天室的選單與底部鍵盤：

```bash
python tools/setup_telegram_menu.py --check
python tools/setup_telegram_menu.py --apply
```

此工具不啟動引擎或 `getUpdates`，不會與 Zeabur 的輪詢搶更新。
`--apply` 會更新該 chat 的指令選單並送出一則快捷鍵訊息，底部六個按鈕都是查詢指令；
暫停／恢復另放在指令選單。Telegram 會保存選單，無須每次部署重設。
需要允許連線到 `api.telegram.org`；金鑰只從系統環境讀取，勿貼到聊天或指令列。

## 策略調整

### 總放貸上限與出金

Zeabur Variables 可設定 `LENDING_MAX_USD` 和 `LENDING_MAX_USDT`，修改後**重新部署／重啟服務**才會載入。
未設定或留白維持原本不限制總本金的行為；`0` 停止該幣別新增放貸。值須是非負數字，
例如 `5000`（不含千分位逗號）；無效值會阻止啟動，避免錯誤設定意外變成無上限。
Telegram `/status` 可確認已載入的各幣別總上限。

上限包含**所有放貸中＋掛單中**的本金（含階梯、FRR、120 天固定單，以及帳戶上可讀取的手動單）。
自動掛單、Telegram `/go` 與 `/lend` 都受限制。120 天部位另受下方長期上限限制；
總本金與長期上限同時生效。

例如放貸錢包有 10,000 USD，想保留 5,000 供出金，設 `LENDING_MAX_USD=5000`：

- 目前已放貸 10,000：不提前終止放貸；本金回來後，超出上限的部分不再續掛。
- 放貸中仍有 7,000：回流的 3,000 全部留在可用餘額。
- 放貸中降到 4,000：最多補掛 1,000，剩下 5,000 留在可用餘額。
- 放貸＋掛單已超額：下一輪先撤回超額未成交單（優先最新單）；必要時整筆撤回，
  再於剩餘額度內重掛。已成交部位只能等待借款人還款，無法保證特定出金日期。

讀取帳戶或確認撤單失敗時，不會把未知／尚未釋放的資金視為新額度。觀察模式只記錄建議，
不真的撤單。`/pause` 保持既有掛單不動；若要透過降額收回掛單，需讓自動循環處於恢復狀態。
服務重啟前或撤單執行前仍可能成交；Bitfinex 上其他服務／手動操作也可能新增部位，
本功能不是交易所層級的帳戶硬限制。
機器人只使用 funding 放貸錢包，不會自動搬動交易錢包資金或提領。

### 分幣別 120 天部位上限

Zeabur 可分別設定 `LONG_TERM_MAX_USD`、`LONG_TERM_MAX_USDT`，例如：

```env
LENDING_MAX_USD=10000
LENDING_MAX_USDT=6000
LONG_TERM_MAX_USD=1000
LONG_TERM_MAX_USDT=500
```

代表 USD 全部放貸＋掛單最多 10,000，其中 120 天 FRR／固定部位最多 1,000；
USDT 全部最多 6,000，其中 120 天部位最多 500。變更後重新部署／重啟服務，
Telegram `/status` 或 `/longcap` 可確認載入結果。

優先順序：該幣別 `LONG_TERM_MAX_USD`／`LONG_TERM_MAX_USDT` → 舊共用
`LONG_TERM_MAX_AMOUNT` → 舊別名 `FRR_MAX_AMOUNT` → `config.yaml`（預設每幣別 1,000）。
分幣別欄位留白表示沿用共用預設；`0` 表示不新增該幣別 120 天部位。
長期上限降額不會強制撤回已掛／已放貸的長期部位，等曝險降低後才可再增加。
若要收回未成交掛單以準備出金，使用前述 `LENDING_MAX_*` 總本金上限。

Telegram `/longcap USD 1000`、`/longcap USDT 500` 可暫時改單一幣別；
舊指令 `/longcap 1000` 同時修改兩幣別，並取代當次執行中的分幣別覆寫，重啟後回到 Zeabur 設定。

### 120 天分批投入

每幣別預設**單筆最多 1,000、滾動 30 分鐘最多送出 1,000 本金**，FRR、固定 120 天階梯、
Telegram `/go` 與 `/lend` 共用額度。提高 `LONG_TERM_MAX_USDT=10000` 只提高長貸總上限，
不會一次用完；後續仍須有可用餘額、長貸剩餘空間及市場觸發才加碼。
未用窗口額度不累積。撤單、提前還款或送單失敗都不退回當次窗口額度，避免 API 逾時但
交易所已接受時重複加碼；這是對機器人送單路徑的限制，不是交易所對其他手動操作的限制。

Zeabur 可選填以下環境變數（留白採 YAML 預設，修改後重新部署）：

```env
LONG_TERM_MAX_PER_OFFER=1000
LONG_TERM_BATCH_AMOUNT=1000
LONG_TERM_BATCH_MINUTES=30
```

單筆與窗口本金設 `0` 可停止新增長單；窗口分鐘必須大於 `0`。兩幣別獨立計算。
**每次重啟後長貸先等待 30 分鐘**（或設定的窗口時間），避免反覆部署繞過限制；
正常 2／30 天階梯照常運作。`/status` 顯示分批設定與目前窗口剩餘額度。
已成交部位無法事後拆單，也不保證拆開的掛單會由不同借款人承接或提早還款。
當階梯選出 120 天但分批／長貸額度已滿時，該部分暫不掛單，沒有強制降天期或降價。

### 一般階梯的小額與追高訊號

低於最小掛單額的檔位併入較低利率檔；第一檔不足時仍保留基檔利率／天期，尾款不再閒置。
例如 229.60 只掛一筆 229.60 基檔；500 拆成 250 基檔與 250 中檔。
一般階梯的 spike 只比較 **2–30 天成交最高利率與 2–30 天 IQM**，60／120 天行情另供長貸判斷。
錨點公式、24 小時價格保底、正常 50／30／20 權重與原有天期門檻維持原設定。
訊號仍以 API 回傳的近期成交樣本判斷，不代表完整回放所有 15 分鐘成交。

### Dashboard 時間範圍

每日收益、每日實際年化各有 **7／30／90 天／全部** 切換，預設近 30 天。
日期沿用後端收益紀錄的台北日期，包含今天與前 N−1 天；費用口徑、帳戶切換與刷新保留所選範圍。
「全部」使用含年份的日期標籤。總覽新增掛單本金、可用餘額與放貸利用率；
「放貸錢包總額」不包含交易錢包。

市場區最上方的機器人錨點年化公開顯示；只包含時間、幣別與市場推導年化。
每幣別左側 K 線可選 2–30／2／30 天，右側固定 120 天；兩張圖共用 K 棒週期控制。
120 天成交可能包含浮動 FRR，不能直接視為相同利率的固定單成交機會。

持續更新公開錨點須先在 Supabase SQL Editor 執行
[`supabase/migrations/015_public_market_anchors.sql`](supabase/migrations/015_public_market_anchors.sql)。
新 RPC 不需 Dashboard 密碼；既有 RLS 與個人資料密碼保護維持原設定。
未安裝時使用 `web/public-anchors.json` 歷史備援，畫面明確標示資料日期；不會自動更新。
開發環境有 `Dashboard_Password` 或 `DASHBOARD_PASSWORD` 時可執行
`python tools/export_public_anchors.py` 更新此備援，工具只匯出三個公開欄位。

### 策略參數

都在 `config.yaml`：階梯檔位/利率倍率、天期門檻、spike 靈敏度、
重掛時間、最低年化底線。改完重啟即生效，參數意義見檔內註解與 DESIGN.md。

## 風險提醒

- 放貸年化隨市場波動（牛市 15-30%+，平靜期可能 <5%），無法保證固定報酬
- 資金放在交易所有交易所風險，請自行評估投入比例
- 先用觀察模式跑幾天，確認決策合理再開真實模式
