const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function marketPage(responses = []) {
  const elements = new Map(), charts = [], requests = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {id, textContent: '', innerHTML: ''});
    return elements.get(id);
  };
  class Chart {static defaults = {}; constructor() {} destroy() {}}
  class WebSocket {
    static OPEN = 1;
    constructor() {this.readyState = 0; this.sent = [];}
    send(data) {this.sent.push(JSON.parse(data));}
    open() {this.readyState = 1; this.onopen();}
    receive(data) {this.onmessage({data: JSON.stringify(data)});}
    close() {this.readyState = 3;}
  }
  const context = vm.createContext({
    Chart, WebSocket, Date, AbortSignal, console, setTimeout: () => {},
    window: {APP_CONFIG: {SUPABASE_URL: 'https://example.test', SUPABASE_ANON_KEY: 'public-anon'}},
    document: {getElementById: element, querySelectorAll: () => []},
    fetch: async (url, options) => {requests.push({url, options}); return responses.shift();},
    LightweightCharts: {
      CrosshairMode: {Normal: 0},
      createChart: el => {
        const series = {data: [], updates: [], setData(data) {this.data = data;}, update(data) {this.updates.push(data);}};
        const chart = {el, series, addCandlestickSeries: () => series, subscribeCrosshairMove() {},
          timeScale: () => ({setVisibleLogicalRange() {}, fitContent() {}})};
        charts.push(chart); return chart;
      },
    },
  });
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  vm.runInContext(source.split('// ═══════════ 初始化 ═══════════')[0], context);
  const run = code => vm.runInContext(code, context);
  run('buildMarketDOM(); startMarket(); market.ws.open();');
  return {run, charts, requests, elements, ws: () => run('market.ws')};
}

const snapshot = [[2000, .0002, .0003, .0004, .0001, 1000], [1000, .0001, .0002, .0003, .0001, 500]];
const plain = value => JSON.parse(JSON.stringify(value));

test('four distinct public candle subscriptions feed their own short and 120-day charts', () => {
  const page = marketPage();
  assert.equal(page.charts.length, 4);
  const keys = page.ws().sent.filter(m => m.channel === 'candles').map(m => m.key);
  assert.deepEqual(keys, ['trade:1h:fUSD:a30:p2:p30', 'trade:1h:fUSD:p120', 'trade:1h:fUST:a30:p2:p30', 'trade:1h:fUST:p120']);
  for (const [index, key] of keys.entries()) {
    page.ws().receive({event: 'subscribed', channel: 'candles', chanId: index + 10, key});
    page.ws().receive([index + 10, snapshot]);
  }
  assert(page.charts.every(c => c.series.data.length === 2));
  assert.equal(page.charts[0].series.data[0].open, page.run('dailyToApy(.0001)'));
  assert(page.elements.get('marketSections').innerHTML.includes('120 天成交'));
  assert(!page.elements.get('marketSections').innerHTML.includes('掛單簿深度'));
});

test('short period switch clears old data and cannot change the 120-day subscription', () => {
  const page = marketPage();
  page.ws().receive({event: 'subscribed', channel: 'candles', chanId: 1, key: 'trade:1h:fUSD:a30:p2:p30'});
  page.ws().receive([1, snapshot]);
  page.run('switchPeriod("fUSD", "p2")');
  assert.equal(page.charts[0].series.data.length, 0);
  assert.equal(page.ws().sent.at(-1).key, 'trade:1h:fUSD:p2');
  page.ws().receive([1, snapshot]); // unsubscribe 的確認尚未到達
  assert.equal(page.charts[0].series.data.length, 0);
  page.ws().receive({event: 'subscribed', channel: 'candles', chanId: 3, key: 'trade:1h:fUSD:a30:p2:p30'});
  assert.deepEqual(page.ws().sent.at(-1), {event: 'unsubscribe', chanId: 3});
  page.run('switchPeriod("fUSD", "p120")'); // 右側固定，左側不接受120天
  assert.equal(page.run('market.states.fUSD.pkey'), 'p2');
  assert.equal(page.run('market.states.fUSD.charts.long.key'), 'trade:1h:fUSD:p120');
});

test('timeframe switch changes both panels and reconnect preserves the user choices', () => {
  const page = marketPage();
  page.run('switchPeriod("fUSD", "p30"); switchTf("fUSD", "6h")');
  assert.deepEqual(page.ws().sent.slice(-2).map(m => m.key), ['trade:6h:fUSD:p30', 'trade:6h:fUSD:p120']);
  page.run('startMarket(); market.ws.open();');
  assert.equal(page.charts.length, 4); // 不重複建立 chart
  assert.equal(page.run('market.states.fUSD.charts.short.key'), 'trade:6h:fUSD:p30');
  assert.equal(page.run('market.states.fUSD.charts.long.key'), 'trade:6h:fUSD:p120');
});

test('public anchors load without a dashboard password and whitelist only market fields', async () => {
  const row = {ts: '2026-10-09T00:00:00Z', symbol: 'fUSD', anchor_apy: 7.5, wallet_balance: 12345};
  const page = marketPage([{ok: true, json: async () => ({snapshots: [row]})}]);
  await page.run('loadPublicAnchors()');
  assert.equal(page.requests.length, 1);
  assert(page.requests[0].url.endsWith('/public_anchor_data'));
  assert.equal(page.requests[0].options.body, '{}');
  assert(!page.requests[0].url.includes('dashboard_data'));
  assert.deepEqual(plain(page.run('anchorSnaps')), [{ts: row.ts, symbol: row.symbol, anchor_apy: 7.5}]);
});

test('missing public RPC falls back to labeled historical data', async () => {
  const row = {ts: '2026-10-09T00:00:00Z', symbol: 'fUST', anchor_apy: 8};
  const page = marketPage([{ok: false}, {ok: true, json: async () => ({snapshots: [row]})}]);
  await page.run('loadPublicAnchors()');
  assert.equal(page.requests[1].url, 'public-anchors.json');
  assert(page.elements.get('anchorStatus').textContent.includes('歷史快照'));
  assert.equal(page.run('anchorSnaps.length'), 1);
});

test('public anchor chart is above the personal password section in the real HTML', () => {
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  assert.equal((html.match(/id="anchorChart"/g) || []).length, 1);
  assert(html.indexOf('id="anchorChart"') < html.indexOf('id="lockPanel"'));
});
