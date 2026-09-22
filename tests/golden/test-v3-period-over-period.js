'use strict';
/**
 * v3.0: 环比/同比极值查询
 * 验证 _lastPeriodOverPeriod 触发 + executeQuery 后处理 + buildInterpretation 解读
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const ROOT = path.join(__dirname, '..', '..');
const HTML_PATH = path.join(ROOT, 'index.html');
let passed = 0, failed = 0;
function assert(cond, msg) {
  if (cond) { console.log('  ✓ ' + msg); passed++; }
  else { console.log('  ✗ ' + msg); failed++; }
}
(async () => {
  const html = fs.readFileSync(HTML_PATH, 'utf-8');
  const patched = html.replace(/let parsedData = \{/, 'var parsedData = {');
  const cleaned = patched
    .replace(/<script src="tailwindcss\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="echarts\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="papaparse\.min\.js"[^>]*><\/script>/g, '')
    .replace(/<script src="lucide\.min\.js"[^>]*><\/script>/g, '');
  const dom = new JSDOM(cleaned, { url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true, resources: 'usable' });
  const win = dom.window;
  win.tailwind = { config: {} };
  win.lucide = { createIcons: () => {}, createElement: () => null };
  win.Papa = { parse: () => ({ data: [], errors: [] }) };
  win.echarts = function () { return { setOption: () => {}, resize: () => {}, dispose: () => {}, on: () => {} }; };
  win.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  // 测试数据: 连续 5 天销售额，最后一天环比下降最大
  const rows = [
    { 日期: '2024-04-01', 销售额: 1000 },
    { 日期: '2024-04-02', 销售额: 1500 },  // 上升 +500
    { 日期: '2024-04-03', 销售额: 1200 },  // 下降 -300
    { 日期: '2024-04-04', 销售额: 800 },   // 下降 -400 ← 环比下降最大
    { 日期: '2024-04-05', 销售额: 900 }    // 上升 +100
  ];
  win.parsedData = {
    fileName: 'test.csv', rows,
    columns: ['日期', '销售额'],
    fieldInfo: [{ name: '日期', type: 'date' }, { name: '销售额', type: 'int' }]
  };
  const scriptMatches = cleaned.match(/<script>([\s\S]*?)<\/script>/g) || [];
  for (const sm of scriptMatches) {
    const code = sm.replace(/^<script>/, '').replace(/<\/script>$/, '');
    try { win.eval(code); } catch(e) {}
  }

  console.log('===== v3.0 环比/同比极值查询 =====');
  console.log('数据: 5 天销售额, 4/4 环比下降最大 (-400)');
  console.log('');

  // === Test 1: executeQuery 环比识别 ===
  console.log('--- Test 1: executeQuery 环比后处理 ---');
  win._lastQuery = '销售额环比下降最大的是哪天？';
  win._lastPeriodOverPeriod = { keyword: '环比', direction: 'decrease', field: '日期' };
  if (typeof win.executeQuery === 'function') {
    const result = win.executeQuery(rows, null, '日期', { field: '销售额' }, 'sum', null, null);
    console.log('  result:', JSON.stringify(result));
    assert(Array.isArray(result) && result.length === 1, '返回 1 行（极值日）');
    if (result && result[0]) {
      assert(result[0].日期 === '2024-04-04', '极值日期 = 4/4');
      assert(result[0]['环比变化额'] === -400, '环比变化额 = -400');
      assert(result[0].__periodOverPeriodData__ !== undefined, '含 __periodOverPeriodData__');
    }
  }
  win._lastPeriodOverPeriod = null;

  // === Test 2: buildInterpretation 环比解读 ===
  console.log('--- Test 2: buildInterpretation 解读 + 行动建议 ---');
  if (typeof win.buildInterpretation === 'function') {
    const _popResult = [{
      日期: '2024-04-04', 前日销售额: 1200, 销售额: 800, 环比变化额: -400, 环比变化率: -33.33,
      __periodOverPeriodData__: { date: '2024-04-04', current: 800, previous: 1200, diff: -400, pct: -33.33 }
    }];
    win._lastPeriodOverPeriod = { direction: 'decrease' };
    const interp = win.buildInterpretation(_popResult, '日期', { field: '销售额', label: '销售额' }, 'sum', null, null, null, '销售额环比下降最大的是哪天？');
    console.log('  解读:', interp);
    assert(/2024-04-04|4月4日/.test(interp), '含极值日期');
    assert(/1,200|1200/.test(interp), '含前日值 1200');
    assert(/800/.test(interp), '含当日值 800');
    assert(/-400|400|33/.test(interp), '含变化额/率');
    assert(/建议|检查/.test(interp), '含行动建议');
    win._lastPeriodOverPeriod = null;
  }

  // === Test 3: 环比增长最大 ===
  console.log('--- Test 3: executeQuery 环比增长最大 ---');
  win._lastQuery = '销售额环比增长最大的是哪天？';
  win._lastPeriodOverPeriod = { keyword: '环比', direction: 'increase', field: '日期' };
  if (typeof win.executeQuery === 'function') {
    const result = win.executeQuery(rows, null, '日期', { field: '销售额' }, 'sum', null, null);
    console.log('  result:', JSON.stringify(result));
    assert(Array.isArray(result) && result.length === 1, '返回 1 行');
    if (result && result[0]) {
      assert(result[0].日期 === '2024-04-02', '增长最大日 = 4/2（+500）');
      assert(result[0]['环比变化额'] === 500, '变化额 = +500');
    }
  }
  win._lastPeriodOverPeriod = null;

  // === Test 4: 对比查询归一化（含 daysUnequal 文案）===
  console.log('--- Test 4: 对比查询含日均归一化文案 ---');
  win._lastQuery = '中旬相比上旬销售额变化了多少？';
  const cmpRows = [
    { 日期: '2024-04-01', 销售额: 1000 },
    { 日期: '2024-04-02', 销售额: 1500 },
    { 日期: '2024-04-03', 销售额: 1200 },
    { 日期: '2024-04-04', 销售额: 800 },
    { 日期: '2024-04-05', 销售额: 900 },
    { 日期: '2024-04-11', 销售额: 2000 },
    { 日期: '2024-04-12', 销售额: 2500 },
    { 日期: '2024-04-13', 销售额: 1800 },
    { 日期: '2024-04-14', 销售额: 1600 },
    { 日期: '2024-04-15', 销售额: 1900 }
  ];
  win._lastComparisonTimeRanges = win.parseComparisonTimeRanges('中旬相比上旬销售额变化了多少？', '日期', cmpRows);
  if (win._lastComparisonTimeRanges && typeof win.executeQuery === 'function') {
    const result = win.executeQuery(cmpRows, null, null, { field: '销售额' }, 'sum', null, null);
    console.log('  result[0].__comparisonData__:', JSON.stringify(result[0].__comparisonData__));
    assert(result[0].__comparisonData__.first.days === 5, 'first.days = 5');
    assert(result[0].__comparisonData__.second.days === 5, 'second.days = 5');
    assert(result[0].__comparisonData__.daysUnequal === false, 'daysUnequal=false（5天vs5天）');
    if (typeof win.buildInterpretation === 'function') {
      const interp = win.buildInterpretation(result, null, { field: '销售额' }, 'sum', null, null, null, '中旬相比上旬销售额变化了多少？');
      console.log('  解读:', interp);
      assert(/5 天/.test(interp), '含"5 天"');
      assert(!/日均.*?元\/天/.test(interp), '天数相等时不含日均文案');
    }
  }
  win._lastComparisonTimeRanges = null;

  // === Test 5: 对比查询天数不等 → 触发日均文案 ===
  console.log('--- Test 5: 对比查询天数不等（4天vs3天）→ 含日均文案 ---');
  const unqRows = [
    { 日期: '2024-04-02', 销售额: 100 },  // 缺 4/1
    { 日期: '2024-04-03', 销售额: 200 },
    { 日期: '2024-04-04', 销售额: 300 },
    { 日期: '2024-04-05', 销售额: 400 },
    { 日期: '2024-04-11', 销售额: 500 },
    { 日期: '2024-04-12', 销售额: 600 },
    { 日期: '2024-04-13', 销售额: 700 }
  ];
  win._lastQuery = '中旬相比上旬销售额变化了多少？';
  win._lastComparisonTimeRanges = win.parseComparisonTimeRanges('中旬相比上旬销售额变化了多少？', '日期', unqRows);
  if (win._lastComparisonTimeRanges && typeof win.executeQuery === 'function') {
    const result = win.executeQuery(unqRows, null, null, { field: '销售额' }, 'sum', null, null);
    console.log('  days:', result[0].__comparisonData__.first.days, 'vs', result[0].__comparisonData__.second.days, 'daysUnequal:', result[0].__comparisonData__.daysUnequal);
    assert(result[0].__comparisonData__.first.days === 4, 'first.days = 4（4/1 无数据）');
    assert(result[0].__comparisonData__.second.days === 3, 'second.days = 3');
    assert(result[0].__comparisonData__.daysUnequal === true, 'daysUnequal=true');
    if (typeof win.buildInterpretation === 'function') {
      const interp = win.buildInterpretation(result, null, { field: '销售额' }, 'sum', null, null, null, '中旬相比上旬销售额变化了多少？');
      console.log('  解读:', interp);
      assert(/元\/天/.test(interp), '含"元/天"日均单位');
    }
  }
  win._lastComparisonTimeRanges = null;

  console.log('\n===== 汇总 =====');
  console.log('通过: ' + passed + ' / ' + (passed + failed));
  process.exit(failed > 0 ? 1 : 0);
})().catch(e => { console.error('Error:', e.message); process.exit(1); });