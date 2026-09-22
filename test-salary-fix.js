// Test: getNumericFieldName(question) correctly returns 薪资 for "按部门总结薪资"
// Bug: previously returned 年龄 (first numeric field) because question was ignored

// Mock parsedData with employee-like schema
global.window = global;
global.parsedData = {
  fileName: 'employees.csv',
  columns: ['部门', '姓名', '年龄', '工龄', '薪资', '奖金'],
  fieldInfo: [
    { name: '部门', type: 'text' },
    { name: '姓名', type: 'text' },
    { name: '年龄', type: 'int' },
    { name: '工龄', type: 'int' },
    { name: '薪资', type: 'currency' },
    { name: '奖金', type: 'currency' }
  ],
  rows: [
    ['研发部', '张三', 28, 3, 13920, 2000],
    ['研发部', '李四', 32, 5, 15500, 3000],
    ['运营部', '王五', 26, 2, 12500, 1500]
  ]
};

// Inline the relevant functions for isolated testing
function adaptiveFindMetric(q, numericFields, columns) {
  var _cleanQ = q.replace(/^(平均|均值|平均的|总的|总|最高|最低|最大|最小|最多|最少|多少|各|每个|按|分别|请|帮|查看|看|查|算|计算|统计|求|想|想看|查询|想知道|给我|告诉我|分析下|分析|看下|看看|最[高低大小贵便宜长短快慢]|异常|显著|突出|头部|前|后|末尾|顶部|底部)/g, '')
                 .replace(/(是多少|为多少|多少|呢|吗|的|了|吧|啊|排名|趋势|分布|对比|占比)$/g, '')
                 .replace(/^(总和|总额|总数|平均分|均值|累计|累积|共|总共)/g, '').trim();
  // 0. direct field name match
  for (var i = 0; i < numericFields.length; i++) {
    var base = numericFields[i].replace(/[（(].*$/, '').replace(/\[.*$/, '').trim();
    if (base.length >= 2 && (_cleanQ.indexOf(base) >= 0 || base.indexOf(_cleanQ) >= 0 || q.indexOf(numericFields[i]) >= 0)) {
      return numericFields[i];
    }
  }
  return null;
}

function getNumericFieldName(question) {
  var nfs = (parsedData.fieldInfo || []).filter(function(f) { return ['int','float','currency','percent'].indexOf(f.type) >= 0; });
  if (nfs.length === 0) return null;
  if (question) {
    var hit = adaptiveFindMetric(question, nfs.map(function(f){return f.name;}), (parsedData.columns || []));
    if (hit) return hit;
  }
  var preferred = nfs.find(function(f) {
    var n = f.name.toLowerCase();
    return /额|金额|收入|成本|利润|销量|数量|用户数|次数|费用|营收|营业额|销售额|gmv|交易额|成交额|订单额|消费额|充值额|充值|退订|评分|分数|星级|口碑|好评|差评|好感度|满意度|nps|时长|耗时|响应时间|等待|延迟|客单价|arpu|dau|mau|日活|月活|新增|留存|转化|续费|复购|打开率|点击率|渗透率|市场份额|占有率|占比|rate|percent|sales|revenue|price|amount|volume|gdp|population|expectancy|mpg|horsepower|weight|tip|bill|count|score|rating|duration|delay|wait|薪|工资|薪酬|薪资|报酬|奖金|提成|津贴|补助|工资条|工龄|年龄/.test(n);
  });
  return preferred ? preferred.name : nfs[0].name;
}

// === TESTS ===
var tests = [
  { q: '按部门总结薪资',          expectField: '薪资', desc: 'BUG case: 薪资' },
  { q: '各部门薪资总额',          expectField: '薪资', desc: '薪资 with 各部门' },
  { q: '按部门计算平均薪资',      expectField: '薪资', desc: '平均薪资 → 薪资' },
  { q: '部门的奖金总和',          expectField: '奖金', desc: '奖金' },
  { q: '部门平均年龄',            expectField: '年龄', desc: '平均年龄 → 年龄' },
  { q: '员工平均工龄',            expectField: '工龄', desc: '平均工龄 → 工龄' },
  { q: null,                       expectField: '年龄', desc: 'no question → falls through to 1st numeric' }
];

var pass = 0, fail = 0;
tests.forEach(function(t){
  var got = getNumericFieldName(t.q);
  var ok = got === t.expectField;
  console.log((ok ? '✓ PASS' : '✗ FAIL') + ' [' + t.desc + '] q="' + (t.q||'(null)') + '" → got=' + got + ' expected=' + t.expectField);
  ok ? pass++ : fail++;
});
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail > 0 ? 1 : 0);