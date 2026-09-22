'use strict';
/**
 * v2.9 F 增强: COUNT DISTINCT 应同时返回去重值列表
 * 验证窗口全局 _lastDistinctValues 被正确填充，buildInterpretation 渲染列表
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
    { 产品: '苹果', 销售额: 100 },
    { 产品: '香蕉', 销售额: 200 },
    { 产品: '苹果', 销售额: 300 },
    { 产品: '葡萄', 销售额: 400 },
    { 产品: '香蕉', 销售额: 500 },
    { 产品: '橘子', 销售额: 600 }
  ];
  win.parsedData = {
    fileName: 'test.csv', rows: rows,
    columns: ['产品', '销售额'],
    fieldInfo: [
      { name: '产品', type: 'text' },
      { name: '销售额', type: 'int' }
    ]
  };

  const scriptMatches = cleaned.match(/<script>([\s\S]*?)<\/script>/g) || [];
  for (const sm of scriptMatches) {
    const code = sm.replace(/^<script>/, '').replace(/<\/script>$/, '');
    try { win.eval(code); } catch(e) { /* ignore */ }
  }

  console.log('===== v2.9 F: COUNT DISTINCT 去重值列表 =====');
  console.log('数据: 6 条销售记录，产品去重后应为 4 种（苹果/香蕉/葡萄/橘子）');
  console.log('');

  // === Test 1: executeQuery 标量 COUNT DISTINCT 保存 _lastDistinctValues ===
  console.log('--- Test 1: executeQuery("产品" COUNT DISTINCT) ---');
  if (typeof win.executeQuery === 'function') {
    const result = win.executeQuery(rows, null, null, { field: '__COUNT_DISTINCT__', countField: '产品' }, 'count_distinct', null, null);
    assert(Array.isArray(result) && result.length === 1, '返回 1 行');
    if (result && result[0]) {
      assert(result[0]['去重计数'] === 4, '去重计数 = 4');
    }
    assert(Array.isArray(win._lastDistinctValues), '_lastDistinctValues 是数组');
    if (Array.isArray(win._lastDistinctValues)) {
      console.log('  _lastDistinctValues:', win._lastDistinctValues);
      assert(win._lastDistinctValues.length === 4, '数组长度 = 4');
      assert(win._lastDistinctValues.includes('苹果'), '包含 苹果');
      assert(win._lastDistinctValues.includes('香蕉'), '包含 香蕉');
      assert(win._lastDistinctValues.includes('葡萄'), '包含 葡萄');
      assert(win._lastDistinctValues.includes('橘子'), '包含 橘子');
    }
    assert(win._lastDistinctField === '产品', '_lastDistinctField = 产品');
  }

  // === Test 2: buildInterpretation 渲染列表（少 → 全列） ===
  console.log('--- Test 2: buildInterpretation 少列表（≤20 项 → 全列）---');
  if (typeof win.buildInterpretation === 'function') {
    win._lastDistinctValues = ['苹果', '香蕉', '葡萄', '橘子'];
    win._lastDistinctField = '产品';
    // metric.label 不传 → _mf 默认为 '去重计数'
    const result = [{ '去重计数': 4 }];
    const interp = win.buildInterpretation(result, null, { field: '__COUNT_DISTINCT__', countField: '产品' }, 'count_distinct', null, null, null, '共有多少种不同的产品？');
    console.log('  解读:', interp);
    assert(/4/.test(interp), '含数字 4');
    assert(/苹果/.test(interp), '含 苹果');
    assert(/香蕉/.test(interp), '含 香蕉');
    assert(/葡萄/.test(interp), '含 葡萄');
    assert(/橘子/.test(interp), '含 橘子');
    assert(/具体包括|类别/.test(interp), '含"具体包括"或"类别"');
  }

  // === Test 3: buildInterpretation 渲染列表（多 → 截断 + 总数） ===
  console.log('--- Test 3: buildInterpretation 多列表（>20 项 → 截断前10 + 总数）---');
  if (typeof win.buildInterpretation === 'function') {
    win._lastDistinctValues = ['a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','v'];
    win._lastDistinctField = '标签';
    const result = [{ '去重计数': 22 }];
    const interp = win.buildInterpretation(result, null, { field: '__COUNT_DISTINCT__', countField: '标签' }, 'count_distinct', null, null, null, '共有多少种不同的标签？');
    console.log('  解读:', interp);
    assert(/22/.test(interp), '含总数 22');
    assert(/a.*b.*c/.test(interp), '含前 3 项 a,b,c');
    assert(/主要类别|等共/.test(interp), '含"主要类别"或"等共"');
  }

  // === Test 4: 非 COUNT DISTINCT 不应污染 _lastDistinctValues ===
  console.log('--- Test 4: 非 COUNT DISTINCT → _lastDistinctValues = null ---');
  if (typeof win.executeQuery === 'function') {
    win._lastDistinctValues = null;
    win.executeQuery(rows, null, null, { field: '销售额' }, 'sum', null, null);
    assert(win._lastDistinctValues === null, 'SUM 查询后 _lastDistinctValues = null');
  }

  console.log('\n===== 汇总 =====');
  console.log('通过: ' + passed + ' / ' + (passed + failed));
  process.exit(failed > 0 ? 1 : 0);
})().catch(e => { console.error('Error:', e.message); process.exit(1); });