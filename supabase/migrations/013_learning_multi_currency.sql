-- 013 學習模式多幣別：應計序列保留 symbol，讓 learn.html 可切換 USD / USDT。
--
-- 其餘 learning_* 表原本已有 symbol/currency 欄，不需改 schema。這裡只修正 012
-- 將不同幣別按日混合聚合的問題。請在 Supabase SQL Editor 執行本檔。

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
    'statuses', (select coalesce(jsonb_agg(to_jsonb(b) order by b.symbol), '[]'::jsonb) from bot_status b),
    'main_earnings', (select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb) from earnings e where e.date > start_date),
    'main_actions', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (select ts, action, detail from actions_log
            where action in ('submit', 'submit(manual)', 'cancel', 'fill', 'closed_early', 'closed_matured')
              and ts >= start_ts order by ts desc limit 600) a
    ),
    'learning_status', (select coalesce(jsonb_agg(to_jsonb(l) order by l.symbol), '[]'::jsonb) from learning_status l),
    'learning_snapshots', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'ts', s.ts, 'symbol', s.symbol, 'wallet_total', s.wallet_total, 'available', s.available,
        'lent_total', s.lent_total, 'lent_count', s.lent_count, 'offers_count', s.offers_count,
        'weighted_apy', s.weighted_apy) order by s.ts), '[]'::jsonb)
      from learning_snapshots s where s.ts > now() - interval '7 days' and s.ts >= start_ts
    ),
    'learning_events', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.ts desc), '[]'::jsonb)
      from (select ts, event, symbol, offer_id, amount, rate, apy, period, detail
            from learning_events where ts >= start_ts order by ts desc limit 800) e
    ),
    'learning_earnings', (select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb) from learning_earnings e where e.date > start_date),
    'learning_reviews', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'date', r.date, 'title', r.title, 'body_md', r.body_md, 'metrics', r.metrics,
        'created_at', r.created_at) order by r.date desc), '[]'::jsonb)
      from (select * from learning_reviews order by date desc limit 60) r
    ),
    'main_accrual', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'day', d.day, 'symbol', d.symbol, 'gross', d.gross, 'avg_lent', d.avg_lent)
        order by d.day, d.symbol), '[]'::jsonb)
      from (select (ts at time zone 'UTC')::date as day, symbol,
                   round(avg(total_lent * weighted_rate)::numeric, 6) as gross,
                   round(avg(total_lent)::numeric, 2) as avg_lent
            from credits_snapshots where ts >= start_ts group by 1, 2) d
    ),
    'learning_accrual', (
      select coalesce(jsonb_agg(jsonb_build_object(
        'day', d.day, 'symbol', d.symbol, 'gross', d.gross, 'avg_lent', d.avg_lent,
        'avg_wallet', d.avg_wallet) order by d.day, d.symbol), '[]'::jsonb)
      from (select (ts at time zone 'UTC')::date as day, symbol,
                   round(avg(lent_total * (power(1 + coalesce(weighted_apy, 0) / 100,
                                                   1.0 / 365) - 1))::numeric, 6) as gross,
                   round(avg(lent_total)::numeric, 2) as avg_lent,
                   round(avg(wallet_total)::numeric, 2) as avg_wallet
            from learning_snapshots where ts >= start_ts group by 1, 2) d
    )
  );
end;
$$;

revoke all on function learning_data(text) from public;
grant execute on function learning_data(text) to anon;
