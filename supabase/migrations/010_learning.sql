-- ═══════════════════════════════════════════════════════════════
-- 010 學習模式：子帳戶唯讀側錄（外部專業策略） vs 主帳戶（我們的策略）
--
-- 資料由 lendbot/observer.py（LEARNING_ENABLED=1 時啟動）寫入：
--   learning_status    ：子帳戶「現況」單列 upsert（每次輪詢更新，網頁看最後觀測時間）
--   learning_snapshots ：每 15 分鐘完整快照（含市場 view 與我們的影子決策）
--   learning_events    ：掛單/放貸「變動事件」（開單/撤單/成交/部分成交/結束）
--   learning_earnings  ：子帳戶每日利息（ledger category 28）
--   learning_reviews   ：每日學習檢討（agent 產出，tools/post_learning_review.py 上傳）
--
-- 網頁 web/learn.html 用 learning_data(token) RPC 讀（同 Dashboard 密碼）。
-- 安裝：Supabase SQL Editor 貼上執行一次。
-- ═══════════════════════════════════════════════════════════════

create table if not exists learning_status (
  symbol text primary key,
  ts timestamptz not null,
  wallet_total numeric,
  available numeric,
  lent_total numeric,
  lent_count int,
  offers_count int,
  weighted_apy numeric,          -- 放貸中加權年化（稅前，%）
  offers jsonb,                  -- [{id, amount, rate, apy, period, created}]
  credits jsonb,                 -- [{id, amount, rate, apy, period, opened}]
  shadow jsonb,                  -- 我們的影子決策 [{amount, rate, apy, period}]（最近一次快照時計算）
  market jsonb                   -- {anchor_apy, frr_apy, iqm_apy, best_ask_apy, floor_apy, spike}
);

create table if not exists learning_snapshots (
  id bigserial primary key,
  ts timestamptz not null,
  symbol text not null,
  wallet_total numeric,
  available numeric,
  lent_total numeric,
  lent_count int,
  offers_count int,
  weighted_apy numeric,
  offers jsonb,
  credits jsonb,
  shadow jsonb,
  market jsonb
);
create index if not exists learning_snapshots_ts on learning_snapshots (ts desc);

create table if not exists learning_events (
  id bigserial primary key,
  ts timestamptz not null,
  event text not null,           -- offer_new / offer_canceled / offer_filled /
                                 -- offer_partial_fill / credit_new / credit_closed
  symbol text not null,
  offer_id bigint,               -- Bitfinex offer/credit id
  amount numeric,
  rate numeric,                  -- 日利率
  apy numeric,                   -- 年化 %（顯示用）
  period int,
  detail jsonb                   -- 附加資訊（held_days、部分成交前後金額、backfill 等）
);
create index if not exists learning_events_ts on learning_events (ts desc);

create table if not exists learning_earnings (
  date date not null,
  currency text not null,
  amount numeric not null,       -- 當日實收利息（已扣 15% 手續費的入帳值）
  balance numeric,               -- 入帳後餘額快照
  primary key (date, currency)
);

create table if not exists learning_reviews (
  date date primary key,         -- 檢討覆蓋的「Bitfinex 結算日」（UTC 日）
  title text,
  body_md text not null,
  metrics jsonb,
  created_at timestamptz default now()
);

-- RLS：全部擋掉 anon 直讀（service key 繞過 RLS 寫入；網頁一律走 RPC + token）
alter table learning_status enable row level security;
alter table learning_snapshots enable row level security;
alter table learning_events enable row level security;
alter table learning_earnings enable row level security;
alter table learning_reviews enable row level security;

-- ═══ RPC：learning_data(token)（同 dashboard_data 的密碼驗證）═══

create or replace function learning_data(p_token text)
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
    -- 主帳戶（沿用正式 bot 寫的表）
    'statuses', (
      select coalesce(jsonb_agg(to_jsonb(b) order by b.symbol), '[]'::jsonb)
      from bot_status b
    ),
    'main_earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from earnings e
    ),
    'main_actions', (
      select coalesce(jsonb_agg(to_jsonb(a) order by a.ts desc), '[]'::jsonb)
      from (
        select ts, action, detail from actions_log
        where action in ('submit', 'submit(manual)', 'cancel', 'fill',
                         'closed_early', 'closed_matured')
        order by ts desc limit 300
      ) a
    ),
    -- 子帳戶（觀察者寫的表）
    'learning_status', (
      select coalesce(jsonb_agg(to_jsonb(l) order by l.symbol), '[]'::jsonb)
      from learning_status l
    ),
    'learning_snapshots', (
      -- 趨勢圖用：近 7 天、去掉厚重 jsonb 欄位
      select coalesce(jsonb_agg(jsonb_build_object(
               'ts', s.ts, 'symbol', s.symbol,
               'wallet_total', s.wallet_total, 'available', s.available,
               'lent_total', s.lent_total, 'lent_count', s.lent_count,
               'offers_count', s.offers_count, 'weighted_apy', s.weighted_apy)
               order by s.ts), '[]'::jsonb)
      from learning_snapshots s
      where s.ts > now() - interval '7 days'
    ),
    'learning_events', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.ts desc), '[]'::jsonb)
      from (
        select ts, event, symbol, offer_id, amount, rate, apy, period, detail
        from learning_events
        order by ts desc limit 400
      ) e
    ),
    'learning_earnings', (
      select coalesce(jsonb_agg(to_jsonb(e) order by e.date), '[]'::jsonb)
      from learning_earnings e
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
