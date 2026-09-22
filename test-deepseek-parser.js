// Test: _robustJsonParse handles real DeepSeek output formats

// Extract the actual function from index.html
const fs = require('fs');
const html = fs.readFileSync('E:/数分精灵demo minmax/最新版-数分ai/index.html', 'utf8');
const m = html.match(/function _robustJsonParse\([\s\S]*?\n    \}/);
if (!m) { console.log('FAIL: _robustJsonParse not found'); process.exit(1); }

// Replace 'return null' outside function with throwaway for eval, then eval into a wrapper
const fnSrc = m[0] + '\nreturn _robustJsonParse;';
const parse = new Function(fnSrc)();

// === Realistic DeepSeek responses ===
var cases = [
  {
    name: 'Pure JSON (ideal)',
    input: '{"dimension":"城市","metric":"日营业额(元)","aggregation":"sum"}',
    expect: { dimension: '城市', metric: '日营业额(元)', aggregation: 'sum' }
  },
  {
    name: 'Markdown ```json``` fence',
    input: '```json\n{"dimension":"城市","metric":"日营业额(元)","aggregation":"sum"}\n```',
    expect: { dimension: '城市', metric: '日营业额(元)', aggregation: 'sum' }
  },
  {
    name: 'Pre-amble "好的，我来..."',
    input: '好的，我来帮你分析。\n```json\n{"dimension":"城市","metric":"日营业额(元)"}\n```',
    expect: { dimension: '城市', metric: '日营业额(元)' }
  },
  {
    name: 'Pre-amble "以下是..."',
    input: '以下是分析结果：\n{"dimension":"部门","metric":"薪资","aggregation":"sum"}',
    expect: { dimension: '部门', metric: '薪资', aggregation: 'sum' }
  },
  {
    name: 'Pre-amble "根据..." with newline',
    input: '根据您的数据画像，\n{"dimension":"门店","metric":"日销量(份)"}',
    expect: { dimension: '门店', metric: '日销量(份)' }
  },
  {
    name: 'JSON with trailing junk',
    input: '{"dimension":"城市","metric":"好评率(%)","aggregation":"avg"}\n希望这个结果对您有帮助。',
    expect: { dimension: '城市', metric: '好评率(%)', aggregation: 'avg' }
  },
  {
    name: 'Nested JSON (object inside object)',
    input: '{"dimension":"城市","filters":{"city":"杭州","op":"="}}',
    expect: { dimension: '城市', filters: { city: '杭州', op: '=' } }
  },
  {
    name: 'No JSON at all',
    input: '抱歉，我无法理解这个问题。',
    expect: null
  },
  {
    name: 'Empty string',
    input: '',
    expect: null
  }
];

var pass = 0, fail = 0;
cases.forEach(function(c){
  var got = parse(c.input);
  var gotStr = JSON.stringify(got);
  var expStr = JSON.stringify(c.expect);
  var ok = gotStr === expStr;
  console.log((ok ? '✓ PASS' : '✗ FAIL') + ' [' + c.name + ']');
  if (!ok) {
    console.log('  expected:', expStr);
    console.log('  got:     ', gotStr);
  }
  ok ? pass++ : fail++;
});
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail > 0 ? 1 : 0);