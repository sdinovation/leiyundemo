// Test: LLM-vs-rule arbitration logic
// Verifies that when classifyIntent is confident, LLM suggestions are NOT blindly overridden

// Simulate the orchestration logic from analyzeQuestion
var dimensionFields = ['门店名称', '城市', '菜品类别', '菜品名称'];
var numericFields = ['单价(元)', '日销量(份)', '日营业额(元)', '好评率(%)', '差评数', '制作时长(分钟)', '食材成本(元)'];

function arbitrate(ruleConfident, ruleDim, ruleMetric, llmResult) {
  var dimension = ruleDim;
  var metric = ruleMetric;
  var _aiDim = llmResult.dimension ? dimensionFields.find(function(f) {
    return f === llmResult.dimension || f.indexOf(llmResult.dimension) >= 0 || llmResult.dimension.indexOf(f) >= 0;
  }) : null;
  var _aiMet = llmResult.metric ? numericFields.find(function(f) {
    return f === llmResult.metric || f.indexOf(llmResult.metric) >= 0 || llmResult.metric.indexOf(f) >= 0;
  }) : null;

  if (_aiDim && (!ruleConfident || !dimension)) dimension = _aiDim;
  if (_aiMet && (!ruleConfident || !metric || !metric.field)) metric = { field: _aiMet, label: _aiMet };
  return { dimension: dimension, metric: metric, llmDimSuggestion: _aiDim, llmMetSuggestion: _aiMet };
}

var tests = [
  {
    name: 'Rules confident, LLM agrees — keep rules',
    ruleConfident: true,
    ruleDim: '城市', ruleMetric: { field: '日营业额(元)' },
    llmResult: { dimension: '城市', metric: '日营业额(元)' },
    expect: { dimension: '城市', metricField: '日营业额(元)', llmDimSuggestion: '城市', llmMetSuggestion: '日营业额(元)' }
  },
  {
    name: 'Rules confident, LLM WRONG — keep rules (THE KEY FIX)',
    ruleConfident: true,
    ruleDim: '城市', ruleMetric: { field: '日销量(份)' },
    llmResult: { dimension: '菜品名称', metric: '好评率(%)' },  // DeepSeek hallucinated
    expect: { dimension: '城市', metricField: '日销量(份)', llmDimSuggestion: '菜品名称', llmMetSuggestion: '好评率(%)' }
  },
  {
    name: 'Rules NOT confident, LLM fills the gap',
    ruleConfident: false,
    ruleDim: null, ruleMetric: null,
    llmResult: { dimension: '门店名称', metric: '差评数' },
    expect: { dimension: '门店名称', metricField: '差评数' }
  },
  {
    name: 'Rules confident on dim only, LLM fills metric',
    ruleConfident: true,
    ruleDim: '城市', ruleMetric: null,
    llmResult: { dimension: '城市', metric: '日营业额(元)' },
    expect: { dimension: '城市', metricField: '日营业额(元)' }
  },
  {
    name: 'LLM suggests nonexistent field — filtered out',
    ruleConfident: false,
    ruleDim: null, ruleMetric: null,
    llmResult: { dimension: '总分数', metric: 'transformed_score' },
    expect: { dimension: null, metricField: null }
  },
  {
    name: 'LLM suggests partial-match via substring',
    ruleConfident: false,
    ruleDim: null, ruleMetric: null,
    llmResult: { dimension: '城市名', metric: '营业额' },
    expect: { dimension: '城市', metricField: '日营业额(元)' }
  }
];

var pass = 0, fail = 0;
tests.forEach(function(t){
  var got = arbitrate(t.ruleConfident, t.ruleDim, t.ruleMetric, t.llmResult);
  var matches = (got.dimension || null) === t.expect.dimension &&
               ((got.metric && got.metric.field) || null) === t.expect.metricField;
  var llmKept = ((got.llmDimSuggestion || null) === (t.llmResult.dimension ? (dimensionFields.find(function(f){return f===t.llmResult.dimension || f.indexOf(t.llmResult.dimension)>=0 || t.llmResult.dimension.indexOf(f)>=0;}) || null) : null)) && ((got.llmMetSuggestion || null) === (t.llmResult.metric ? (numericFields.find(function(f){return f===t.llmResult.metric || f.indexOf(t.llmResult.metric)>=0 || t.llmResult.metric.indexOf(f)>=0;}) || null) : null));
  var ok = matches && llmKept;
  console.log((ok ? '✓ PASS' : '✗ FAIL') + ' [' + t.name + ']');
  if (!ok) {
    console.log('  expected:', JSON.stringify(t.expect));
    console.log('  got:     ', JSON.stringify(got));
  }
  ok ? pass++ : fail++;
});
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail > 0 ? 1 : 0);