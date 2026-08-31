-- 主 Dashboard 加入子帳戶唯讀資料，前端可選主／子／兩者合計。
-- 安裝：Supabase SQL Editor 執行一次；沿用 dashboard token，不開放資料表直接讀取。

create or replace function dashboard_data(p_token text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  stored_hash text;
begin
  select value into stored_hash from app_settings where key = 'dashboard_token_hash';
  if stored_hash is null
     or encode(digest(p_token, 'sha256'), 'hex') <> stored_hash then
    return null;
  end if;

  return jsonb_build_object(
    'statuses', (
      select coalesce(jsonb_agg(to_jsonb(b) order by b.symbol), '[]'::jsonb)
      from bot_status b
    ),
    'child_statuses', (
      select coalesce(jsonb_agg(to_jsonb(s) order by s.symbol), '[]'::jsonb)
      from learning_status s
    ),
    'earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from earnings e
    ),
    'child_earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from learning_earnings e
    ),
    'snapshots', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'ts', s.ts, 'symbol', s.symbol, 'anchor_apy', s.anchor_apy,
               'frr', s.frr, 'spike', s.spike) order by s.ts), '[]'::jsonb)
      from (
        select distinct on (symbol, floor(extract(epoch from ts) / 600))
               ts, symbol, anchor_apy, frr, spike
        from market_snapshots
        where ts > now() - interval '7 days'
        order by symbol, floor(extract(epoch from ts) / 600), ts desc
      ) s
    ),
    'recent_actions', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (select ts, action, detail from actions_log order by ts desc limit 20) a
    ),
    'closed_credits', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (
        select ts, action, detail from actions_log
        where action in ('closed_matured', 'closed_early')
        order by ts desc limit 500
      ) a
    ),
    'capital_flows', (
      select coalesce(jsonb_agg(to_jsonb(f) order by f.ts desc), '[]'::jsonb)
      from (
        select ts, currency, amount, kind, description from capital_flows
        order by ts desc limit 50
      ) f
    ),
    'weekly_reviews', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'week', w.week, 'period', w.period, 'title', w.title,
               'body_md', w.body_md, 'metrics', w.metrics,
               'created_at', w.created_at) order by w.week desc), '[]'::jsonb)
      from (select * from weekly_reviews order by week desc limit 60) w
    )
  );
end;
$$;

revoke all on function dashboard_data(text) from public;
grant execute on function dashboard_data(text) to anon;
