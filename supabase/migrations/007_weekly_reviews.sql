-- ═══════════════════════════════════════════════════════════════
-- 007 每週檢討（weekly reviews）
-- 用途：每週末產出的放貸檢討「重點整理 + 優化方向」，存 DB 給網頁讀。
-- 安裝：Supabase Dashboard → SQL Editor → 貼上整份執行（只需一次）。
-- 之後 agent 用 service_role key 直接 upsert，不必再手動。
-- ═══════════════════════════════════════════════════════════════

create table if not exists weekly_reviews (
  week       text primary key,          -- 該週起始日，例 '2026-06-13'（使用者的一週：週六～週五）
  period     text not null,             -- 顯示用區間，例 '06/13(六)–06/19(五)'
  title      text,                      -- 一句話重點
  body_md    text not null,            -- markdown 全文（重點整理 + 優化方向）
  metrics    jsonb,                     -- 結構化指標（給未來做趨勢用）
  created_at timestamptz not null default now()
);

-- 與其他表一致：開 RLS、不給 anon 直接讀（只能透過 dashboard_data RPC 經 token 驗證）
alter table weekly_reviews enable row level security;

-- ── 擴充 dashboard_data RPC：多回一個 weekly_reviews 欄位 ──────────
-- （內容同 schema.sql，僅在最後新增 weekly_reviews；token 驗證邏輯不變）
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
