'use strict';
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

  const dom = new JSDOM(cleaned, {
    url: 'http://localhost/',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
    resources: 'usable'
  });
  const win = dom.window;
  win.tailwind = { config: {} };
  win.lucide = { createIcons: () => {}, createElement: () => null };
  win.Papa = { parse: () => ({ data: [], errors: [] }) };
  win.echarts = function () { return { setOption: () => {}, resize: () => {}, dispose: () => {}, on: () => {} }; };
  win.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  const rows = [
    { 日期: '2024-01-05', 销售额: 1000 },
    { 日期: '2024-01-15', 销售额: 2000 },
    { 日期: '2024-01-22', 销售额: 3000 },
    { 日期: '2024-01-28', 销售额: 4000 },
    { 日期: '2024-01-30', 销售额: 5000 },
    { 日期: '2024-02-10', 销售额: 6000 }
  ];
  win.parsedData = {
    fileName: 'test.csv', rows: rows,
    columns: ['日期', '销售额'],
    fieldInfo: [
      { name: '日期', type: 'date' },
      { name: '销售额', type: 'int' }
    ]
  };

  const scriptMatches = cleaned.match(/<script>([\s\S]*?)<\/script>/g) || [];
  for (const sm of scriptMatches) {
    const code = sm.replace(/^<script>/, '').replace(/<\/script>$/, '');
    try { win.eval(code); } catch(e) { /* ignore */ }
  }

  if (typeof win.parseTimeRange !== 'function') {
    console.error('parseTimeRange not exposed on window');
    process.exit(1);
  }

  const parseTimeRange = win.parseTimeRange;
  console.log('===== parseTimeRange 旬/半月语义 =====');
  console.log('数据日期范围: 2024-01-05 至 2024-02-10');
  console.log('');

  function test(q) {
    try { return parseTimeRange(q, '日期', rows); }
    catch (e) { console.error('  [error] ' + e.message); return null; }
  }
  function testVerbose(q) {
    console.log('  [DEBUG] q=' + q);
    var r = test(q);
    if (r) {
      console.log('  [DEBUG] label=' + r.label + ' minDate=' + fmt(r.minDate) + ' maxDate=' + fmt(r.maxDate) +
        ' | minDate.getDate()=' + r.minDate.getDate() + ' maxDate.getDate()=' + r.maxDate.getDate());
    }
    return r;
  }

  function fmt(d) { return d.toISOString().slice(0,10); }

  // Test 1
  console.log('--- Test 1: "上旬销售额" ---');
  let res = test('上旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 1, 'minDate = 1日');
    assert(res.maxDate.getDate() === 10, 'maxDate = 10日');
    assert(/上旬/.test(res.label), 'label 含 "上旬"');
  }

  // Test 2
  console.log('--- Test 2: "中旬销售额" ---');
  res = test('中旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 11, 'minDate = 11日');
    assert(res.maxDate.getDate() === 20, 'maxDate = 20日');
  }

  // Test 3
  console.log('--- Test 3: "下旬销售额" ---');
  res = test('下旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 21, 'minDate = 21日');
    const refLastDay = new Date(2024, 2, 0).getDate();
    assert(res.maxDate.getDate() === refLastDay, 'maxDate = ' + refLastDay + '日（2月末）');
  }

  // Test 4
  console.log('--- Test 4: "上半月销售额"（不被上旬抢词）---');
  res = test('上半月销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 1, 'minDate = 1日');
    assert(res.maxDate.getDate() === 15, 'maxDate = 15日');
    assert(/上半月/.test(res.label), 'label 含 "上半月"');
  }

  // Test 5
  console.log('--- Test 5: "下半月销售额" ---');
  res = test('下半月销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 16, 'minDate = 16日');
    const refLastDay = new Date(2024, 2, 0).getDate();
    assert(res.maxDate.getDate() === refLastDay, 'maxDate = ' + refLastDay + '日');
  }

  // Test 6
  console.log('--- Test 6: "1月上旬销售额" ---');
  // Direct regex check
  console.log('  direct regex test:', /上旬/.test('1月上旬销售额'));
  console.log('  下旬 regex:', /下旬/.test('1月上旬销售额'));
  console.log('  中旬 regex:', /中旬/.test('1月上旬销售额'));
  res = testVerbose('1月上旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    assert(res.minDate.getMonth() === 0, '月份 = 0（1月）');
    assert(res.minDate.getDate() === 1, 'minDate = 1日');
    assert(res.maxDate.getDate() === 10, 'maxDate = 10日');
  }

  // Test 7
  console.log('--- Test 7: "2月下旬销售额" ---');
  res = testVerbose('2月下旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    assert(res.minDate.getMonth() === 1, '月份 = 1（2月）');
    assert(res.minDate.getDate() === 21, 'minDate = 21日');
    const febLastDay = new Date(2024, 2, 0).getDate();
    assert(res.maxDate.getDate() === febLastDay, 'maxDate = ' + febLastDay + '日（2月末）');
  }

  // Test 8
  console.log('--- Test 8: "1月销售总额"（月度解析不回归）---');
  res = test('1月销售总额');
  assert(res !== null, '返回非 null（应走月度解析）');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getDate() === 1, 'minDate = 1日');
    assert(res.maxDate.getDate() === 31, 'maxDate = 31日（1月末）');
  }

  // Test 9
  console.log('--- Test 9: "一月上旬销售额"（中文月份识别）---');
  res = test('一月上旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getMonth() === 0, '月份 = 0（1月）');
  }

  // Test 10
  console.log('--- Test 10: "十一月下旬销售额"（中文十+一 = 11月）---');
  res = test('十一月下旬销售额');
  assert(res !== null, '返回非 null');
  if (res) {
    console.log('  解析: ' + fmt(res.minDate) + ' 至 ' + fmt(res.maxDate));
    assert(res.minDate.getMonth() === 10, '月份 = 10（11月）');
  }

  console.log('\n===== 汇总 =====');
  console.log('通过: ' + passed + ' / ' + (passed + failed));
  process.exit(failed > 0 ? 1 : 0);
})().catch(e => { console.error('Error:', e.message); process.exit(1); });