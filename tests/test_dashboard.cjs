// node --test tests/test_dashboard.cjs
// 執行真正的圖表資料轉換；Chart / DOM 僅用替身，無須登入或網路。
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function dashboard() {
  const charts = [];
  class Chart {
    static defaults = {};
    constructor(element, config) { charts.push({ element, config }); }
    destroy() {}
  }
  const fixedNow = Date.parse('2026-10-09T08:00:00Z');
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [fixedNow])); }
    static now() { return fixedNow; }
  }
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { id });
    return elements.get(id);
  };
  const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  const ranges = {};
  for (const id of ['earningsRange', 'apyRange']) {
    const block = html.match(new RegExp(`<div class="tf-btns" id="${id}">([\\s\\S]*?)</div>`));
    ranges[id] = Array.from(block?.[1].matchAll(/<button class="([^"]+)" data-days="([^"]+)">/g) || [], (match) => {
      const classes = new Set(match[1].split(' '));
      const listeners = {};
      return {
        dataset: { days: match[2] },
        classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), contains: (name) => classes.has(name) },
        addEventListener: (event, listener) => { listeners[event] = listener; },
        click: () => listeners.click(),
      };
    });
  }
  const context = vm.createContext({
    Chart, Date: FixedDate, window: { APP_CONFIG: {} },
    document: { getElementById: element, querySelectorAll: (selector) => ranges[selector.split(' ')[0].slice(1)] || [] },
  });
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  vm.runInContext(source.split('// ═══════════ 初始化 ═══════════')[0], context);
  return {
    run: (code) => vm.runInContext(code, context),
    charts,
    element,
    ranges,
    initializeRanges: () => vm.runInContext(source.slice(source.indexOf('document.querySelectorAll("#earningsRange .tf")'), source.indexOf('// 切換費用口徑')), context),
  };
}

const earnings = [
  { date: '2026-10-08', currency: 'USD', account: 'main', balance: 10000 },
  { date: '2026-10-08', currency: 'UST', account: 'main', balance: 6000 },
];

test('wallet trend combined view sums funding balances', () => {
  const page = dashboard();
  page.run(`walletTrendDays = 0; drawWalletTrendChart(${JSON.stringify(earnings)});`);
  const chart = page.charts.at(-1).config;
  assert.equal(chart.data.datasets[0].data[0], 16000);
  assert.equal(chart.options.plugins.legend.display, false);
});

const datedEarnings = ['2026-01-01', '2026-07-12', '2026-09-09', '2026-09-10', '2026-10-02', '2026-10-03', '2026-10-09']
  .map((date) => ({ date, currency: 'USD', account: 'main', amount: 2, balance: 10002 }));

test('both daily charts default to the last 30 Taipei dates rather than full history', () => {
  const page = dashboard();
  page.run(`drawEarningsChart(${JSON.stringify(datedEarnings)});
            drawDailyApyChart(${JSON.stringify(datedEarnings)});`);
  for (const chart of page.charts) {
    assert.deepEqual(Array.from(chart.config.data.labels), ['09-10', '10-02', '10-03', '10-09']);
  }
  assert.equal(page.charts[0].config.data.datasets[0].data[0], 2);
  assert.equal(page.charts[1].config.data.datasets[0].data[0], 7.3);
});

test('7 day filter includes precisely today and the previous 6 Taipei dates', () => {
  const page = dashboard();
  page.run(`drawEarningsChart(${JSON.stringify(datedEarnings)});
            earningsRangeDays = 7; renderEarningsChart();
            drawDailyApyChart(${JSON.stringify(datedEarnings)});
            apyRangeDays = 7; renderDailyApyChart();`);
  assert.deepEqual(Array.from(page.charts[1].config.data.labels), ['10-03', '10-09']);
  assert.deepEqual(Array.from(page.charts[3].config.data.labels), ['10-03', '10-09']);
});

test('90 days and all history remain available with unambiguous all-history dates', () => {
  const page = dashboard();
  page.run(`drawEarningsChart(${JSON.stringify(datedEarnings)});
            earningsRangeDays = 90; renderEarningsChart();
            earningsRangeDays = 0; renderEarningsChart();
            drawDailyApyChart(${JSON.stringify(datedEarnings)});
            apyRangeDays = 0; renderDailyApyChart();`);
  assert.equal(page.charts[1].config.data.labels[0], '07-12');
  assert.deepEqual(Array.from(page.charts[2].config.data.labels), datedEarnings.map((e) => e.date));
  assert.deepEqual(Array.from(page.charts[4].config.data.labels), datedEarnings.map((e) => e.date));
});

test('refresh and fee/split switches preserve the selected range and fee calculation', () => {
  const page = dashboard();
  page.run(`drawDailyApyChart(${JSON.stringify(datedEarnings)});
            apyRangeDays = 7; apyFeeMode = 'gross'; apyViewMode = 'split';
            drawDailyApyChart(${JSON.stringify(datedEarnings)});`);
  const config = page.charts.at(-1).config;
  assert.deepEqual(Array.from(config.data.labels), ['10-03', '10-09']);
  assert.equal(config.data.datasets[0].data[0], 8.59);
});

test('empty date range is safe and Taipei rollover matches the stored ledger date', () => {
  const page = dashboard();
  assert.equal(page.run(`earningsInRange([{date:'2026-10-09'}], 1, Date.parse('2026-10-08T15:59:00Z')).length`), 0);
  assert.equal(page.run(`earningsInRange([{date:'2026-10-09'}], 1, Date.parse('2026-10-08T16:00:00Z')).length`), 1);
  page.run('drawEarningsChart([]); drawDailyApyChart([]);');
  assert.equal(page.charts[0].config.data.labels.length, 0);
  assert.equal(page.charts[1].config.data.labels.length, 0);
});

test('funds summary distinguishes pending and available money and shows lending utilization', () => {
  const page = dashboard();
  page.run(`renderFundsSummary([
    {wallet_balance:10000, total_lent:8000, available:500, offers:[{amount:1500}], weighted_apy:10},
    {wallet_balance:6000, total_lent:4000, available:1000, offers:[{amount:1000}], weighted_apy:12}
  ]);`);
  assert.equal(page.element('dWallet').textContent, '$16,000');
  assert.equal(page.element('dLent').textContent, '$12,000');
  assert.equal(page.element('dOffered').textContent, '$2,500');
  assert.equal(page.element('dAvailable').textContent, '$1,500');
  assert.equal(page.element('dUtilization').textContent, '放貸利用率 75.0%');
  assert.equal(page.element('dEstApy').textContent, '6.80%');
});

test('empty funding summary never displays NaN utilization', () => {
  const page = dashboard();
  page.run('renderFundsSummary([]);');
  assert.equal(page.element('dWallet').textContent, '$0');
  assert.equal(page.element('dUtilization').textContent, '放貸利用率 —');
});

test('the actual range buttons redraw the matching chart and update active state', () => {
  const page = dashboard();
  page.run(`drawEarningsChart(${JSON.stringify(datedEarnings)}); drawDailyApyChart(${JSON.stringify(datedEarnings)});`);
  page.initializeRanges();
  assert.deepEqual(page.ranges.earningsRange.map((b) => b.dataset.days), ['7', '30', '90', '0']);
  page.ranges.earningsRange[0].click();
  assert.equal(page.charts.at(-1).element.id, 'earningsChart');
  assert.deepEqual(Array.from(page.charts.at(-1).config.data.labels), ['10-03', '10-09']);
  assert.equal(page.ranges.earningsRange[0].classList.contains('active'), true);
  assert.equal(page.ranges.earningsRange[1].classList.contains('active'), false);
  assert.equal(page.run('apyRangeDays'), 30);
  page.ranges.apyRange[2].click();
  assert.equal(page.charts.at(-1).element.id, 'dailyApyChart');
  assert.equal(page.run('apyRangeDays'), 90);
  assert.equal(page.run('earningsRangeDays'), 7);
});

test('switching wallet trend to split view renders USD and USDT series', () => {
  const page = dashboard();
  page.run(`walletTrendDays = 0; drawWalletTrendChart(${JSON.stringify(earnings)});
            walletTrendMode = 'split'; renderWalletTrendChart();`);
  const chart = page.charts.at(-1).config;
  assert.equal(chart.data.datasets.length, 2);
  assert.equal(chart.data.datasets[0].label, 'USD');
  assert.equal(chart.data.datasets[1].data[0], 6000);
  assert.equal(chart.options.plugins.legend.display, true);
});

test('split wallet view distinguishes main and child accounts', () => {
  const page = dashboard();
  const rows = [...earnings, { date: '2026-10-08', currency: 'USD', account: 'child', balance: 0 }];
  page.run(`selectedAccounts.add('child'); walletTrendDays = 0; walletTrendMode = 'split';
            drawWalletTrendChart(${JSON.stringify(rows)});`);
  const chart = page.charts.at(-1).config;
  assert.equal(chart.data.datasets[0].label, '主·USD');
  assert.equal(chart.data.datasets[2].label, '子·USD');
  assert.equal(chart.data.datasets[2].data[0], 0);
});
