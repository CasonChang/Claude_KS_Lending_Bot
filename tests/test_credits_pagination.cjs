const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function dashboard() {
  const elements = new Map();
  class Element {
    constructor(id) {this.id = id; this.innerHTML = ''; this.children = []; this.handlers = {}; this.classList = {add() {}, toggle() {}};}
    addEventListener(name, handler) {this.handlers[name] = handler;}
    appendChild(child) {this.children.push(child);}
    querySelector(selector) {
      if (selector === '.sort-arrow') return this.children[0];
      return element(this.id + ':' + selector);
    }
    querySelectorAll(selector) {
      return selector === 'thead th' ? headers : [];
    }
    click() {if (this.handlers.click) this.handlers.click(); else this.onclick?.();}
  }
  const element = id => {if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id);};
  const headers = Array.from({length: 8}, (_, i) => new Element('header-' + i));
  class Chart {static defaults = {};}
  const context = vm.createContext({Chart, Date, window: {APP_CONFIG: {}}, document: {
    getElementById: element, createElement: () => new Element('span'), querySelectorAll: () => [],
  }});
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  vm.runInContext(source.split('// ═══════════ 初始化 ═══════════')[0], context);
  const run = code => vm.runInContext(code, context);
  return {run, element, headers, rows: () => (element('creditsTable:tbody').innerHTML.match(/<tr>/g) || []).length};
}

function credits(count, account = 'main') {
  return [{symbol: 'fUSD', account, credits: Array.from({length: count}, (_, n) => ({
    amount: n + 1, rate: .0002, period: 2, remaining_days: 1,
    opened: new Date(Date.parse('2026-10-01T00:00:00Z') + n * 1000).toISOString(),
  }))}];
}

test('active loans default to ten rows while the total includes all loans on every page', () => {
  const page = dashboard();
  page.run(`renderCredits(${JSON.stringify(credits(25))});`);
  assert.equal(page.rows(), 10);
  assert(page.element('creditsTable:tbody').innerHTML.includes('全部合計 25 筆'));
  assert(page.element('creditsTable:tbody').innerHTML.includes('$325'));
  assert(page.element('creditsPager').innerHTML.includes('第 1–10 筆，共 25 筆'));
  page.element('creditsNext').click();
  assert.equal(page.rows(), 10);
  assert(page.element('creditsPager').innerHTML.includes('第 11–20 筆'));
  assert(page.element('creditsTable:tbody').innerHTML.includes('$325'));
  page.element('creditsNext').click();
  assert.equal(page.rows(), 5);
  assert(page.element('creditsPager').innerHTML.includes('第 21–25 筆'));
  page.element('creditsPrev').click();
  assert.equal(page.run('creditsPage'), 1);
});

test('sorting applies globally and returns to page one; changing page size also resets the page', () => {
  const page = dashboard();
  page.run(`renderCredits(${JSON.stringify(credits(25))});`);
  page.element('creditsNext').click();
  page.headers[1].click(); // 金額預設大到小
  assert.equal(page.run('creditsPage'), 0);
  assert.deepEqual(Array.from(page.run('creditsRows.slice(0, 3).map(c => c.amount)')), [25, 24, 23]);
  page.headers[1].click();
  assert.deepEqual(Array.from(page.run('creditsRows.slice(0, 3).map(c => c.amount)')), [1, 2, 3]);
  page.element('creditsNext').click();
  page.element('creditsPageSize').onchange({target: {value: '20'}});
  assert.equal(page.run('creditsPage'), 0);
  assert.equal(page.rows(), 20);
  page.element('creditsPageSize').onchange({target: {value: '50'}});
  assert.equal(page.rows(), 25);
});

test('refresh preserves the page and sort, clamps when loans are repaid, and clears empty pagination', () => {
  const page = dashboard();
  page.run(`renderCredits(${JSON.stringify(credits(25))});`);
  page.headers[1].click();
  page.element('creditsNext').click();
  page.run(`renderCredits(${JSON.stringify(credits(26))});`);
  assert.equal(page.run('creditsPage'), 1);
  assert.equal(page.run('creditsSort.idx'), 1);
  page.run(`renderCredits(${JSON.stringify(credits(4))});`);
  assert.equal(page.run('creditsPage'), 0);
  assert.equal(page.rows(), 4);
  page.run('renderCredits([]);');
  assert.equal(page.element('creditsPager').innerHTML, '');
  assert(page.element('creditsTable:tbody').innerHTML.includes('目前沒有放貸中的部位'));
});

test('account scope changes reset pagination and do not mix the previous account totals', () => {
  const page = dashboard();
  page.run(`renderCredits(${JSON.stringify(credits(25))});`);
  page.element('creditsNext').click();
  page.run(`selectedAccounts.clear(); selectedAccounts.add('child'); renderCredits(${JSON.stringify(credits(12, 'child'))});`);
  assert.equal(page.run('creditsPage'), 0);
  assert(page.element('creditsTable:tbody').innerHTML.includes('全部合計 12 筆'));
  assert(page.element('creditsTable:tbody').innerHTML.includes('$78'));
});
