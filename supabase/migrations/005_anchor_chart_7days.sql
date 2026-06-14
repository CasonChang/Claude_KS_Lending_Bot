-- 005：機器人錨點年化圖 24 小時 → 近 7 天（每幣別每 10 分鐘降採樣）
-- 在 Supabase SQL Editor 直接執行整段即可。
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
    return null;  -- token 錯誤：不回任何資料
  end if;

  return jsonb_build_object(
    'statuses', (
      select coalesce(jsonb_agg(to_jsonb(b) order by b.symbol), '[]'::jsonb)
      from bot_status b
    ),
    'earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from earnings e
      where e.date > current_date - interval '30 days'
    ),
    'snapshots', (
      -- 近 7 天，每幣別每 10 分鐘取最後一筆（降採樣，避免 payload 過大）
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
      from (
        select ts, action, detail from actions_log
        order by ts desc limit 20
      ) a
    ),
    'closed_credits', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (
        select ts, action, detail from actions_log
        where action in ('closed_matured', 'closed_early')
        order by ts desc limit 500
      ) a
    )
  );
end;
$$;
