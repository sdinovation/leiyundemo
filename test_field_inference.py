"""Quick sanity test for backend field_inference port."""
import sys
sys.path.insert(0, 'backend')
from core.field_inference import (
    infer_field_type, infer_field_info, infer_field_info_from_records,
    compute_type_distribution, get_numeric_fields, get_text_fields,
)

passed = failed = 0
def check(name, got, expected):
    global passed, failed
    ok = got == expected
    print(f'  {"✓" if ok else "✗"} {name}: got={got!r}{"" if ok else f" expected={expected!r}"}')
    if ok: passed += 1
    else: failed += 1

# Basic type inference
print('--- Single field inference ---')
check('日期字段', infer_field_type('日期', []), 'date')
check('时间字段', infer_field_type('created_time', []), 'date')
check('货币字段', infer_field_type('销售额', []), 'currency')
check('英文货币', infer_field_type('revenue', []), 'currency')
check('百分比字段', infer_field_type('增长率', []), 'percent')
check('英文percent', infer_field_type('growth_rate', []), 'percent')
check('ID字段', infer_field_type('id', []), 'text')
check('编号字段', infer_field_type('产品编号', []), 'text')
check('整数字段', infer_field_type('销量', [10, 20, 30]), 'int')
check('浮点字段', infer_field_type('评分', [4.5, 3.8, 4.2]), 'float')
check('空值默认', infer_field_type('随便', []), 'text')

# Uniqueness check (ID-like)
check('高唯一值的name=ID → text', infer_field_type('订单ID', [1, 2, 3, 4, 5]), 'text')
check('低唯一值 → int', infer_field_type('部门ID', [1, 1, 1, 2, 2]), 'int')
check('数值但name含"量" → int', infer_field_type('访问量', [10, 20, 30]), 'int')

# Field info
print('\n--- infer_field_info (array mode) ---')
columns = ['日期', '城市', '销售额', '好评率']
rows = [
    ['2024-01-01', '杭州', 1000, 95.5],
    ['2024-01-02', '北京', 1500, 88.0],
    ['2024-01-03', '上海', 2000, 92.0],
]
info = infer_field_info(columns, rows)
check('日期 type', info[0]['type'], 'date')
check('城市 type', info[1]['type'], 'text')
check('销售额 type', info[2]['type'], 'currency')
check('好评率 type', info[3]['type'], 'percent')
check('字段信息项数', len(info), 4)
check('nullRate 格式', info[0]['nullRate'], '0.0%')

# Records mode
print('\n--- infer_field_info_from_records (dict mode) ---')
records = [
    {'日期': '2024-01-01', '城市': '杭州', '销售额': 1000},
    {'日期': '2024-01-02', '城市': '北京', '销售额': 1500},
]
info2 = infer_field_info_from_records(columns, records)
check('records 模式日期 type', info2[0]['type'], 'date')
check('records 模式货币 type', info2[2]['type'], 'currency')

# Type distribution
print('\n--- compute_type_distribution ---')
dist = compute_type_distribution(info)
print(f'  distribution: {dist}')
check('分布包含中文标签', any(d['name'] in ['日期/时间', '货币', '文本'] for d in dist), True)

# Field extraction helpers
print('\n--- Helper functions ---')
check('get_numeric_fields', get_numeric_fields(info), ['销售额', '好评率'])
check('get_text_fields', get_text_fields(info), ['城市'])
check('get_date_fields', get_date_fields(info), ['日期'])

print(f'\n{passed} passed, {failed} failed')
sys.exit(0 if failed == 0 else 1)
