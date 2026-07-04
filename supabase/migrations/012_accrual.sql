-- ═══════════════════════════════════════════════════════════════
-- 012 應計收益：learning_data RPC 加回傳雙帳戶「每日應計」序列。
--
-- 為什麼：Bitfinex 利息是「放貸結束才結算」→ 現金入帳是塊狀的
--（2 天單可能第一天 0、第二天全額），短期看現金會失真。
-- 應計口徑 = 當日實際持倉 × 掛單利率 推算的當日賺取額，跟入帳時點無關，
-- 才是逐日公平的比較基準（網頁疊虛線用）。
--
-- 計算：從部位快照取「放貸中本金 × 加權日利率」的當日平均＝每日應計（稅前 $/日）。
--   主帳戶：credits_snapshots（約每 2 分鐘一筆，weighted_rate 已是日利率）
--   子帳戶：learning_snapshots（每 15 分鐘一筆，由 weighted_apy 反推日利率）
-- 快照密度高，平均值等同時間加權，精度足夠。
--
-- 安裝：Supabase SQL Editor 貼上執行一次（整個函式覆蓋 011 版）。
-- ═══════════════════════════════════════════════════════════════

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
  start_ts := start_date::timestamp at time zone 'UTC';

  return jsonb_build_object(
    'learning_start', start_date,
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
    ),
    -- ═══ 每日應計（稅前 $/日；day = 應計的 UTC 日）═══
    'main_accrual', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', d.day, 'gross', d.gross, 'avg_lent', d.avg_lent)
               order by d.day), '[]'::jsonb)
      from (
        select (ts at time zone 'UTC')::date as day,
               round(avg(total_lent * weighted_rate)::numeric, 6) as gross,
               round(avg(total_lent)::numeric, 2) as avg_lent
        from credits_snapshots
        where symbol = 'fUSD' and ts >= start_ts
        group by 1
      ) d
    ),
    'learning_accrual', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', d.day, 'gross', d.gross, 'avg_lent', d.avg_lent,
               'avg_wallet', d.avg_wallet)
               order by d.day), '[]'::jsonb)
      from (
        select (ts at time zone 'UTC')::date as day,
               round(avg(lent_total * (power(1 + coalesce(weighted_apy, 0) / 100,
                                             1.0 / 365) - 1))::numeric, 6) as gross,
               round(avg(lent_total)::numeric, 2) as avg_lent,
               round(avg(wallet_total)::numeric, 2) as avg_wallet
        from learning_snapshots
        where ts >= start_ts
        group by 1
      ) d
    )
  );
end;
$$;

revoke all on function learning_data(text) from public;
grant execute on function learning_data(text) to anon;
