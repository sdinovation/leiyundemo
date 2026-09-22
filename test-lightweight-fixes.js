// Test: Lightweight fixes (synonym map + bad question + date parser excerpts)

// === Test 1: Extended synonym map covers common business terms ===
function findMetricBySynonym(q, numericFields) {
  var _synonymMap = {
    '客户': ['客户','用户','会员','玩家','学员','学生','患者','病人','医生','员工'],
    '订单': ['订单','单','交易','成交','合同','工单','病历','订单数','工单数'],
    '价格': ['价格','单价','均价','定价','售价','标价','成本价','客单价','面价'],
    '利润': ['利润','净利润','毛利润','毛利','盈利','利润率','毛利率','净利率'],
    '成本': ['成本','总成本','费用','支出','成本率','费用率'],
    '转化': ['转化','转化率','转化数','转化金额','注册转化'],
    '复购': ['复购','复购率','回购','回购率','复购数','二次购买'],
    '留存': ['留存','留存率','次日留存','7日留存','30日留存','次留','7留'],
    '曝光': ['曝光','曝光量','曝光数','展现','展现量','PV','impression'],
    '点击': ['点击','点击量','点击数','点击率','CTR','UV','访问量'],
    '客单': ['客单','客单价','ARPU','ARPPU','人均消费','单客价值'],
    '增长': ['增长','增长率','增速','环比','同比','增长率%','增幅'],
    '退订': ['退订','退款','退货','退款率','退货率','取消率','流失'],
    '活跃': ['活跃','日活','周活','月活','DAU','WAU','MAU','活跃用户'],
    '新增': ['新增','新客','新用户','新会员','新增用户','新增客户'],
    '绩效': ['绩效','成绩','得分','考分','分数','总分','KPI','完成率'],
    '工龄': ['工龄','司龄','工龄年','司龄年','入职年数','在职年数'],
    '学分': ['学分','学时','课时','学分总数','GPA','绩点'],
    '营收': ['营收','营业收入','营收额','主营收入','副营收入'],
    '满意度': ['满意度','NPS','推荐意愿','满意度评分','好评率']
  };
  for (var syn in _synonymMap) {
    if (q.indexOf(syn) >= 0) {
      for (var j = 0; j < numericFields.length; j++) {
        var base = numericFields[j].replace(/[（(].*$/, '').trim();
        for (var k = 0; k < _synonymMap[syn].length; k++) {
          if (base === _synonymMap[syn][k] || base.indexOf(_synonymMap[syn][k]) >= 0) return numericFields[j];
        }
      }
    }
  }
  return null;
}

// === Test 2: isBadQuestion blacklist logic ===
function isBadQuestion(question) {
  var qKey = String(question || '').slice(0, 50).trim();
  if (!qKey) return false;
  var badQ = { '按部门总结薪资': { ts: 1 }, '哪些菜品最受欢迎': { ts: 2 } };
  for (var k in badQ) {
    if (qKey.indexOf(k) >= 0 || k.indexOf(qKey) >= 0) return true;
  }
  return false;
}

// === Test 3: Date patterns ===
function parseExtendedTimeRange(q) {
  if (/年初至今|YTD|今年至今|本年/.test(q)) return 'YTD';
  if (/本季度|本季|Q[1-4]\s*(?:至今)?/i.test(q)) return 'current_quarter';
  if (/上季度|上季/.test(q)) return 'last_quarter';
  if (/上半年/.test(q)) return 'h1';
  if (/下半年/.test(q)) return 'h2';
  if (/本月|当月/.test(q)) return 'current_month';
  if (/上月/.test(q)) return 'last_month';
  if (/去年/.test(q)) return 'last_year';
  if (/截至|截止/.test(q)) return 'as_of';
  return null;
}

// === RUN ===
var tests = [
  // Synonym tests
  { cat: 'synonym', name: '客户 → 客户数', q: '客户总数', fields: ['客户数','销售额'], expect: '客户数' },
  { cat: 'synonym', name: '转化 → 转化率', q: '转化率', fields: ['转化率','点击率'], expect: '转化率' },
  { cat: 'synonym', name: '复购 → 复购率', q: '复购率', fields: ['复购率','订单数'], expect: '复购率' },
  { cat: 'synonym', name: 'DAU → 日活', q: 'DAU是多少', fields: ['日活','月活'], expect: '日活' },
  { cat: 'synonym', name: '工龄 → 工龄(年)', q: '平均工龄', fields: ['工龄(年)','薪资'], expect: '工龄(年)' },
  { cat: 'synonym', name: '退订 → 退款率', q: '退款率', fields: ['退款率','订单数'], expect: '退款率' },
  { cat: 'synonym', name: '客单 → 客单价', q: '客单价', fields: ['客单价','订单数'], expect: '客单价' },

  // Bad question tests
  { cat: 'badq', name: 'exact match', q: '按部门总结薪资', expect: true },
  { cat: 'badq', name: 'partial prefix', q: '按部门总结薪资和人数', expect: true },
  { cat: 'badq', name: 'substring match', q: '部门总结薪资', expect: true },
  { cat: 'badq', name: 'unrelated question', q: '各城市销售额排名', expect: false },
  { cat: 'badq', name: 'empty', q: '', expect: false },

  // Date tests
  { cat: 'date', name: 'YTD', q: 'YTD 销售额', expect: 'YTD' },
  { cat: 'date', name: '本季度', q: '本季度的销售', expect: 'current_quarter' },
  { cat: 'date', name: 'Q2', q: 'Q2 营收', expect: 'current_quarter' },
  { cat: 'date', name: '上半年', q: '上半年的销售额', expect: 'h1' },
  { cat: 'date', name: '本月', q: '本月的销量', expect: 'current_month' },
  { cat: 'date', name: '上月', q: '上月的销量', expect: 'last_month' },
  { cat: 'date', name: '截至', q: '截至目前的总营收', expect: 'as_of' },
  { cat: 'date', name: '去年', q: '去年的销售', expect: 'last_year' }
];

var pass = 0, fail = 0;
tests.forEach(function(t){
  var got;
  if (t.cat === 'synonym') got = findMetricBySynonym(t.q, t.fields);
  else if (t.cat === 'badq') got = isBadQuestion(t.q);
  else if (t.cat === 'date') got = parseExtendedTimeRange(t.q);
  var ok = got === t.expect;
  console.log((ok ? '✓' : '✗') + ' [' + t.cat + '] ' + t.name + ' → got=' + JSON.stringify(got) + (ok ? '' : ' (expected ' + JSON.stringify(t.expect) + ')'));
  ok ? pass++ : fail++;
});
console.log('\n' + pass + ' passed, ' + fail + ' failed');
process.exit(fail > 0 ? 1 : 0);