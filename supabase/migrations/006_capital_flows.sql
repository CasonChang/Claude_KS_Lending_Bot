-- 006：資金變動偵測（入金/出金/兌換）。在 Supabase SQL Editor 執行整段。
-- (1) 新表 + RLS
create table if not exists capital_flows (
  id bigint primary key,            -- Bitfinex ledger entry id（去重）
  ts timestamptz not null,
  currency text not null,
  amount double precision not null,
  kind text not null,               -- 入金 / 出金 / 兌換
  description text
);
create index if not exists idx_capital_flows_ts on capital_flows (ts desc);
alter table capital_flows enable row level security;  -- 機器人用 service key 寫，繞過 RLS

-- (2) 更新 RPC，多回傳 capital_flows
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
    'earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from earnings e
      where e.date > current_date - interval '30 days'
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
    ),
    'capital_flows', (
      select coalesce(jsonb_agg(to_jsonb(f) order by f.ts desc), '[]'::jsonb)
      from (
        select ts, currency, amount, kind, description from capital_flows
        order by ts desc limit 50
      ) f
    )
  );
end;
$$;

revoke all on function dashboard_data(text) from public;
grant execute on function dashboard_data(text) to anon;
