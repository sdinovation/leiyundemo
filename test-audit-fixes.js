// Combined test for all audit-driven fixes

// === Fix #1: learnedMetrics reader supports column-name-keyed entries ===
function adaptiveFindMetricWithLearned(q, numericFields, learnedMetrics) {
  for (var histQ in learnedMetrics) {
    if (q.indexOf(histQ) >= 0 || histQ.indexOf(q.slice(0, 10)) >= 0) {
      var learnedMet = learnedMetrics[histQ];
      if (typeof learnedMet !== 'string') continue;
      var m = numericFields.find(function(f){return f === learnedMet;});
      if (m) return m;
    }
  }
  // Fix: column-name keyed entries
  for (var _colKey in learnedMetrics) {
    var _entry = learnedMetrics[_colKey];
    if (typeof _entry === 'object' && _entry !== null) {
      if (numericFields.indexOf(_colKey) >= 0) {
        var _cleanKey = _colKey.replace(/[（(].*$/, '').trim();
        if (_cleanKey.length >= 2 && (q.indexOf(_cleanKey) >= 0 || q.indexOf(_colKey) >= 0)) return _colKey;
      }
    }
  }
  return null;
}

// === Fix #5: isHavingCond regex ===
function isHavingCond(q) {
  return /(?:平均|均值|总和|总计|累计)(?:[一-龥a-zA-Z_（（\(\)]+)?(?:超过|大于|高于|不低于|>|<|>=|<=)\s*\d/.test(q) && /的/.test(q) && !/(?:趋势|走势|变化|对比|比较|关系|相关|分布)/.test(q);
}

// === Fix #10: parseLikeFilter not-like support ===
function parseLikeFilterOp(q) {
  var negative = /(?:不包含|不含|不含有|不带有|没包含|没含|没有.*?含|没有.*?带)/.test(q);
  var match = q.match(/(?:包含|含有|带有|包括|含)(.{1,10}?)(?:的|产品|商品|记录|数据|项目|信息|名称)/);
  if (!match) return null;
  return { op: negative ? 'NOT LIKE' : 'LIKE', value: match[1].trim() };
}

// === RUN ALL TESTS ===
var passed = 0, failed = 0;
function check(name, got, expect) {
  var ok = JSON.stringify(got) === JSON.stringify(expect);
  console.log((ok ? '✓' : '✗') + ' ' + name + ' → got=' + JSON.stringify(got) + (ok ? '' : ' expected=' + JSON.stringify(expect)));
  ok ? passed++ : failed++;
}

console.log('--- Fix #1: learnedMetrics column-name-keyed ---');
var learned = { '日营业额(元)': { trainedAt: 1, source: 'llm' }, '营收': 'legacy_string_value' };
check('LLM-trained entry matches question', adaptiveFindMetricWithLearned('日营业额总和', ['日营业额(元)','好评率(%)'], learned), '日营业额(元)');
check('Legacy string entry still works', adaptiveFindMetricWithLearned('营收是多少', ['日营业额(元)'], learned), null);
check('No match returns null', adaptiveFindMetricWithLearned('随便问问', ['日营业额(元)'], {}), null);

console.log('\n--- Fix #5: isHavingCond ---');
check('好评率大于90% → NOT HAVING', isHavingCond('好评率大于90%的产品'), false);
check('差评数超过5 → NOT HAVING', isHavingCond('差评数超过5的门店'), false);
check('平均评分超过4.5 → IS HAVING', isHavingCond('平均评分超过4.5的城市'), true);
check('累计营收大于50万 → IS HAVING', isHavingCond('累计营收大于50万的客户'), true);
check('趋势关键字排除 → NOT HAVING', isHavingCond('平均价格趋势'), false);

console.log('\n--- Fix #10: parseLikeFilter 不包含 ---');
check('包含X → LIKE', parseLikeFilterOp('包含苹果的产品'), { op: 'LIKE', value: '苹果' });
check('不包含X → NOT LIKE', parseLikeFilterOp('不包含苹果的产品'), { op: 'NOT LIKE', value: '苹果' });
check('不含X → NOT LIKE', parseLikeFilterOp('不含测试的数据'), { op: 'NOT LIKE', value: '测试' });
check('不含有X → NOT LIKE', parseLikeFilterOp('不含有内部的数据'), { op: 'NOT LIKE', value: '内部' });
check('没有...含X → NOT LIKE', parseLikeFilterOp('没有包含草稿的订单'), { op: 'NOT LIKE', value: '草稿' });

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed > 0 ? 1 : 0);