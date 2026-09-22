// Phase 1.2 验证脚本 - 模拟 detectFollowUpType
// 直接从 index.html 复制函数定义

// ===== Mock ctx =====
class ConversationContext {
  constructor() {
    this.turns = [];
    this.entities = new Map();
  }
  push(turn) {
    this.turns.push(turn);
    // 同步 entities
    if (turn.entities) {
      Object.entries(turn.entities).forEach(([alias, real]) => {
        this.recordEntityAlias(alias, real);
      });
    }
  }
  getLastTurn() { return this.turns[this.turns.length - 1]; }
  resolveField(alias) {
    if (!alias) return null;
    const cleaned = String(alias).replace(/[的呢吧？\?]+$/, '').trim();
    if (!cleaned) return null;
    if (this.entities.has(cleaned)) {
      return this.entities.get(cleaned);
    }
    for (const [key, val] of this.entities.entries()) {
      if (cleaned.includes(key) || key.includes(cleaned)) {
        return val;
      }
    }
    return null;
  }
  recordEntityAlias(alias, realField) {
    this.entities.set(alias, realField);
  }
}

// ===== 被测函数（最新版本） =====
function detectFollowUpType(text, ctx) {
  if (!text || !ctx) return { type: 'none', confidence: 0, payload: {} };
  const lastTurn = ctx.getLastTurn ? ctx.getLastTurn() : null;
  const last = lastTurn ? lastTurn.analysis : null;
  if (!last) return { type: 'none', confidence: 0, payload: {} };

  const t = String(text).trim();
  const len = t.length;

  if (/^(它|这个|那个|上面那个|上一轮|前面的|前述|此)\s*[的呢吧？\?]?$/.test(t))
    return { type: 'reference', confidence: 0.95, payload: { ref: 'previous' } };

  const aliased = ctx.resolveField ? ctx.resolveField(t) : null;
  if (aliased && aliased !== t) {
    return { type: 'field_swap', confidence: 0.85, payload: { swapTo: aliased } };
  }

  let cm = /^换成?\s*(柱状图|折线图|饼图|散点图|表格|数字|条形|面积图|雷达图)$/.exec(t);
  if (cm) {
    const typeMap = {
      '柱状图': 'bar', '条形': 'bar',
      '折线图': 'line', '面积图': 'line',
      '饼图': 'pie',
      '散点图': 'scatter',
      '表格': 'table',
      '数字': 'number',
      '雷达图': 'radar'
    };
    return { type: 'chart_swap', confidence: 0.92, payload: { newChartType: typeMap[cm[1]] || 'bar' } };
  }
  if (/^返回卡片/.test(t))
    return { type: 'chart_swap', confidence: 0.85, payload: { newChartType: 'card' } };

  let m = /^(按|改成|换成|切到|换作|改用)\s*(.+?)(?:呢|吧|？|\?)?$/.exec(t);
  if (m) {
    const swapTo = m[2].trim();
    const fieldInfo = (typeof parsedData !== 'undefined' && parsedData.fieldInfo) || [];
    const dimField = fieldInfo.find(f => f.name === swapTo && (f.type === 'text' || f.type === 'date'));
    const numericField = fieldInfo.find(f => f.name === swapTo && ['int','float','currency','percent'].indexOf(f.type) >= 0);
    if (dimField) return { type: 'axis_swap', confidence: 0.85, payload: { swapTo, swapKind: 'dimension' } };
    if (numericField) return { type: 'axis_swap', confidence: 0.8, payload: { swapTo, swapKind: 'metric' } };
    if (/^(平均|均值|总和|总计|累计|最大|最小|最高|最低|求和|求平均)$/.test(swapTo)) {
      return { type: 'axis_swap', confidence: 0.75, payload: { swapTo, swapKind: 'aggregation' } };
    }
    return { type: 'axis_swap', confidence: 0.6, payload: { swapTo, swapKind: 'unknown' } };
  }

  if (/^(上|这|下|近|最近)\s*(周|月|季|年|天)\s*[的呢吧？\?]*$/.test(t))
    return { type: 'time_relative', confidence: 0.9, payload: { text: t.replace(/\s*[的呢吧？\?]*$/, '') } };
  if (/^(本周|上周|本月|上月|本季|上季|今年|去年|前年|近\s*\d+\s*(?:天|周|月|年))\s*[的呢吧]*$/.test(t))
    return { type: 'time_relative', confidence: 0.92, payload: { text: t.replace(/\s*[的呢吧]*$/, '') } };
  if (/^(昨天|今天|明天|前天|后天|大前天)$/.test(t))
    return { type: 'time_relative', confidence: 0.9, payload: { text: t } };

  let lm = /^(倒序|正序|从小到大|从大到小|升序|降序)$/i.exec(t);
  if (lm) return { type: 'limit_swap', confidence: 0.85, payload: { sortOrder: /倒序|从大到小|降序/.test(t) ? 'desc' : 'asc' } };
  lm = /^(?:前|top|TOP)\s*(\d+)\s*(?:个|名|位|条|家)?\s*[的呢吧]*$/.exec(t);
  if (lm) return { type: 'limit_swap', confidence: 0.85, payload: { limit: parseInt(lm[1], 10) } };
  if (/^(只看前\s*\d+|前\s*\d+个)\s*[的吧呢]*$/.test(t)) {
    const n = t.match(/\d+/);
    if (n) return { type: 'limit_swap', confidence: 0.8, payload: { limit: parseInt(n[0], 10) } };
  }

  if (len < 12) {
    const lastEntities = (lastTurn && lastTurn.entities) ? Object.keys(lastTurn.entities) : [];
    const lastDimension = last && last.dimension;
    const lastMetric = last && (last.metric || last.y_field);
    const allPrev = [...lastEntities, lastDimension, lastMetric].filter(Boolean);
    if (len <= 6 && allPrev.some(e => t === String(e) || t === String(e).slice(0, 2))) {
      return { type: 'weak', confidence: 0.55, payload: { fallback: 'recompute', sharedField: allPrev.find(e => t === String(e) || t === String(e).slice(0, 2)) } };
    }
    if (allPrev.some(e => t.includes(String(e).slice(0, Math.max(2, Math.floor(String(e).length * 0.4)))))) {
      return { type: 'weak', confidence: 0.5, payload: { fallback: 'recompute' } };
    }
    if (/(呢|吧|怎么样|如何|多少)$/.test(t) || /(看|看)?下$/.test(t)) {
      return { type: 'weak', confidence: 0.5, payload: { fallback: 'recompute' } };
    }
  }

  return { type: 'none', confidence: 0, payload: {} };
}

// ===== Mock fieldInfo =====
const parsedData = {
  fieldInfo: [
    { name: '产品', type: 'text' },
    { name: '销售额', type: 'currency' },
    { name: '日期', type: 'date' },
    { name: '地区', type: 'text' },
    { name: '城市', type: 'text' },
    { name: '数量', type: 'int' },
    { name: '部门', type: 'text' },
    { name: '员工人数', type: 'int' }
  ]
};

// ===== 测试用例 =====
const tests = [
  { input: '按地区呢', expected: 'axis_swap' },
  { input: '上周的呢', expected: 'time_relative' },
  { input: '营收呢', expected: 'field_swap' },
  { input: '换成饼图', expected: 'chart_swap' },
  { input: '前3名', expected: 'limit_swap' },
  { input: '倒序', expected: 'limit_swap' },
  { input: '它', expected: 'reference' },
  { input: '那个呢', expected: 'reference' },
  { input: '前10个', expected: 'limit_swap' },
  { input: '市场部', expected: 'field_swap' },  // entities 里 alias='市场部' → '部门'
  { input: '本周', expected: 'time_relative' },
  { input: '本月', expected: 'time_relative' },
  { input: '看趋势', expected: 'none' }
];

// 上轮固定为「HR 数据：各城市员工人数」
const ctx = new ConversationContext();
ctx.push({
  question: '各城市员工人数',
  analysis: {
    dimension: '城市',
    metric: '员工人数',
    groupBy: '城市'
  },
  entities: {
    '城市': '城市',
    '员工人数': '员工人数',
    '部门': '部门',
    '市场部': '部门'  // '市场部' 是 '部门' 维度的某值
  }
});

// '营收' 不存在 entities 缓存里，先测一次
let pass1 = 0, fail1 = 0;
console.log('=== Phase 1.2 detectFollowUpType 测试 ===');
for (const t of tests) {
  const r = detectFollowUpType(t.input, ctx);
  const ok = r.type === t.expected;
  console.log(`  ${ok ? '✅' : '❌'} '${t.input}' → ${r.type} ${ok ? '' : `(期望: ${t.expected})`}`);
  if (ok) pass1++; else fail1++;
}
console.log(`\n通过: ${pass1}/${tests.length}\n`);

// ===== 测试 '营收呢' 在 recordEntityAlias 后 =====
ctx.recordEntityAlias('营收', '员工人数');
const after = detectFollowUpType('营收呢', ctx);
console.log(`别名注入后 '营收呢' → ${after.type} ${after.type === 'field_swap' ? '✅' : '❌ (期望: field_swap)'}`);

// ===== resolveFollowUp 测试 =====
function resolveFollowUp(detect, ctx) {
  const prev = ctx.getLastTurn().analysis;
  if (!prev) return null;
  switch (detect.type) {
    case 'reference':
    case 'weak':
      return Object.assign({}, prev, { followUpType: detect.type, resolvedFrom: 'previous' });
    case 'field_swap':
      return Object.assign({}, prev, { metric: detect.payload.swapTo, y_field: detect.payload.swapTo });
    case 'axis_swap':
      const swapKind = detect.payload.swapKind;
      if (swapKind === 'dimension') return Object.assign({}, prev, { dimension: detect.payload.swapTo, groupBy: detect.payload.swapTo });
      if (swapKind === 'metric') return Object.assign({}, prev, { metric: detect.payload.swapTo, y_field: detect.payload.swapTo });
      if (swapKind === 'aggregation') return Object.assign({}, prev, { aggregation: detect.payload.swapTo });
      return prev;
    case 'time_relative':
      const label = detect.payload.text;
      return Object.assign({}, prev, { timeRange: { label, text: label } });
    case 'limit_swap':
      return Object.assign({}, prev, { limit: detect.payload.limit, sortOrder: detect.payload.sortOrder });
    case 'chart_swap':
      return Object.assign({}, prev, { chartType: detect.payload.newChartType, chart_type: detect.payload.newChartType });
    default:
      return prev;
  }
}

console.log('\n=== resolveFollowUp 测试 ===');
const tests2 = [
  { input: '按地区呢', expected: '地区', check: 'dimension' },
  { input: '营收呢', expected: '员工人数', check: 'metric' },
  { input: '换成饼图', expected: 'pie', check: 'chartType' },
  { input: '前3名', expected: 3, check: 'limit' },
  { input: '上周的呢', expected: '上周', check: 'timeRange.label' }
];
let pass2 = 0, fail2 = 0;
for (const t of tests2) {
  const detect = detectFollowUpType(t.input, ctx);
  const r = resolveFollowUp(detect, ctx);
  let actual;
  if (t.check === 'timeRange.label') actual = r && r.timeRange && r.timeRange.label;
  else actual = r && r[t.check];
  const ok = actual == t.expected;
  console.log(`  ${ok ? '✅' : '❌'} '${t.input}' → ${t.check}=${actual} ${ok ? '' : `(期望: ${t.expected})`}`);
  if (ok) pass2++; else fail2++;
}
console.log(`\n通过: ${pass2}/${tests2.length}`);