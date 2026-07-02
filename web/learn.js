/* 策略學習對照頁（隱藏頁，主頁不放連結）
 * 主帳戶（我們的策略，bot_status/earnings/actions_log） vs
 * 子帳戶（外部專業策略，observer 唯讀側錄的 learning_* 表）。
 * 資料：Supabase RPC learning_data(token)，同一組 Dashboard 密碼。
 * 子帳戶約每分鐘觀測一次；快照/影子每 15 分 → 本頁每 60 秒自動刷新。
 */
"use strict";

const CFG = window.APP_CONFIG || {};
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "dash_token";           // 與主 Dashboard 共用同一組密碼
const SYM = "fUSD";                        // 學習期只比 USD
const CUR = "USD";

const FUNDING_FEE = 0.15;                  // Bitfinex 放貸利息抽 15%
const NET = 1 - FUNDING_FEE;
const dailyToApy = (r) => (Math.pow(1 + r, 365) - 1) * 100;
const pct = (v) => (v ?? 0).toFixed(2) + "%";
const money = (v) => "$" + (v || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

const chartColors = { grid: "#2c3644", text: "#8b98a9", main: "#4fc3f7", sub: "#ffb74d", good: "#4caf80", bad: "#ef5350" };
Chart.defaults.color = chartColors.text;
Chart.defaults.borderColor = chartColors.grid;

function fmtDate(iso) {
  return new Date(iso).toLocaleString("zh-TW",
    { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
function fmtAge(iso) {
  if (!iso) return "—";
  const min = (Date.now() - new Date(iso).getTime()) / 60000;
  if (min < 60) return `${Math.round(min)} 分鐘`;
  if (min < 1440) return `${(min / 60).toFixed(1)} 小時`;
  return `${(min / 1440).toFixed(1)} 天`;
}

// ═══════════ RPC ═══════════

async function rpcLearning(token) {
  if (!CFG.SUPABASE_URL || !CFG.SUPABASE_ANON_KEY) return { error: "未設定 Supabase" };
  try {
    const r = await fetch(`${CFG.SUPABASE_URL}/rest/v1/rpc/learning_data`, {
      method: "POST",
      headers: {
        apikey: CFG.SUPABASE_ANON_KEY,
        Authorization: `Bearer ${CFG.SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_token: token }),
    });
    if (!r.ok) return { error: `Supabase 回應 ${r.status}（RPC learning_data 可能尚未安裝：migration 010）` };
    const data = await r.json();
    if (data === null) return { error: "密碼錯誤" };
    return { data };
  } catch (e) {
    return { error: "Supabase 連線失敗" };
  }
}

async function tryUnlock(token, silent = false) {
  const { data, error } = await rpcLearning(token);
  if (error) {
    if (!silent) { $("lockError").textContent = error; $("lockError").classList.remove("hidden"); }
    if (error === "密碼錯誤") localStorage.removeItem(TOKEN_KEY);
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
  $("lockPanel").classList.add("hidden");
  $("panel").classList.remove("hidden");
  renderAll(data);
}

// ═══════════ 指標計算 ═══════════

// 一側帳戶的彙總指標。main: bot_status 的 fUSD 列；sub: learning_status 列。
// earnings: [{date, currency, amount, balance}]（amount 已是稅後入帳）
function sideMetrics(status, earnings) {
  const s = status || {};
  const offers = s.offers || [];
  const credits = s.credits || [];
  const wallet = typeof s.wallet_balance === "number" ? s.wallet_balance
    : typeof s.wallet_total === "number" ? s.wallet_total
    : (s.available || 0) + (s.total_lent || s.lent_total || 0) +
      offers.reduce((a, o) => a + (o.amount || 0), 0);
  const lent = s.total_lent ?? s.lent_total ?? 0;
  const offersAmt = offers.reduce((a, o) => a + (o.amount || 0), 0);
  const wApy = s.weighted_apy || 0;
  const avgPeriod = lent
    ? credits.reduce((a, c) => a + (c.amount || 0) * (c.period || 0), 0) / lent : 0;

  const rows = (earnings || []).filter((e) => e.currency === CUR);
  const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10); // UTC+8 日期
  const sumSince = (days) => {
    const cutoff = new Date(Date.now() - days * 86400000 + 8 * 3600000).toISOString().slice(0, 10);
    return rows.filter((e) => e.date >= cutoff).reduce((a, e) => a + (e.amount || 0), 0);
  };
  // 近 7 日實際年化（稅後）：Σ利息 ÷ 平均資金規模 × 365
  const last7 = rows.slice(-7).filter((e) => e.balance > e.amount);
  const cap7 = last7.length
    ? last7.reduce((a, e) => a + (e.balance - e.amount), 0) / last7.length : 0;
  const apy7 = cap7 ? sumSince(7) / 7 / cap7 * 365 * 100 : 0;

  return {
    wallet, lent, util: wallet ? lent / wallet * 100 : 0,
    available: s.available || 0,
    offersCount: s.offers_count ?? offers.length, offersAmt,
    creditsCount: s.credits_count ?? s.lent_count ?? credits.length,
    wApyGross: wApy, wApyNet: wApy * NET, avgPeriod,
    earnToday: rows.filter((e) => e.date === today).reduce((a, e) => a + e.amount, 0),
    earn7: sumSince(7),
    // 累計收益（自起跑）：RPC 已把 earnings 過濾到起跑日之後，這裡直接全加
    earnCum: rows.reduce((a, e) => a + (e.amount || 0), 0),
    apy7,
    ts: s.ts, offers, credits,
  };
}

// 起跑日 → 「第 N 天」（含起跑日當天算第 1 天）
function learningDayCount(startStr) {
  if (!startStr) return null;
  const start = new Date(startStr + "T00:00:00Z").getTime();
  return Math.max(1, Math.floor((Date.now() - start) / 86400000) + 1);
}

// ═══════════ 渲染 ═══════════

let lastData = null;

function renderAll(d) {
  lastData = d;
  const mainStatus = (d.statuses || []).find((s) => s.symbol === SYM);
  const subStatus = (d.learning_status || []).find((s) => s.symbol === SYM)
                    || (d.learning_status || [])[0];
  const M = sideMetrics(mainStatus, d.main_earnings);
  const S = sideMetrics(subStatus, d.learning_earnings);

  // 起跑資訊（所有對比皆自此日起算，主帳戶過往歷史不計入）
  const startStr = d.learning_start;
  const day = learningDayCount(startStr);
  const startInfo = startStr ? `｜🏁 起跑 ${startStr}（第 ${day} 天）` : "";

  // 觀察狀態（輪詢約 1 分鐘一次；超過 5 分沒更新就標紅）
  if (!subStatus) {
    $("obsBadge").textContent = "⚪ 尚未開始觀察";
    $("obsInfo").textContent = "等待 LEARNING_ENABLED 開啟＋觀察者第一筆回報" + startInfo;
  } else {
    const ageMin = (Date.now() - new Date(subStatus.ts).getTime()) / 60000;
    $("obsBadge").textContent = ageMin < 5 ? "🟢 側錄中" : "🔴 觀測中斷";
    $("obsInfo").textContent = `子帳戶最後觀測 ${fmtAge(subStatus.ts)}前（每分鐘輪詢、變動才記事件；快照/影子每 15 分）` + startInfo;
  }
  $("lastUpdate").textContent = "更新 " + new Date().toLocaleTimeString("zh-TW", { hour12: false });

  $("cBoth").textContent = money(M.wallet + S.wallet);
  $("cMain").textContent = money(M.wallet);
  $("cSub").textContent = money(S.wallet);
  $("cEarn7").innerHTML =
    `<span class="acct-main">$${M.earn7.toFixed(2)}</span> <span class="muted">vs</span> <span class="acct-sub">$${S.earn7.toFixed(2)}</span>`;

  renderCompareTable(M, S);
  renderEarnCompare(d);
  renderApyCompare(d);
  renderSubTrend(d.learning_snapshots || []);
  renderOffersTables(M, S);
  renderShadow(subStatus);
  renderCreditsTables(M, S);
  renderMainActions(d.main_actions || []);
  renderSubEvents(d.learning_events || []);
  renderReviews(d.learning_reviews || []);
}

function renderCompareTable(M, S) {
  const num = (v, f = 2) => (v || 0).toLocaleString(undefined, { maximumFractionDigits: f });
  // [label, 主顯示, 子顯示, 主值, 子值, 越大越好(true)/中性(null)]
  const rows = [
    ["錢包總額", money(M.wallet), money(S.wallet), M.wallet, S.wallet, null],
    ["放貸中金額", money(M.lent), money(S.lent), M.lent, S.lent, null],
    ["資金利用率", pct(M.util), pct(S.util), M.util, S.util, true],
    ["可用（閒置）", money(M.available), money(S.available), -M.available, -S.available, null],
    ["掛單", `${M.offersCount} 筆／${money(M.offersAmt)}`, `${S.offersCount} 筆／${money(S.offersAmt)}`, 0, 0, null],
    ["放貸筆數", `${M.creditsCount} 筆`, `${S.creditsCount} 筆`, 0, 0, null],
    ["加權年化（稅前）", pct(M.wApyGross), pct(S.wApyGross), M.wApyGross, S.wApyGross, true],
    ["加權年化（稅後實拿）", pct(M.wApyNet), pct(S.wApyNet), M.wApyNet, S.wApyNet, true],
    ["加權平均天期", `${num(M.avgPeriod, 1)} 天`, `${num(S.avgPeriod, 1)} 天`, 0, 0, null],
    ["今日收益", "$" + M.earnToday.toFixed(4), "$" + S.earnToday.toFixed(4), M.earnToday, S.earnToday, true],
    ["近 7 日收益", "$" + M.earn7.toFixed(4), "$" + S.earn7.toFixed(4), M.earn7, S.earn7, true],
    ["累計收益（自起跑）", "$" + M.earnCum.toFixed(4), "$" + S.earnCum.toFixed(4), M.earnCum, S.earnCum, true],
    ["近 7 日實際年化（稅後）", pct(M.apy7), pct(S.apy7), M.apy7, S.apy7, true],
  ];
  $("compareTable").querySelector("tbody").innerHTML = rows.map(([label, mv, sv, mnum, snum, judge]) => {
    let lead = "—";
    if (judge && (mnum || snum)) {
      lead = mnum === snum ? "＝"
        : mnum > snum ? `<span class="acct-main">主</span>` : `<span class="acct-sub">子</span>`;
    }
    return `<tr><td>${label}</td><td>${mv}</td><td>${sv}</td><td>${lead}</td></tr>`;
  }).join("");
}

// ── 每日收益 / 年化 對比圖 ──

let earnChart, apyChart, subTrendChart, subApyTrendChart;
let apyFeeMode = "net";

function seriesByDate(earnings) {
  const map = {};
  for (const e of (earnings || []).filter((x) => x.currency === CUR)) map[e.date] = e;
  return map;
}

function renderEarnCompare(d) {
  const m = seriesByDate(d.main_earnings), s = seriesByDate(d.learning_earnings);
  const dates = [...new Set([...Object.keys(m), ...Object.keys(s)])].sort().slice(-30);
  earnChart?.destroy();
  earnChart = new Chart($("earnCompareChart"), {
    type: "line",
    data: {
      labels: dates.map((x) => x.slice(5)),
      datasets: [
        { label: "主帳戶", data: dates.map((x) => m[x]?.amount ?? null),
          borderColor: chartColors.main, pointRadius: 2, borderWidth: 2, tension: 0.2, spanGaps: true },
        { label: "子帳戶", data: dates.map((x) => s[x]?.amount ?? null),
          borderColor: chartColors.sub, pointRadius: 2, borderWidth: 2, tension: 0.2, spanGaps: true },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true } },
      scales: { y: { ticks: { callback: (v) => "$" + v } } },
    },
  });
}

function dailyApy(e, feeFactor) {
  if (!e || !e.balance || e.balance <= e.amount) return null;
  return +(e.amount / (e.balance - e.amount) * 365 * 100 * feeFactor).toFixed(2);
}

function renderApyCompare(d) {
  const feeFactor = apyFeeMode === "gross" ? 1 / NET : 1;
  const m = seriesByDate(d.main_earnings), s = seriesByDate(d.learning_earnings);
  const dates = [...new Set([...Object.keys(m), ...Object.keys(s)])].sort().slice(-30);
  apyChart?.destroy();
  apyChart = new Chart($("apyCompareChart"), {
    type: "line",
    data: {
      labels: dates.map((x) => x.slice(5)),
      datasets: [
        { label: "主帳戶", data: dates.map((x) => dailyApy(m[x], feeFactor)),
          borderColor: chartColors.main, pointRadius: 2, borderWidth: 2, tension: 0.2, spanGaps: true },
        { label: "子帳戶", data: dates.map((x) => dailyApy(s[x], feeFactor)),
          borderColor: chartColors.sub, pointRadius: 2, borderWidth: 2, tension: 0.2, spanGaps: true },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true } },
      scales: { y: { ticks: { callback: (v) => v.toFixed(1) + "%" } } },
    },
  });
}

function renderSubTrend(snaps) {
  const pts = snaps.filter((s) => s.symbol === SYM);
  const timeTicks = {
    type: "linear",
    ticks: {
      maxTicksLimit: 8,
      callback: (v) => {
        const dt = new Date(v);
        return `${dt.getMonth() + 1}/${dt.getDate()} ${dt.getHours()}:${String(dt.getMinutes()).padStart(2, "0")}`;
      },
    },
  };
  subTrendChart?.destroy();
  subTrendChart = new Chart($("subTrendChart"), {
    type: "line",
    data: { datasets: [
      { label: "錢包總額", data: pts.map((s) => ({ x: new Date(s.ts).getTime(), y: s.wallet_total })),
        borderColor: chartColors.sub, pointRadius: 0, borderWidth: 2, tension: 0.15 },
      { label: "放貸中", data: pts.map((s) => ({ x: new Date(s.ts).getTime(), y: s.lent_total })),
        borderColor: chartColors.good, backgroundColor: chartColors.good + "30",
        fill: true, pointRadius: 0, borderWidth: 1.5, tension: 0.15 },
    ]},
    options: {
      plugins: { legend: { display: true } },
      scales: { x: timeTicks, y: { ticks: { callback: (v) => "$" + v.toLocaleString() } } },
    },
  });
  subApyTrendChart?.destroy();
  subApyTrendChart = new Chart($("subApyTrendChart"), {
    type: "line",
    data: { datasets: [
      { label: "子帳戶加權年化", data: pts.map((s) => ({ x: new Date(s.ts).getTime(), y: s.weighted_apy })),
        borderColor: chartColors.sub, pointRadius: 0, borderWidth: 1.5, tension: 0.2 },
    ]},
    options: {
      plugins: { legend: { display: false } },
      scales: { x: timeTicks, y: { ticks: { callback: (v) => v.toFixed(1) + "%" } } },
    },
  });
}

// ── 掛單 / 影子 / 放貸中 / 事件 ──

function offerRows(offers, withAge) {
  if (!offers?.length) return `<tr><td colspan="${withAge ? 4 : 3}" class="muted">目前沒有掛單</td></tr>`;
  const rows = offers.map((o) => `<tr><td>${money(o.amount)}</td>
    <td>${pct(o.apy ?? dailyToApy(o.rate))}</td><td>${o.period} 天</td>
    ${withAge ? `<td>${o.created ? fmtAge(o.created) : "—"}</td>` : ""}</tr>`).join("");
  const tAmt = offers.reduce((a, o) => a + (o.amount || 0), 0);
  return rows + `<tr class="total-row"><td>${money(tAmt)}</td><td colspan="${withAge ? 3 : 2}">合計 ${offers.length} 筆</td></tr>`;
}

function renderOffersTables(M, S) {
  $("offersMain").querySelector("tbody").innerHTML = offerRows(M.offers, false);
  $("offersSub").querySelector("tbody").innerHTML = offerRows(S.offers, true);
}

function renderShadow(subStatus) {
  const shadow = subStatus?.shadow || [];
  const mkt = subStatus?.market || {};
  const actual = subStatus?.offers || [];
  $("shadowActual").querySelector("tbody").innerHTML = offerRows(actual, false);
  $("shadowOurs").querySelector("tbody").innerHTML = shadow.length
    ? offerRows(shadow, false)
    : `<tr><td colspan="3" class="muted">快照當下子帳戶沒有可用資金（全掛出去了）→ 我們也無單可掛</td></tr>`;
  $("shadowMarket").textContent = mkt.anchor_apy != null
    ? `快照 ${mkt.snap_ts ? fmtAge(mkt.snap_ts) + "前" : "—"}｜市場：錨點 ${pct(mkt.anchor_apy)}・IQM ${pct(mkt.iqm_apy)}・FRR ${pct(mkt.frr_apy)}・隊首 ${pct(mkt.best_ask_apy)}・保底 ${pct(mkt.floor_apy)}${mkt.spike ? "・🔥SPIKE" : ""}`
    : "（還沒有快照）";
}

function creditRows(credits) {
  if (!credits?.length) return `<tr><td colspan="4" class="muted">目前沒有放貸中的部位</td></tr>`;
  const top = [...credits].sort((a, b) => (b.amount || 0) - (a.amount || 0)).slice(0, 12);
  const rows = top.map((c) => `<tr><td>${money(c.amount)}</td>
    <td>${pct(c.apy ?? dailyToApy(c.rate))}</td><td>${c.period} 天</td>
    <td>${c.opened ? fmtDate(c.opened) : "—"}</td></tr>`).join("");
  const tAmt = credits.reduce((a, c) => a + (c.amount || 0), 0);
  const wApy = tAmt ? credits.reduce((a, c) => a + (c.amount || 0) * (c.apy ?? dailyToApy(c.rate)), 0) / tAmt : 0;
  const more = credits.length > 12 ? `（顯示前 12 筆）` : "";
  return rows + `<tr class="total-row"><td>${money(tAmt)}</td><td>${pct(wApy)}</td>
    <td colspan="2">合計 ${credits.length} 筆 ${more}</td></tr>`;
}

function renderCreditsTables(M, S) {
  $("creditsMain").querySelector("tbody").innerHTML = creditRows(M.credits);
  $("creditsSub").querySelector("tbody").innerHTML = creditRows(S.credits);
}

const ACTION_LABEL = {
  "submit": ["掛單", "ev-open"], "submit(manual)": ["手動掛單", "ev-open"],
  "cancel": ["撤單", "ev-cancel"], "fill": ["成交", "ev-fill"],
  "closed_early": ["提前還款", "ev-close"], "closed_matured": ["到期還款", "ev-close"],
};

function renderMainActions(actions) {
  const rows = actions.filter((a) => (a.detail || {}).symbol === SYM).slice(0, 60);
  $("actionsMain").querySelector("tbody").innerHTML = rows.length
    ? rows.map((a) => {
        const d = a.detail || {};
        const [label, cls] = ACTION_LABEL[a.action] || [a.action, ""];
        const apy = d.apy ?? (d.rate != null ? dailyToApy(d.rate) : null);
        return `<tr><td>${fmtDate(a.ts)}</td><td class="${cls}">${label}</td>
          <td>${money(d.amount)}</td><td>${apy != null ? pct(apy) : "—"}</td>
          <td>${d.period ?? "—"} 天</td></tr>`;
      }).join("")
    : `<tr><td colspan="5" class="muted">還沒有紀錄</td></tr>`;
}

const EVENT_LABEL = {
  offer_new: ["掛單", "ev-open"], offer_canceled: ["撤單", "ev-cancel"],
  offer_filled: ["成交（掛單）", "ev-fill"], offer_partial_fill: ["部分成交", "ev-fill"],
  credit_new: ["放貸成交", "ev-fill"], credit_closed: ["放貸結束", "ev-close"],
};

function renderSubEvents(events) {
  const rows = events.slice(0, 60);
  $("eventsSub").querySelector("tbody").innerHTML = rows.length
    ? rows.map((e) => {
        const [label, cls] = EVENT_LABEL[e.event] || [e.event, ""];
        let extra = "";
        if (e.event === "credit_closed" && e.detail) {
          extra = e.detail.matured ? "・放滿" : `・持有 ${e.detail.held_days} 天`;
        }
        return `<tr><td>${fmtDate(e.ts)}</td><td class="${cls}">${label}${extra}</td>
          <td>${money(e.amount)}</td><td>${e.apy != null ? pct(e.apy) : "—"}</td>
          <td>${e.period ?? "—"} 天</td></tr>`;
      }).join("")
    : `<tr><td colspan="5" class="muted">還沒有事件（觀察者啟動後，掛單有變動才會記）</td></tr>`;
}

function renderReviews(reviews) {
  const tabs = $("rvTabs");
  tabs.innerHTML = "";
  if (!reviews.length) {
    $("rvBody").innerHTML = `<p class="muted">尚無檢討。每日台北 09:30 後由 agent 產出（SOP：reviews/learning/README.md）。</p>`;
    return;
  }
  reviews.forEach((rv, i) => {
    const b = document.createElement("button");
    b.className = "tf" + (i === 0 ? " active" : "");
    b.textContent = rv.date;
    b.onclick = () => {
      [...tabs.children].forEach((c, j) => c.classList.toggle("active", j === i));
      $("rvBody").innerHTML = marked.parse(rv.body_md || "");
    };
    tabs.appendChild(b);
  });
  $("rvBody").innerHTML = marked.parse(reviews[0].body_md || "");
}

// ═══════════ fUSD K 棒（公開 WebSocket，REST 沒開 CORS）═══════════

const WS_URL = "wss://api-pub.bitfinex.com/ws/2";
const TZ_SHIFT = -new Date().getTimezoneOffset() * 60;
const kState = { ws: null, tf: "1h", chanId: null, chart: null, series: null };

function mapCandle(c) {
  return { time: c[0] / 1000 + TZ_SHIFT, open: dailyToApy(c[1]), close: dailyToApy(c[2]),
           high: dailyToApy(c[3]), low: dailyToApy(c[4]) };
}

function initKChart() {
  const chart = LightweightCharts.createChart($("kchart"), {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: chartColors.text },
    grid: { vertLines: { color: chartColors.grid }, horzLines: { color: chartColors.grid } },
    timeScale: { timeVisible: true, borderColor: chartColors.grid },
    rightPriceScale: { borderColor: chartColors.grid },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { priceFormatter: (v) => v.toFixed(2) + "%" },
  });
  const series = chart.addCandlestickSeries({
    upColor: chartColors.good, downColor: chartColors.bad,
    wickUpColor: chartColors.good, wickDownColor: chartColors.bad,
    borderVisible: false,
    priceFormat: { type: "custom", formatter: (v) => v.toFixed(2) + "%", minMove: 0.01 },
  });
  chart.subscribeCrosshairMove((param) => {
    const d = param?.seriesData?.get(series);
    if (!d || d.open === undefined) {
      $("kOhlc").textContent = "（滑鼠移到 K 棒上顯示開高低收）";
      return;
    }
    const t = new Date((param.time - TZ_SHIFT) * 1000).toLocaleString("zh-TW",
      { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
    const color = d.close >= d.open ? chartColors.good : chartColors.bad;
    $("kOhlc").innerHTML = `${t}｜開 ${d.open.toFixed(2)}%｜高 ${d.high.toFixed(2)}%｜` +
      `低 ${d.low.toFixed(2)}%｜收 <b style="color:${color}">${d.close.toFixed(2)}%</b>`;
  });
  kState.chart = chart;
  kState.series = series;
}

function startKWs() {
  if (kState.ws) { kState.ws.onclose = null; kState.ws.close(); }
  const ws = new WebSocket(WS_URL);
  kState.ws = ws;
  ws.onopen = () => subscribeCandles();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (!Array.isArray(msg)) {
      if (msg.event === "subscribed" && msg.channel === "candles") kState.chanId = msg.chanId;
      return;
    }
    const [chanId, payload] = msg;
    if (chanId !== kState.chanId || payload === "hb") return;
    if (Array.isArray(payload) && Array.isArray(payload[0])) {
      const seen = new Map();
      for (const c of payload) seen.set(c[0], c);
      const data = [...seen.values()].sort((a, b) => a[0] - b[0]).map(mapCandle);
      kState.series.setData(data);
      if (data.length > 48) {
        kState.chart.timeScale().setVisibleLogicalRange({ from: data.length - 48, to: data.length + 1 });
      } else {
        kState.chart.timeScale().fitContent();
      }
    } else if (Array.isArray(payload) && typeof payload[0] === "number") {
      kState.series.update(mapCandle(payload));
    }
  };
  ws.onclose = () => setTimeout(startKWs, 3000);
}

function subscribeCandles() {
  if (kState.ws?.readyState !== WebSocket.OPEN) return;
  if (kState.chanId != null) {
    kState.ws.send(JSON.stringify({ event: "unsubscribe", chanId: kState.chanId }));
    kState.chanId = null;
  }
  kState.ws.send(JSON.stringify({ event: "subscribe", channel: "candles",
                                  key: `trade:${kState.tf}:${SYM}:a30:p2:p30` }));
}

document.querySelectorAll("#kTfs .tf").forEach((btn) =>
  btn.addEventListener("click", () => {
    if (kState.tf === btn.dataset.tf) return;
    document.querySelectorAll("#kTfs .tf").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    kState.tf = btn.dataset.tf;
    kState.series.setData([]);
    subscribeCandles();
  }));

// ═══════════ 初始化 ═══════════

$("unlockBtn").addEventListener("click", () => tryUnlock($("tokenInput").value.trim()));
$("tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") tryUnlock($("tokenInput").value.trim()); });
$("lockBtn").addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  $("panel").classList.add("hidden");
  $("lockPanel").classList.remove("hidden");
});
$("refreshBtn").addEventListener("click", async () => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (!t) return;
  const btn = $("refreshBtn");
  btn.disabled = true; btn.textContent = "⟳ 刷新中…";
  await tryUnlock(t, true);
  btn.textContent = "⟳ 刷新"; btn.disabled = false;
});
document.querySelectorAll("#apyFeeToggle .tf").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll("#apyFeeToggle .tf").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    apyFeeMode = btn.dataset.fee;
    if (lastData) renderApyCompare(lastData);
  }));

initKChart();
startKWs();

const saved = localStorage.getItem(TOKEN_KEY);
if (saved) tryUnlock(saved, true);
// 子帳戶每分鐘觀測一次 → 本頁每 60 秒自動刷新（解鎖後才會打）
setInterval(() => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t && !$("panel").classList.contains("hidden")) tryUnlock(t, true);
}, 60_000);
