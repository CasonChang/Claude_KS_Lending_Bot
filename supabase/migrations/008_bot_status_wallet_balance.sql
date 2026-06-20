-- ═══════════════════════════════════════════════════════════════
-- 008 bot_status 加 wallet_balance 欄位
-- 用途：存 Bitfinex funding 錢包的「真實總餘額」(w[2] BALANCE)，
--       含放貸本金 + 掛單預留 + 未結算利息，是「錢包總額」的權威值。
-- 為什麼：原本網頁用「可用 + 放貸 + 掛單」三塊相加，撤單/掛單當下三塊讀取時間點不同
--         （撤掉的單還在掛單清單、錢卻已回到可用）→ 同筆錢算兩次 → 總額在刷新間跳動；
--         且不含未結算利息，會跟 app 顯示差一截。改存單一原子讀取的 wallet_balance 即解。
-- 安裝：Supabase SQL Editor 貼上執行一次。dashboard_data RPC 用 to_jsonb(bot_status)
--       會自動帶出新欄位，不必改 RPC。
-- ═══════════════════════════════════════════════════════════════

alter table bot_status add column if not exists wallet_balance double precision;
