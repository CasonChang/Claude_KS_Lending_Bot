-- ═══════════════════════════════════════════════════════════════
-- 011 學習起跑點：讓 learn.html 的對比只從「學習開始日」起算。
--
-- 為什麼：主帳戶已跑數週、earnings/actions 有歷史；子帳戶才剛開始。
-- 直接比會不公平。設一個 learning_start 錨點，learning_data RPC 只回傳
-- 起跑後的資料 → 雙方起跑點一致。
--
-- 非破壞性：不刪任何真實紀錄，只是「這個對比頁」的顯示過濾。
--   主 Dashboard（dashboard_data / index.html）完全不受影響。
--
-- 收益窗口說明：Bitfinex 利息每天 00:00 UTC 結算、入帳日期記為結算當天。
--   起跑日 D 當天(D)才開始的新放貸，利息要到 D+1 才結算入帳。
--   所以「收益」用 date > D（嚴格大於）過濾，排除掉 D 當天入帳、其實是
--   D-1(起跑前) 放貸產生的那筆利息 → 雙方第一個計入日都是 D+1，才公平。
--   事件/快照/動作則從 D 當天 00:00 UTC 起算（觀察窗口）。
--
-- 安裝：Supabase SQL Editor 貼上執行一次。
-- 改起跑日：把下面 DO 區塊的日期改掉再跑一次即可（隨時可調）。
-- ═══════════════════════════════════════════════════════════════

do $$
begin
  if exists (select 1 from app_settings where key = 'learning_start') then
    update app_settings set value = '2026-07-02' where key = 'learning_start';
  else
    insert into app_settings (key, value) values ('learning_start', '2026-07-02');
  end if;
end $$;

create or replace function learning_data(p_token text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  stored_hash text;
  start_date date;
  start_ts timestamptz;
begin
  select value into stored_hash from app_settings where key = 'dashboard_token_hash';
  if stored_hash is null
     or encode(digest(p_token, 'sha256'), 'hex') <> stored_hash then
    return null;
  end if;

  select value::date into start_date from app_settings where key = 'learning_start';
  start_date := coalesce(start_date, '2000-01-01');
  start_ts := start_date::timestamp at time zone 'UTC';  -- 起跑日 00:00 UTC

  return jsonb_build_object(
    'learning_start', start_date,
    -- 主帳戶（沿用正式 bot 寫的表；只取起跑後）
    'statuses', (
      select coalesce(jsonb_agg(to_jsonb(b) order by b.symbol), '[]'::jsonb)
      from bot_status b
    ),
    'main_earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from earnings e where e.date > start_date
    ),
    'main_actions', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (
        select ts, action, detail from actions_log
        where action in ('submit', 'submit(manual)', 'cancel', 'fill',
                         'closed_early', 'closed_matured')
          and ts >= start_ts
        order by ts desc limit 300
      ) a
    ),
    -- 子帳戶（觀察者寫的表；只取起跑後）
    'learning_status', (
      select coalesce(jsonb_agg(to_jsonb(l) order by l.symbol), '[]'::jsonb)
      from learning_status l
    ),
    'learning_snapshots', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'ts', s.ts, 'symbol', s.symbol,
               'wallet_total', s.wallet_total, 'available', s.available,
               'lent_total', s.lent_total, 'lent_count', s.lent_count,
               'offers_count', s.offers_count, 'weighted_apy', s.weighted_apy)
               order by s.ts), '[]'::jsonb)
      from learning_snapshots s
      where s.ts > now() - interval '7 days' and s.ts >= start_ts
    ),
    'learning_events', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.ts desc), '[]'::jsonb)
      from (
        select ts, event, symbol, offer_id, amount, rate, apy, period, detail
        from learning_events
        where ts >= start_ts
        order by ts desc limit 400
      ) e
    ),
    'learning_earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from learning_earnings e where e.date > start_date
    ),
    'learning_reviews', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'date', r.date, 'title', r.title, 'body_md', r.body_md,
               'metrics', r.metrics, 'created_at', r.created_at)
               order by r.date desc), '[]'::jsonb)
      from (select * from learning_reviews order by date desc limit 60) r
    )
  );
end;
$$;

revoke all on function learning_data(text) from public;
grant execute on function learning_data(text) to anon;
