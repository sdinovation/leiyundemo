# 数分精灵 · 分析正确性基线报告 v2.3

> **生成时间**: 2026-08-24  
> **范围**: 254 个黄金问题 × 7 个数据集（students/sales/employees/ecommerce_10k/finance/dirty_data/leap_year）  
> **目标**: 上线前所有指标达标，建立可持续回归机制

---

## 🆕 v2.3 Changelog（vs v2.2）

| 变化 | 说明 |
|---|---|
| **总通过率** | 100.0% → **100.0%** (254/254) |
| **黄金集扩容** | 207 → 254 (+47: T118+T119+T202 + 44 new + 3 v2.3-P1: T_DailyAvg/T_DistProd/T_DistCate) |
| **新增类别** | daily_avg |
| **3 个真实 bad case** | 全部修复（详见下方） |
| **数分报告** | P0 双 bug 全修：卡片格式大图渲染 + 数据提亮 |
| **回归保障** | count_distinct 14/14、daily_avg 1/1 全 100% |

### v2.3 真实 bad case 修复明细（用户场景驱动）

| 编号 | 问题 | 修复 | 测试 |
|---|---|---|---|
| T_DailyAvg | "日均交易笔数是多少" 返回 `SUM(销售额)` 完全错 | `parseMetric` 加"日均/平均每天"识别 → metric.label='日均X' → `generateSQL` 生成 `CAST(COUNT(*) AS REAL)/NULLIF(COUNT(DISTINCT 日期),0)` 复合 SQL | T_DailyAvg |
| T_DistProd | "共有多少种不同的产品" 返回 `COUNT(*)=9222` 完全错 | `parseMetric` regex 字符类移除"的"（不再截断字段名）+ "产品/商品/品牌/客户/员工" 语义映射 → `COUNT(DISTINCT 商品名)` | T_DistProd |
| T_DistCate | "共有多少种不同的品类" 返回每品类计数 | `parseAggregation` distinct_count regex 加"不同/不一样" → `COUNT(DISTINCT 品类)` | T_DistCate |

### v2.3 P0 报告双 bug 修复明细

| 编号 | 问题 | 修复 |
|---|---|---|
| 报告卡片格式大图不显示 | `collectReportRounds` 只 capture canvas→dataURL，number/multiNumber 卡片无图 | 同时 capture `cardHtml` 作为 fallback，S5Content 渲染时优先图，否则卡片 |
| 报告数据不亮 | interpretation 与表格数字无视觉提亮 | `highlightNumbersInInterpretation` 用 accent 颜色 + tabular-nums；表格数字单元格加 accent + bold |

---

## v2.1 Changelog（vs v2.0）

| 变化 | 说明 |
|---|---|
| **总通过率** | 96.5% → **100.0%** (199/199) |
| **SQL 准确性** | 98.0% → **100.0%** (199/199) |
| **数据正确性** | 97.5% → **100.0%** (199/199) |
| 4 个核心修复 | T112 (LIKE 样本 50→200) / T175+T194 (闰年 exactDayMatch) / T120+T121 (timeKeywords 加按月) / T197 (显式聚合词→HAVING) |
| **LLM 鲁棒性** | `callLLMviaProxy` 加 25s 超时 + 解读阶段 `showToast` 降级提示 |
| 已知限制 | 7 → 0 条（全量归零，无遗留设计限制） |

### 修复明细

| 编号 | 类别 | 修复点 | 测试 |
|---|---|---|---|
| T112 | 文本搜索 | `parseLikeFilter` 样本 50 → 200 行（10k 数据不漏稀疏值） | 商品名含'手机' |
| T175 | 日期精确 | `parseTimeRange` 新增 `exactDayMatch` 前置于 `ymMatch`，用 `Date.UTC()` 避免时区漂移 | `2024-02-29` |
| T194 | 日期精确 | 同上 | `2024-02-28` |
| T120 | 时间维度 | `parseDimension.timeKeywords` 增补：`按月/分月/各月/每月/月度/按季度/分季度` | 按月统计营收总额 |
| T121 | 时间维度 | 同上 | 按月统计成本总额 |
| T197 | HAVING 分支 | 显式聚合词（总和/累计/汇总/总计/总额/合计）+ 阈值 → 优先 HAVING | 每个城市销售额总和超过5000 |

### 已知限制

**无。** v2.1 全量 100% 通过，所有 20 类别全 100%。

---

## 🆕 v2.0 Changelog（vs v1.0）

| 变化 | 说明 |
|---|---|
| 黄金集扩容 | 81 → 199 条（+145%） |
| 数据集扩展 | 3 → 7 个（含 ecommerce_10k 1 万行） |
| Runner 增强 | 多 JSON 容错 + 逗号剥离 + stddev/variance 白名单 |
| 反幻觉规则 | 100% 通过（逗号剥离修复 1,000 类假阳性） |
| SQL 准确性 | 98.0%（达标 ≥98% 核心） |
| 数据正确性 | 97.5%（接近 100%） |
| 剩余失败 | 7 个 known limitations（已文档化） |

---

## 一、综合指标

| 维度 | 当前 | 上线目标 | 差距 | 状态 |
|---|---|---|---|---|
| **总通过率** | **100.0%** (254/254) | ≥95% | 0 | ✅ 达标 |
| **① SQL 准确性** | **100.0%** (254/254) | ≥98% 核心 / ≥90% 长尾 | 0 | ✅ 达标 |
| **② 数据正确性** | **100.0%** (254/254) | 100% | 0 | ✅ 达标 |
| **③ 解读存在率** | **100.0%** (254/254) | 100% | 0 | ✅ 达标 |
| **④ 反幻觉通过率** | **100.0%** (254/254) | ≥99% | 0 | ✅ 达标 |

> 🟡 接近（≥95%）  🔴 需重点修复  ✅ 已达标

### 1.1 版本对比

| 指标 | v1.0 (81) | v2.0 (199) | **v2.1 (199)** |
|---|---|---|---|
| 总通过率 | 100.0% | 96.5% | **100.0%** |
| SQL 准确性 | 100.0% | 98.0% | **100.0%** |
| 数据正确性 | 100.0% | 97.5% | **100.0%** |
| 解读存在率 | 100.0% | 100.0% | **100.0%** |
| 反幻觉 | 100.0% | 100.0% | **100.0%** |
| **黄金集规模** | **81** | **199** | **199** |

> v2.1 在 v2.0 规模基础上实现 100% 全通过，达到与 v1.0 同等准确度 + 2.5 倍覆盖度。

---

## 二、按类别通过率（薄弱环节识别）

| 类别 | 通过/总数 | 通过率 | 评级 |
|---|---|---|---|
| aggregation_group（按X聚合） | 13/13 | 100% | ✅ |
| scalar_count（标量计数） | 9/9 | 100% | ✅ |
| comparison（对比） | 7/7 | 100% | ✅ |
| multi_condition（多条件 AND） | 7/7 | 100% | ✅ |
| statistic（中位数等统计） | 23/23 | 100% | ✅ |
| ratio（占比） | 7/7 | 100% | ✅ |
| count_distinct（去重计数） | 10/10 | 100% | ✅ |
| ranking_date（日期排序） | 2/2 | 100% | ✅ |
| cumulative（累计） | 5/5 | 100% | ✅ |
| scalar_avg（标量平均） | 5/5 | 100% | ✅ |
| time_after（时间之后） | 5/5 | 100% | ✅ |
| time_before（时间之前） | 4/4 | 100% | ✅ |
| time_range（时间区间） | 6/6 | 100% | ✅ |
| range_filter（BETWEEN） | 7/7 | 100% | ✅ |
| ranking（排名 TopN） | 18/18 | 100% | ✅ |
| threshold_filter（阈值过滤） | 21/21 | 100% | ✅ |
| single_filter（单值过滤） | 21/21 | 100% | ✅ |
| like_filter（LIKE 模糊） | 15/15 | 100% | ✅ |
| trend_group（趋势分组） | 9/9 | 100% | ✅ |
| having（HAVING 条件） | 5/5 | 100% | ✅ |

> v2.1 全 20 类别 100% 通过，无薄弱环节。

---

## 三、Top 薄弱环节（按优先级）— 已全部修复（v2.1）

### ✅ #1 trend_group 趋势分组（v2.0: 7/9 → v2.1: 9/9 = 100%）

**修复内容**: `parseDimension.timeKeywords` 增补 `按月/分月/各月/每月/月度/按季度/分季度` 等
**测试**: T120/T121 finance.csv "按月统计营收/成本总额"

### ✅ #2 having 条件（v2.0: 4/5 → v2.1: 5/5 = 100%）

**修复内容**: 阈值分支识别显式聚合词（总和/累计/汇总/总计/总额/合计）→ 优先走 HAVING
**测试**: T197 "每个城市销售额总和超过5000"

### ✅ #3 threshold_filter / single_filter / like_filter（v2.0: 90-95% → v2.1: 100%）

**修复内容**: T175/T194 (闰年 exactDayMatch) + T112 (LIKE 样本 50→200)
**测试**: T175/T194 leap_year 闰年当日；T112 ecommerce 10k 稀疏 LIKE

---

## 三、Top 薄弱环节（按优先级）— v2.0

### 🟡 #1 trend_group 趋势分组（7/9 = 78%）

**v2.0 阶段全部 7 个 known limitations 已在 v2.1 修复**：T112/T120/T121/T175/T192/T194/T197 全部清零（详见上方 v2.1 Changelog）。

---

## 四、上线前必修清单（Roadmap）

### Phase 0 ✅ 已完成
- [x] 创建黄金集 JSONL（30 条）
- [x] 编写 golden-runner.js 执行器
- [x] 反幻觉基础断言
- [x] 跑出基线：SQL 96.7%、数据 96.7%、反幻觉 53.3%

### Phase 1：地基（1 周）✅ **已完成**
- [x] **修 LIKE**：补全触发关键词 + 加 5 个边界单测
- [x] **修时间之后**：✅ 已修，需在黄金集加 5 个变体（"X月之后"/"X日起"/"X年以后"）
- [x] **修多条件**：✅ 已修，需在黄金集加 5 个变体（"X部且Y>Z"/"X为Y的Z"）
- [x] **修累计**：SQL 生成器改标准窗口函数
- [x] **目标**: 总通过率 ≥80% → **实际 100%** 🎉

### Phase 2：扩展覆盖（1 周）✅ **已完成**
- [x] **新增 4 个数据集**：
  - ecommerce_10k.csv（10,000 行电商订单）
  - finance.csv（24 行财务数据，含同比环比）
  - dirty_data.csv（13 行含缺失值）
  - leap_year.csv（16 行跨年闰年边界）
- [x] **黄金集扩展到 199 条**（v1.0 的 81 条 → v2.0 的 199 条，+145%）
- [x] 覆盖 20 个类别，每类至少 1 条用例（薄弱类如 LIKE 15 条、ranking 18 条、threshold 21 条）
- [x] **目标**: 总通过率 ≥90% → **实际 96.5%** 🎉
- [x] **反幻觉**: 100%（commastrip + stddev/variance 白名单 + 统计量容差）
- [x] **SQL 准确性**: 98.0%（达标 ≥98% 核心）

### Phase 3：反幻觉强化（1 周）⏳ 待启动
- [x] v2.0 已完成：逗号剥离 / stddev 白名单 / 子串匹配 / 统计量容差
- [x] LLM prompt 强约束"只能引用结果数字"（已在 `llmDeepInterpretation` systemPrompt）
- [x] LLM 输出结构化 `[{数字, 来源, 类型}]`（已成 rawResult 透传）
- [x] 后处理层：摘要数字单独校验（黄金集反幻觉 100%）
- [x] **目标**: 反幻觉 ≥99% → **已达100%** ✅

### Phase 3b：上线前鲁棒性（v2.1）✅ **已完成**
- [x] `callLLMviaProxy` 加 25s AbortController 超时
- [x] 解读阶段 `showToast('AI 解读超时/失败，已用本地规则')`
- [x] 综合 AI 增强失败 → `pushErrorLog + showToast` 双出口
- [x] **目标**: LLM 卡死有降级、不再永久转圈 → **已完成**

### Phase 4：CI 集成（3 天）⏳ 待启动
- [ ] 把 golden-runner 接入 CI（GitHub Actions）
- [ ] 覆盖率门禁：核心模块 ≥80%
- [ ] BadCase 自动转回归用例流程
- [ ] **目标**: 每次 PR 自动跑 199 条，< 5 分钟

### Phase 5：监控上线（持续）⏳ 待启动
- [ ] 生产 BadCase 周报
- [ ] 用户反馈 → 自动转回归用例
- [ ] 持续跟踪基线回归（防止引擎改坏历史用例）

---

## 五、上线硬性指标（不可妥协）

| 指标 | 上线门槛 |
|---|---|
| 总通过率 | **≥95%** |
| SQL 准确性 | **≥98%（核心）/ ≥90%（长尾）** |
| 数据正确性 | **100%** |
| 解读存在率 | 100% |
| 反幻觉 | **≥99%** |
| 黄金集规模 | **≥200 条** |
| 黄金集运行时长 | < 5 分钟 |

> **任一指标不达标 → 阻断发布**

---

## 六、附录

### 6.1 黄金集文件清单

```
tests/golden/
├── questions.jsonl          # 199 条问题
├── golden-runner.js         # 执行器（jsdom + js）
├── baseline-report.json     # 最新基线数据
├── BASELINE.md              # 本报告（v2.0）
├── debug.js                 # 单题调试脚本
├── original-81.jsonl        # 原始 81 条（v1.0 黄金集，便于 diff）
├── new-questions.jsonl      # ecommerce 37 条
├── finance-questions.jsonl  # finance 30 条
├── dirty-questions.jsonl    # dirty_data 25 条
├── leap-questions.jsonl     # leap_year 25 条
├── expected/                # 预留：每题独立预期 JSON（结构化 AST）
└── fixtures/                # 预留：扩展数据集

test-datasets/
├── students.csv             # 12 行 (v1.0)
├── sales.csv                # 12 行 (v1.0)
├── employees.csv            # 10 行 (v1.0)
├── ecommerce_10k.csv        # 10000 行 (v2.0 新增)
├── finance.csv              # 24 行 (v2.0 新增)
├── dirty_data.csv           # 13 行 (v2.0 新增)
├── leap_year.csv            # 16 行 (v2.0 新增)
├── generate-ecommerce.js    # 生成脚本
└── generate-extras.js       # 生成脚本
```

### 6.2 v2.0 vs v1.0 主要变化

| 维度 | v1.0 | v2.0 |
|---|---|---|
| 问题数 | 81 | 199 (+145%) |
| 数据集数 | 3 | 7 (+133%) |
| 最大数据集 | 12 行 | 10000 行 |
| 类别数 | 20 | 20 |
| 总通过率 | 100.0% | 96.5% |
| SQL 准确性 | 100.0% | 98.0% |
| 数据正确性 | 100.0% | 97.5% |
| 反幻觉 | 100.0% | 100.0% |

**Runner 关键改进**:
1. 多 JSON-per-line 容错（`}\s*{` → `\n`）
2. 反幻觉：逗号剥离（避免 1,000 误报为 1/000）
3. 反幻觉：stddev/variance/sampleStddev/CV 加入白名单
4. 反幻觉：跨列乘积 + 子集求和

### 6.2 如何运行

```bash
# 跑全量基线
node tests/golden/golden-runner.js

# 单独跑某条
node -e "const r=require('./tests/golden/baseline-report.json'); console.log(r.results.find(x=>x.id==='T01'))"
```

### 6.3 黄金集演进原则

1. **每条用例必须可断言**（SQL/数据/解读三维度）
2. **每类场景至少 5 条**（避免单点测试）
3. **边界场景优先级高于正常场景**（上线红线）
4. **BadCase → 自动入集**（生产问题 ≤7 天进入黄金集）
5. **每条带"预期行数 + 关键校验字符串"**，便于快速诊断

### 6.4 与 run-tests.js 的关系

| 文件 | 用途 |
|---|---|
| `run-tests.js` | **开发态冒烟**（30 条 + 控制台美化输出）|
| `tests/golden/golden-runner.js` | **上市级回归**（结构化 JSONL + 报告） |

两者共用同一个 HTML/PapaParse 环境搭建逻辑，结论一致。  
后续将 run-tests.js 改造为 golden-runner 的薄壳调用，避免维护两套。

---

> **下一步**: 立即进入 **Phase 1**，修复 5 个 Top 薄弱环节，把总通过率从 50% 提升到 ≥80%。