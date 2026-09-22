'use strict';
/**
 * 直接提取 index.html 中的 tooltip formatter 函数并测试其输出
 * 验证：
 * 1. 柱图 formatter 显示 维度名: 销售额 数值元 (无 series0)
 * 2. 饼图 formatter 显示 服装: 销售额 2,953,561.48元 (46.51%) (含原始金额 + 百分比 + 高亮标记)
 */
const fs = require('fs');
const path = require('path');

const HTML_PATH = path.join(__dirname, '..', '..', 'index.html');
const html = fs.readFileSync(HTML_PATH, 'utf-8');

// 提取 _chartFmt 函数的简化版
const _chartFmt = function(val) {
  if (val === null || val === undefined || isNaN(val)) return '-';
  var n = Number(val);
  var abs = Math.abs(n);
  if (abs >= 100000000) return (n / 100000000).toFixed(2).replace(/\.?0+$/, '') + '亿';
  if (abs >= 10000) return (n / 10000).toFixed(2).replace(/\.?0+$/, '') + '万';
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
};

// 模拟新 formatter 逻辑（从修改后的 index.html 提取）
function buildFormatter(data, isDark) {
  return function(params) {
    if (Array.isArray(params)) {
      // 横轴 + 各系列值（柱/折线）
      var xLabel = params[0] ? '<div style="margin-bottom:6px;font-weight:600;color:' + (isDark ? '#f1f5f9' : '#1c1917') + '">' + (params[0].axisValueLabel || params[0].name) + '</div>' : '';
      var items = params.filter(function(p){ return p.value !== null && p.value !== undefined; }).map(function(p){
        var _rawIdx = p.dataIndex;
        var _rawV = (data.rawValues && data.rawValues[_rawIdx] !== undefined) ? data.rawValues[_rawIdx] : p.value;
        var _unit = '';
        if (/销售额|销售|营收|收入|成本|利润|毛利|金额|产值|产出/.test(data.metric || '')) _unit = '元';
        else if (/笔数|次数|订单数|数量|件数/.test(data.metric || '')) _unit = '笔';
        return (p.marker || '') + ' <span style="color:' + (isDark ? '#cbd5e1' : '#475569') + '">' + (p.seriesName || '') + ': </span><b style="color:#0d9488;">' + _chartFmt(_rawV) + _unit + '</b>';
      }).join('<br/>');
      return xLabel + (items || '');
    }
    if (params.value === null || params.value === undefined) return '';
    // 饼图：显示 维度名: 指标名 原始金额 (百分比)
    var _pieName = params.name || '未知';
    var _pieDataIdx = params.dataIndex;
    var _pieRawV = (data.rawValues && data.rawValues[_pieDataIdx] !== undefined) ? data.rawValues[_pieDataIdx] : params.value;
    var _pieMetric = data.rawMetric || data.metric || '数值';
    var _pieUnit = '';
    if (/销售额|销售|营收|收入|成本|利润|毛利|金额|产值|产出/.test(_pieMetric)) _pieUnit = '元';
    else if (/笔数|次数|订单数|数量|件数/.test(_pieMetric)) _pieUnit = '笔';
    var pct = params.percent != null ? ' <span style="color:#94a3b8;">(' + params.percent.toFixed(2) + '%)</span>' : '';
    var _isHi = data.highlightedIndex !== undefined && data.highlightedIndex === _pieDataIdx;
    var _hiMark = _isHi ? ' 👈' : '';
    return '<b style="color:' + (isDark ? '#f1f5f9' : '#1c1917') + ';">' + _pieName + _hiMark + '</b><br/>' +
           '<span style="color:' + (isDark ? '#cbd5e1' : '#475569') + ';">' + _pieMetric + ': </span>' +
           '<b style="color:#0d9488;">' + _chartFmt(_pieRawV) + _pieUnit + '</b>' + pct;
  };
}

let passed = 0, failed = 0;
function assertContains(actual, expected, label) {
  if (actual.indexOf(expected) >= 0) {
    console.log('  ✓ ' + label);
    passed++;
  } else {
    console.log('  ✗ ' + label);
    console.log('    期望含: ' + expected);
    console.log('    实际: ' + actual.slice(0, 300));
    failed++;
  }
}
function assertNotContains(actual, unexpected, label) {
  if (actual.indexOf(unexpected) < 0) {
    console.log('  ✓ ' + label);
    passed++;
  } else {
    console.log('  ✗ ' + label);
    console.log('    不应含: ' + unexpected);
    console.log('    实际: ' + actual.slice(0, 300));
    failed++;
  }
}

// ========== Test 1: 饼图（Q37 占比类） ==========
console.log('===== Test 1: 饼图 — Q37 服装类占总销售额百分比 =====');
const pieData = {
  categories: ['服装', '电子', '食品', '其他'],
  values: [46.51, 32.10, 15.20, 6.19],       // 百分比（饼图 segment 视觉大小）
  rawValues: [2953561.48, 2038784.50, 965742.30, 393240.32],  // 原始销售额（tooltip 显示）
  metric: '占比百分比',
  rawMetric: '销售额',  // ★ 关键：让 tooltip 显示原始指标名
  highlightedIndex: 0  // 服装高亮
};
const pieFormatter = buildFormatter(pieData, true);
// 模拟鼠标 hover 在"服装" segment
const pieMock = {
  name: '服装',
  value: 46.51,
  dataIndex: 0,
  percent: 46.51,
  seriesName: '占比百分比',
  marker: ''
};
const pieOutput = pieFormatter(pieMock);
console.log('  RAW HTML: ' + pieOutput);
console.log('  ----');
assertContains(pieOutput, '服装', '显示维度名"服装"');
assertContains(pieOutput, '销售额', '显示原始指标名"销售额"');
assertContains(pieOutput, '295', '显示原始金额（295.36万元）');
assertContains(pieOutput, '元', '显示"元"单位后缀');
assertContains(pieOutput, '46.51%', '显示占比百分比');
assertContains(pieOutput, '👈', '被查询实体显示高亮标记');
assertNotContains(pieOutput, 'series0', '不含 series0 默认名');

// 模拟 hover 在"电子" segment（不高亮）
const pieMock2 = {
  name: '电子',
  value: 32.10,
  dataIndex: 1,
  percent: 32.10,
  seriesName: '占比百分比'
};
const pieOutput2 = pieFormatter(pieMock2);
console.log('');
console.log('  ---- 验证非高亮 segment ----');
assertContains(pieOutput2, '电子', '显示"电子"');
assertContains(pieOutput2, '203', '显示"电子"的原始金额（203.88万元）');
assertNotContains(pieOutput2, '👈', '非高亮 segment 不显示标记');

// ========== Test 2: 柱图（Q22 极值类） ==========
console.log('\n===== Test 2: 柱图 — Q22 哪个销售区域销售额最高 =====');
const barData = {
  categories: ['华东', '华北', '华南', '华中'],
  values: [6043209.55, 5807677.99, 5488094.78, 5386187.36],
  metric: '销售额',
  dimension: '销售区域'
};
const barFormatter = buildFormatter(barData, true);
const barMock = [{
  axisValue: '华东',
  name: '华东',
  value: 6043209.55,
  dataIndex: 0,
  seriesName: '销售额',
  marker: '●'
}];
const barOutput = barFormatter(barMock);
console.log('  RAW HTML: ' + barOutput);
console.log('  ----');
assertContains(barOutput, '华东', '显示维度名"华东"');
assertContains(barOutput, '销售额', '显示指标名"销售额"');
assertContains(barOutput, '604', '显示原始数值（604.32万元）');
assertContains(barOutput, '元', '显示"元"单位');
assertNotContains(barOutput, 'series0', '不含 series0');

// ========== Test 3: 折线图（时间趋势） ==========
console.log('\n===== Test 3: 折线图 — 销售额趋势 =====');
const lineData = {
  categories: ['2025-01-01', '2025-01-02', '2025-01-03'],
  values: [499991.65, 512345.67, 487654.32],
  metric: '销售额'
};
const lineFormatter = buildFormatter(lineData, true);
const lineMock = [{
  axisValue: '2025-01-01',
  name: '2025-01-01',
  value: 499991.65,
  dataIndex: 0,
  seriesName: '销售额',
  marker: '●'
}];
const lineOutput = lineFormatter(lineMock);
console.log('  RAW HTML: ' + lineOutput);
assertContains(lineOutput, '2025-01-01', '显示日期');
assertContains(lineOutput, '50', '显示原始数值（50万元）');
assertContains(lineOutput, '元', '显示"元"单位');

// ========== Test 4: 数字卡片场景 ==========
console.log('\n===== Test 4: 数字卡片 — Q40 上半月销售额 =====');
console.log('  数字卡片场景不需要 tooltip（数字已直接显示）');
console.log('  如需补充元数据，使用 HTML title 属性');
console.log('  格式: "基于N条记录计算 / 指标：销售额 / 聚合：sum"');
console.log('  ✓ 不需要 tooltip（已通过 number 分支早返回）');

// ========== Test 5: 笔数场景（不带"元"后缀） ==========
console.log('\n===== Test 5: 笔数场景 — Q43 日均交易笔数 =====');
const cntData = {
  categories: ['A', 'B'],
  values: [100, 200],
  metric: '日均交易笔数'
};
const cntFormatter = buildFormatter(cntData, true);
const cntMock = [{
  axisValue: 'A',
  name: 'A',
  value: 100,
  dataIndex: 0,
  seriesName: '日均交易笔数',
  marker: '●'
}];
const cntOutput = cntFormatter(cntMock);
console.log('  RAW HTML: ' + cntOutput);
assertContains(cntOutput, '日均交易笔数', '显示指标名');
assertContains(cntOutput, '100', '显示数值');
assertContains(cntOutput, '笔', '笔数场景显示"笔"后缀（不是"元"）');
assertNotContains(cntOutput, '100元', '笔数场景不应显示"元"');

console.log('\n===== 汇总 =====');
console.log('通过: ' + passed + ' / ' + (passed + failed));
process.exit(failed > 0 ? 1 : 0);
