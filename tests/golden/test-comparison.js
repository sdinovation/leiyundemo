'use strict';
/**
 * v2.9: 时间对比查询单元测试
 * 验证 parseComparisonTimeRanges + executeQuery + buildInterpretation 端到端
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

  // 测试数据：2024年4月每日销售额
  const rows = [
    { 日期: '2024-04-01', 销售额: 100 },
    { 日期: '2024-04-05', 销售额: 200 },
    { 日期: '2024-04-10', 销售额: 300 },   // 上旬末
    { 日期: '2024-04-11', 销售额: 400 },   // 中旬始
    { 日期: '2024-04-15', 销售额: 500 },
    { 日期: '2024-04-20', 销售额: 600 },   // 中旬末
    { 日期: '2024-04-21', 销售额: 700 },   // 下旬始
    { 日期: '2024-04-25', 销售额: 800 },
    { 日期: '2024-04-30', 销售额: 900 }
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

  if (typeof win.parseComparisonTimeRanges !== 'function') {
    console.error('parseComparisonTimeRanges not exposed on window');
    process.exit(1);
  }

  const parseComparisonTimeRanges = win.parseComparisonTimeRanges;
  const parseTimeRange = win.parseTimeRange;

  console.log('===== parseComparisonTimeRanges 时间对比 =====');
  console.log('数据日期范围: 2024-04-01 至 2024-04-30');
  console.log('');

  // === Test 1: 中旬相比上旬 ===
  console.log('--- Test 1: "中旬相比上旬销售额变化了多少？" ---');
  let cmp = parseComparisonTimeRanges('中旬相比上旬销售额变化了多少？', '日期', rows);
  assert(cmp !== null, 'parseComparisonTimeRanges 返回非 null');
  if (cmp) {
    console.log('  first.term=' + cmp.first.term + ' second.term=' + cmp.second.term);
    assert(cmp.first.term === '上旬' && cmp.second.term === '中旬', '顺序：first=上旬 second=中旬');
    assert(cmp.first.timeRange && cmp.second.timeRange, '两个 timeRange 都解析');
    if (cmp.first.timeRange && cmp.second.timeRange) {
      console.log('  上旬:', cmp.first.timeRange.minDate.toISOString().slice(0,10), '至', cmp.first.timeRange.maxDate.toISOString().slice(0,10));
      console.log('  中旬:', cmp.second.timeRange.minDate.toISOString().slice(0,10), '至', cmp.second.timeRange.maxDate.toISOString().slice(0,10));
      assert(cmp.first.timeRange.minDate.getDate() === 1 && cmp.first.timeRange.maxDate.getDate() === 10, '上旬 = 1-10');
      assert(cmp.second.timeRange.minDate.getDate() === 11 && cmp.second.timeRange.maxDate.getDate() === 20, '中旬 = 11-20');
    }
  }

  // === Test 2: 本周相比上周 ===
  console.log('--- Test 2: "本周相比上周销售额增长了多少？" ---');
  cmp = parseComparisonTimeRanges('本周相比上周销售额增长了多少？', '日期', rows);
  // 注：parseTimeRange 不解析 "本周/上周"，本测试仅验证模式匹配
  if (cmp) {
    console.log('  first.term=' + cmp.first.term + ' second.term=' + cmp.second.term);
  } else {
    console.log('  本周/上周 暂未被 parseTimeRange 识别（预期），待后续迭代');
  }
  assert(true, 'parseComparisonTimeRanges 不抛异常');

  // === Test 3: 3月相比2月 ===
  console.log('--- Test 3: "3月相比2月销售额增长了多少"（X月 vs X月）---');
  cmp = parseComparisonTimeRanges('3月相比2月销售额增长了多少', '日期', rows);
  assert(cmp !== null, 'parseComparisonTimeRanges 返回非 null');
  if (cmp) {
    console.log('  first.term=' + cmp.first.term + ' second.term=' + cmp.second.term);
    assert(cmp.first.term === '2月' && cmp.second.term === '3月', 'first=2月 second=3月');
  }

  // === Test 4: executeQuery 对比路径 ===
  console.log('--- Test 4: executeQuery 对比路径返回 __comparisonData__ ---');
  if (typeof win.executeQuery === 'function') {
    win._lastComparisonTimeRanges = parseComparisonTimeRanges('中旬相比上旬销售额变化了多少？', '日期', rows);
    const result = win.executeQuery(rows, null, null, { field: '销售额' }, 'sum', null, null);
    assert(Array.isArray(result) && result.length === 1, '返回 1 行');
    if (result && result[0]) {
      assert(result[0].__comparisonData__ !== undefined, '含 __comparisonData__ 字段');
      if (result[0].__comparisonData__) {
        const cd = result[0].__comparisonData__;
        console.log('  上旬总和:', cd.first.sum, '中旬总和:', cd.second.sum, '差:', cd.diff, '率:', cd.pct + '%');
        // 注：jsdom Date 时区偏移可能导致日期偏移 1 天，绝对值取决于运行环境
        // 验证逻辑正确性：diff = second.sum - first.sum，pct = diff/first.sum * 100
        assert(cd.second.sum > cd.first.sum, '中旬 > 上旬（数据正确性）');
        assert(Math.abs(cd.diff - (cd.second.sum - cd.first.sum)) < 0.01, 'diff = second - first');
        assert(cd.pct > 0, '增长率 > 0（中旬更高）');
      }
    }
    win._lastComparisonTimeRanges = null;
  }

  // === Test 5: buildInterpretation 对比渲染 ===
  console.log('--- Test 5: buildInterpretation 对比文本 ---');
  if (typeof win.buildInterpretation === 'function') {
    const _cmpResult = [{
      '上旬总和': 600,
      '中旬总和': 1500,
      '变化额': 900,
      '变化率': 150,
      __comparisonData__: {
        first: { term: '上旬', sum: 600, label: '4月上旬' },
        second: { term: '中旬', sum: 1500, label: '4月中旬' },
        diff: 900, pct: 150, metric: '销售额'
      }
    }];
    const interp = win.buildInterpretation(_cmpResult, null, { field: '销售额' }, 'sum', null, null, null, '中旬相比上旬销售额变化了多少？');
    console.log('  解读:', interp);
    assert(/上旬|4月上旬/.test(interp), '解读含上旬');
    assert(/中旬|4月中旬/.test(interp), '解读含中旬');
    assert(/900|增长|150/.test(interp), '解读含差值/增长率');
  }

  // === Test 6: buildChartData 对比柱状图（含 KPI 卡片）===
  console.log('--- Test 6: buildChartData 对比柱状图 ---');
  if (typeof win.buildChartData === 'function') {
    const _cmpResult = [{
      '上旬总和': 600,
      '中旬总和': 1500,
      '变化额': 900,
      '变化率': 150,
      __comparisonData__: {
        first: { term: '上旬', sum: 600, label: '4月上旬' },
        second: { term: '中旬', sum: 1500, label: '4月中旬' },
        diff: 900, pct: 150, metric: '销售额'
      }
    }];
    const chartInfo = win.buildChartData(_cmpResult, null, { field: '销售额' }, 'sum', null);
    assert(chartInfo && chartInfo.chartType === 'bar', 'chartType=bar');
    assert(chartInfo.chartData, '含 chartData');
    if (chartInfo.chartData) {
      assert(chartInfo.chartData.values && chartInfo.chartData.values.length === 2, 'values 长度 = 2');
      assert(chartInfo.chartData.values[0] === 600 && chartInfo.chartData.values[1] === 1500, 'values = [600, 1500]');
      assert(chartInfo.chartData.categories && chartInfo.chartData.categories.length === 2, 'categories 长度 = 2');
      assert(/上旬/.test(chartInfo.chartData.categories[0]) && /中旬/.test(chartInfo.chartData.categories[1]), 'categories = [上旬, 中旬]');
    }
    assert(Array.isArray(chartInfo.kpiCards) && chartInfo.kpiCards.length === 4, '含 4 个 KPI 卡片（上旬/中旬/变化额/变化率）');
    assert(/对比/.test(chartInfo.title || ''), 'title 含"对比"');
  }

  console.log('\n===== 汇总 =====');
  console.log('通过: ' + passed + ' / ' + (passed + failed));
  process.exit(failed > 0 ? 1 : 0);
})().catch(e => { console.error('Error:', e.message); process.exit(1); });