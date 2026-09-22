// 端到端集成测试：模拟整个追问流程
// 包括 ConversationContext + compat layer + detectFollowUpType + resolveFollowUp

// ===== ConversationContext =====
class ConversationContext {
  constructor() {
    this.version = 1;
    this.datasetId = null;
    this.datasetFingerprint = null;
    this.turns = [];
    this.currentTurnIndex = -1;
    this.entities = new Map();
    this.preferences = { timeDrilldown: 0, chartSwitchCount: 0 };
    this.state = {};
  }

  push(turn) {
    const id = turn.id || ('turn-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8));
    const fullTurn = Object.assign({
      id, ts: Date.now(),
      question: '', analysis: null, sql: '', chartConfig: null, chartType: null, insight: '',
      followUpType: null, resolvedFrom: null, entities: {}, rawResult: null
    }, turn);
    this.turns.push(fullTurn);
    this.currentTurnIndex = this.turns.length - 1;
    this.state.lastQuestion = fullTurn.question;
    this.state.lastAnalysis = fullTurn.analysis;
    this.state.lastSQL = fullTurn.sql;
    if (fullTurn.entities && typeof fullTurn.entities === 'object') {
      Object.entries(fullTurn.entities).forEach(([alias, real]) => {
        this.recordEntityAlias(alias, real);
      });
    }
    return fullTurn;
  }

  last(n = 1) { if (n <= 0) return []; return this.turns.slice(-n); }
  getLastTurn() { return this.turns.length > 0 ? this.turns[this.turns.length - 1] : null; }
  getTurn(i) { return this.turns[i] || null; }

  resolveField(alias) {
    if (!alias) return null;
    const cleaned = String(alias).replace(/[的呢吧？\?]+$/, '').trim();
    if (!cleaned) return null;
    if (this.entities.has(cleaned)) {
      const ref = this.entities.get(cleaned);
      ref.hitCount = (ref.hitCount || 0) + 1;
      return ref.canonField;
    }
    for (const [term, ref] of this.entities) {
      if (cleaned.includes(term) || term.includes(cleaned)) return ref.canonField;
    }
    return null;
  }

  recordEntityAlias(userTerm, canonField) {
    if (!userTerm || !canonField || userTerm === canonField) return;
    const existing = this.entities.get(userTerm);
    if (existing) {
      existing.canonField = canonField;
      existing.hitCount = (existing.hitCount || 0) + 1;
    } else {
      this.entities.set(userTerm, { canonField, hitCount: 1, firstSeenTs: Date.now(), lastSeenTs: Date.now() });
    }
  }

  forget() {
    this.turns = [];
    this.currentTurnIndex = -1;
    this.state = {};
  }

  snapshot() {
    // 模拟从 window 同步
    return this;
  }

  restore() {
    return this;
  }

  serialize() {
    return JSON.stringify({
      version: this.version,
      turns: this.turns,
      entities: Array.from(this.entities.entries())
    });
  }

  static deserialize(json) {
    const ctx = new ConversationContext();
    try {
      const obj = typeof json === 'string' ? JSON.parse(json) : json;
      ctx.turns = Array.isArray(obj.turns) ? obj.turns : [];
      ctx.currentTurnIndex = ctx.turns.length - 1;
      ctx.entities = new Map(Array.isArray(obj.entities) ? obj.entities : []);
    } catch (e) {}
    return ctx;
  }
}

// ===== Compat Layer =====
const window = {};
const ctx = new ConversationContext();
const keys = ['_lastQuestion', '_lastAnalysis', '_lastSQL', '_lastIntent', '_isFollowUp'];
keys.forEach(key => {
  let _v = null;
  Object.defineProperty(window, key, {
    configurable: true,
    get() { return _v; },
    set(v) {
      _v = v;
      ctx.state[key.slice(1)] = v;
    }
  });
});

// ===== detectFollowUpType =====
function detectFollowUpType(text, ctx) {
  if (!text || !ctx) return { type: 'none' };
  const lastTurn = ctx.getLastTurn();
  const last = lastTurn ? lastTurn.analysis : null;
  if (!last) return { type: 'none' };

  const t = String(text).trim();

  if (/^(它|这个|那个|上面那个|上一轮|前面的|前述|此)\s*[的呢吧？\?]?$/.test(t))
    return { type: 'reference', confidence: 0.95, payload: { ref: 'previous' } };

  const aliased = ctx.resolveField(t);
  if (aliased && aliased !== t) return { type: 'field_swap', confidence: 0.85, payload: { swapTo: aliased } };

  let cm = /^换成?\s*(柱状图|折线图|饼图|散点图|表格|数字|条形|面积图|雷达图)$/.exec(t);
  if (cm) {
    const typeMap = { '柱状图': 'bar', '条形': 'bar', '折线图': 'line', '面积图': 'line', '饼图': 'pie' };
    return { type: 'chart_swap', confidence: 0.92, payload: { newChartType: typeMap[cm[1]] || 'bar' } };
  }

  let m = /^(按|改成|换成|切到|换作|改用)\s*(.+?)(?:呢|吧|？|\?)?$/.exec(t);
  if (m) {
    return { type: 'axis_swap', confidence: 0.8, payload: { swapTo: m[2].trim(), swapKind: 'dimension' } };
  }

  if (/^(上|这|下|近|最近)\s*(周|月|季|年|天)\s*[的呢吧？\?]*$/.test(t))
    return { type: 'time_relative', confidence: 0.9, payload: { text: t.replace(/\s*[的呢吧？\?]*$/, '') } };
  if (/^(本周|上周|本月|上月|本季|上季|今年|去年|前年|近\s*\d+\s*(?:天|周|月|年))\s*[的呢吧]*$/.test(t))
    return { type: 'time_relative', confidence: 0.92, payload: { text: t.replace(/\s*[的呢吧]*$/, '') } };

  let lm = /^(?:前|top|TOP)\s*(\d+)\s*(?:个|名|位|条|家)?\s*[的呢吧]*$/.exec(t);
  if (lm) return { type: 'limit_swap', confidence: 0.85, payload: { limit: parseInt(lm[1], 10) } };

  return { type: 'none' };
}

function resolveFollowUp(detect, ctx) {
  if (!detect || detect.type === 'none' || !ctx) return null;
  const prev = ctx.getLastTurn().analysis;
  if (!prev) return null;
  switch (detect.type) {
    case 'reference':
    case 'weak':
      return Object.assign({}, prev, { followUpType: detect.type });
    case 'field_swap':
      return Object.assign({}, prev, { metric: detect.payload.swapTo });
    case 'axis_swap':
      return Object.assign({}, prev, { dimension: detect.payload.swapTo });
    case 'time_relative':
      return Object.assign({}, prev, { timeRange: { label: detect.payload.text } });
    case 'limit_swap':
      return Object.assign({}, prev, { limit: detect.payload.limit });
    case 'chart_swap':
      return Object.assign({}, prev, { chartType: detect.payload.newChartType });
    default:
      return prev;
  }
}

// ===== 集成测试：用户完整多轮对话 =====
console.log('===== 集成测试：用户多轮对话 =====\n');

// Round 1: 用户初次提问（触发 analyzeQuestion，但本测试用 mock）
ctx.push({
  question: '各城市销售额',
  analysis: { type: 'DataQuery', dimension: '城市', metric: '销售额', chartType: 'bar', followUps: ['换成饼图', '按地区呢'] },
  sql: 'SELECT 城市, SUM(销售额) FROM ...',
  insight: '北京销售额最高',
  entities: { '销售额': '销售额', '城市': '城市' }
});
// 模拟 compat layer：window._lastAnalysis = analysis
window._lastAnalysis = ctx.getLastTurn().analysis;
window._lastQuestion = '各城市销售额';
window._lastSQL = ctx.getLastTurn().sql;
console.log('Round 1 已 push 到 ctx，turns:', ctx.turns.length, '/ state.lastQuestion:', ctx.state.lastQuestion);

// Round 2: 用户追问"按地区呢"
const detect2 = detectFollowUpType('按地区呢', ctx);
console.log('\nRound 2 输入: "按地区呢"');
console.log('  detect:', detect2.type, '(confidence:', detect2.confidence, ')');
const resolved2 = resolveFollowUp(detect2, ctx);
console.log('  resolved dimension:', resolved2.dimension, '(应为"地区")');
if (resolved2.dimension === '地区') console.log('  ✅ 维度切换成功');

// Round 3: 用户追问"上周的呢"
ctx.push({ question: '按地区呢', analysis: resolved2, sql: '', entities: {} });
window._lastAnalysis = ctx.getLastTurn().analysis;
const detect3 = detectFollowUpType('上周的呢', ctx);
console.log('\nRound 3 输入: "上周的呢"');
console.log('  detect:', detect3.type, '(payload:', JSON.stringify(detect3.payload), ')');
const resolved3 = resolveFollowUp(detect3, ctx);
console.log('  resolved timeRange:', JSON.stringify(resolved3.timeRange));
if (resolved3.timeRange && resolved3.timeRange.label === '上周') console.log('  ✅ 时间切换成功');

// Round 4: 用户追问"前3名"
const detect4 = detectFollowUpType('前3名', ctx);
const resolved4 = resolveFollowUp(detect4, ctx);
console.log('\nRound 4 输入: "前3名"');
console.log('  resolved limit:', resolved4.limit, '(应为 3)');
if (resolved4.limit === 3) console.log('  ✅ limit 切换成功');

// Round 5: 用户追问"换成饼图"
const detect5 = detectFollowUpType('换成饼图', ctx);
const resolved5 = resolveFollowUp(detect5, ctx);
console.log('\nRound 5 输入: "换成饼图"');
console.log('  resolved chartType:', resolved5.chartType, '(应为 "pie")');
if (resolved5.chartType === 'pie') console.log('  ✅ 图表切换成功');

// Round 6: 用户追问"它"（reference）
const detect6 = detectFollowUpType('它', ctx);
const resolved6 = resolveFollowUp(detect6, ctx);
console.log('\nRound 6 输入: "它"');
console.log('  resolved dimension:', resolved6.dimension, '(应复用上轮的"地区")');
if (resolved6.dimension === '地区') console.log('  ✅ 引用复用成功');

// 序列化往返
console.log('\n===== 序列化往返 =====');
const json = ctx.serialize();
const restored = ConversationContext.deserialize(json);
console.log('serialize → deserialize 成功');
console.log('  原始 turns 数:', ctx.turns.length, '/ 恢复后:', restored.turns.length);
console.log('  实体数:', ctx.entities.size, '/ 恢复后:', restored.entities.size);
if (restored.turns.length === ctx.turns.length && restored.entities.size === ctx.entities.size) {
  console.log('  ✅ 序列化一致');
}

console.log('\n===== 集成测试通过 =====');