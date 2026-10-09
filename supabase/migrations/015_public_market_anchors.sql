-- SQL Editor 執行一次。只公開市場推導的錨點，不公開帳戶狀態／金額／動作。
-- 保留既有資料表 RLS 與 dashboard_data 的密碼檢查。
create or replace function public.public_anchor_data()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select jsonb_build_object('snapshots', coalesce(jsonb_agg(
    jsonb_build_object('ts', s.ts, 'symbol', s.symbol, 'anchor_apy', s.anchor_apy)
    order by s.ts, s.symbol), '[]'::jsonb))
  from (
    select distinct on (symbol, floor(extract(epoch from ts) / 600))
           ts, symbol, anchor_apy
    from public.market_snapshots
    where ts > now() - interval '7 days' and ts <= now()
      and symbol in ('fUSD', 'fUST')
    order by symbol, floor(extract(epoch from ts) / 600), ts desc
  ) s;
$$;
revoke all on function public.public_anchor_data() from public;
grant execute on function public.public_anchor_data() to anon;
notify pgrst, 'reload schema';
