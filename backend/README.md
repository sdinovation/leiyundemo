# 数分精灵 — Flask 后端

## 当前状态：Stage 6 完整版（全部 6 个阶段完成）

✅ **Stage 0** — 前端 HttpQueryService 接入
✅ **Stage 1** — Flask 应用骨架 + 数据层
✅ **Stage 2** — 6 个核心服务（DataManager / SQLGenerator / SQLExecutor / DataProfiler / ChartConfigGenerator / FieldInference）
✅ **Stage 3** — LLM Function Calling（function_schema + 16 条规则 prompt + 异步客户端）
✅ **Stage 4** — FAISS 语义缓存（L1 精确 + L2 FAISS，优雅降级）
✅ **Stage 5** — 7 个业务蓝图 + 8 个 API 端点 + Rule Engine + Insight Generator
✅ **Stage 6** — 启动脚本 + 文档 + 端到端验证

后端响应形状与前端 `HttpQueryService` 契约对齐（`{sql, data, chart_config, insight, ...}`），不需要前端适配。

---

## 快速开始

### 1. 安装依赖

```bash
# Windows（推荐）
cd backend
run_dev.bat

# 或手动
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
copy .env.example .env
# 编辑 .env，填入 LLM_API_KEY（DeepSeek / OpenAI 等 OpenAI 兼容服务）
```

最小配置（未配置 LLM Key 时也能用纯规则引擎）：
```ini
LLM_API_KEY=sk-your-deepseek-key  # 不填也能用基础功能
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 3. 启动服务

```bash
# 开发模式（run_dev.bat 已封装）
python -m flask run --host=0.0.0.0 --port=5000

# 生产模式
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
```

### 4. 与前端联调

1. 双击 `../index.html`（前端）
2. 上传测试数据（如 `restaurant_menu_test.csv`）
3. 打开诊断面板 → 点击 "后端 (Flask)" → `QueryService.setSource('backend', {backendUrl: 'http://localhost:5000'})`
4. 提问 → 应走 Flask 后端
5. 关闭后端再提问 → 应自动降级到 local 模式（toast 提示）

---

## 项目结构

```
backend/
├── app.py                       # Flask 应用工厂（注册蓝图 + 错误处理）
├── wsgi.py                      # 生产部署入口（gunicorn 加载）
├── requirements.txt              # Python 依赖
├── run_dev.bat                  # Windows 开发启动脚本
├── .env.example                 # 环境变量模板
├── README.md                    # 本文件
│
├── config.py                    # 全局配置（路径/LLM/Embedding/FAISS/Flask/CORS）
│
├── models/                      # SQLAlchemy 模型层
│   ├── database.py              # Engine + Session + init_db
│   ├── dataset.py               # Dataset 元信息
│   ├── query_history.py         # 查询历史
│   └── cache_entry.py           # 缓存条目（question_vector BLOB 编码）
│
├── core/                        # 核心服务层
│   ├── data_manager.py          # 文件上传 / 数据集管理
│   ├── field_inference.py       # 字段类型推断（前端移植）
│   ├── data_profiler.py         # 数据画像构建
│   ├── sql_executor.py          # SQL 执行器（带安全校验）
│   ├── sql_generator.py         # SQL 生成器（规则引擎路径）
│   ├── chart_config_generator.py  # 图表配置生成器
│   ├── rule_engine.py           # 规则引擎（LLM 降级路径）
│   ├── insight_generator.py     # 自动洞察生成器
│   └── query_processor.py       # 查询编排器（核心）
│
├── llm/                         # LLM 集成层
│   ├── function_schema.py       # execute_data_query JSON Schema
│   ├── prompts.py               # 16 条规则 system prompt
│   └── llm_client.py            # 异步 LLM 客户端（重试 + fallback parse）
│
├── cache/                       # 缓存层
│   ├── embedding_model.py       # Sentence Transformer 单例
│   └── semantic_cache.py        # L1 + L2 FAISS 语义缓存
│
├── api/                         # API 路由层
│   ├── errors.py                # 统一错误处理
│   ├── upload.py                # POST /api/upload
│   ├── query.py                 # POST /api/query
│   ├── schema.py                # GET /api/schema
│   ├── history.py               # GET /api/history
│   ├── insight.py               # POST /api/insight
│   ├── cache.py                 # GET /api/cache/stats, POST /api/cache/invalidate
│   └── dataset.py               # GET /api/dataset, DELETE /api/dataset/<id>
│
└── data/                        # 运行时数据（自动创建）
    ├── uploads/                 # 上传的原始文件
    ├── sqlite/                  # 每数据集一个 SQLite 文件
    ├── faiss/                   # FAISS 索引
    ├── logs/                    # 应用日志
    └── metadata.db              # 元数据库（Dataset / QueryHistory / CacheEntry）
```

---

## API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/` | 端点索引（调试用） |
| GET | `/api/health` | 健康检查（含 LLM/Embedding/Cache 状态） |
| POST | `/api/upload` | 上传文件（multipart/form-data）→ 创建数据集 |
| POST | `/api/query` | **核心** — 自然语言查询，返回 SQL + 数据 + 图表配置 |
| GET | `/api/schema?dataset_id=xxx` | 获取数据集 schema |
| GET | `/api/history?dataset_id=xxx&page=1&per_page=20` | 查询历史（分页） |
| POST | `/api/insight` | 数据集整体洞察报告 |
| GET | `/api/cache/stats` | 缓存统计 |
| POST | `/api/cache/invalidate` | 失效指定数据集的缓存 |
| GET | `/api/dataset` | 列出所有数据集 |
| DELETE | `/api/dataset/<id>` | 删除数据集（级联清理 SQLite + 缓存 + 历史） |

---

## POST /api/query 请求/响应示例

### 请求

```json
{
  "question": "各部门平均薪资",
  "dataset_id": "ds-1723294800-abc123"
}
```

### 响应（成功）

```json
{
  "success": true,
  "data": {
    "query_id": "q-6b6e90...",
    "dataset_id": "ds-1723294800-abc123",
    "question": "各部门平均薪资",
    "sql": "SELECT \"部门\", AVG(\"薪资\") AS \"avg_薪资\" FROM \"data\" GROUP BY \"部门\" ORDER BY 2 DESC LIMIT 10",
    "data": {
      "columns": ["部门", "avg_薪资"],
      "rows": [
        {"部门": "技术", "avg_薪资": 20500.0},
        {"部门": "产品", "avg_薪资": 15000.0}
      ],
      "row_count": 2
    },
    "chart_config": {
      "type": "bar",
      "x_field": "部门",
      "y_field": "avg_薪资",
      "categories": ["技术", "产品"],
      "values": [20500.0, 15000.0],
      "aggregation": "avg",
      "intent": "ranking",
      "row_count": 2
    },
    "chart_data": {
      "categories": ["技术", "产品"],
      "values": [20500.0, 15000.0],
      "metric": "avg_薪资",
      "dimension": "部门"
    },
    "insight": "技术 的 avg_薪资 最高，为 20.50K。前 3 名依次为：技术、产品、销售。销售 最低（12.00K）。",
    "analysis": {
      "intent": "ranking",
      "dimension": "部门",
      "metric": "薪资",
      "aggregation": "avg",
      ...
    },
    "cached": false,
    "cache_level": "miss",
    "response_time_ms": 45,
    "llm_tokens_used": null
  }
}
```

### 响应（错误）

```json
{
  "success": false,
  "error": {
    "code": "DATASET_NOT_FOUND",
    "message": "数据集 ds-xxx 不存在",
    "details": {}
  }
}
```

---

## 数据流

```
POST /api/query
    ↓
QueryProcessor.process()
    ↓
1. DataManager.get_dataset()
    ↓
2. DataProfiler.build_data_profile()  → Markdown 画像
    ↓
3+4. SemanticCache.lookup()
       ├─ L1: MD5(question + dataset_id) → CacheEntry 表查询
       └─ L2: encode(question) + FAISS.search() (cosine ≥ 0.92)
    ↓ 命中
    ↓ 返回缓存结果（cached=true）
    ↓
5. LLM Function Calling (LLMClient.analyze_question)
       ├─ execute_data_query JSON Schema + 16 条规则 system prompt
       ├─ OpenAI 兼容 API（DeepSeek / OpenAI / 其他）
       └─ 失败时重试 2 次 + fallback parse
    ↓
6. RuleEngine.classify()  ← LLM 失败时降级
    ↓
7. SQLGenerator.generate()  → SQL 字符串
       ├─ LLM 路径：validate_llm_sql()（白名单校验）
       └─ 规则路径：从 analysis dict 生成 SQL
    ↓
8. SQLExecutor.execute()  → {columns, rows, row_count}
       ├─ 安全校验（关键字/注释/多语句）
       ├─ 字段白名单
       └─ SQLite 执行
    ↓
9. ChartConfigGenerator.generate()  → 前端 ECharts 配置
    ↓
10. InsightGenerator.generate()  → 2-4 句中文洞察
       ├─ 统计模式（兜底）
       └─ LLM 模式（增强）
    ↓
11. SemanticCache.store()  → 写回 L1 + L2
    ↓
12. QueryHistory 记录
    ↓
13. 返回完整 JSON（与前端 HttpQueryService 契约一致）
```

---

## 性能验收标准

| 指标 | 目标 | 实测 |
|------|------|------|
| 健康检查延迟 | < 50ms | ✅ |
| L1 缓存命中 | < 10ms | ✅ |
| L2 FAISS 检索 | < 30ms | 取决于 embedding |
| SQL 执行（执行 | < 200ms（10万行） | SQLite 性能 |
| LLM Function Calling | < 3s（DeepSeek） | 网络正常 |
| 规则引擎（降级） | < 50ms | ✅ |

---

## 已知限制 / 不在本期范围

- ❌ 用户认证 / 多租户（单用户本地工具）
- ❌ Docker 镜像 / K8s 部署（用 gunicorn 即可）
- ❌ FAISS 增量更新（数据集失效时重建索引）

---

## 常见问题

### Q: 不配置 LLM_API_KEY 能用吗？
A: 可以。LLM 缺失时自动降级到规则引擎，支持基础分析（各XX/按XX 排名/汇总/计数/趋势）。Function Calling 和 LLM 增强洞察不可用。

### Q: faiss/sentence-transformers 安装失败？
A: L2 缓存自动降级到 L1-only，FAISS 不可用时所有查询仍能正常返回。

### Q: 中文字段名怎么用？
A: SQL 生成器自动用 `"中文字段名"` 双引号包裹（SQLite 标识符需双引号）。前端不变。

### Q: 与前端契约对齐吗？
A: 是的。所有 API 响应（除额外的 query_id/response_time_ms）都使用前端 HttpQueryService 期望的字段名（`sql`/`data`/`chart_config`/`insight`），前端 0 改动。

### Q: 数据存在哪？
A: `backend/data/` 下：
- `uploads/` 原始文件
- `sqlite/{dataset_id}.db` 每数据集一个 SQLite
- `metadata.db` 元数据库（Dataset / QueryHistory / CacheEntry）
- `faiss/semantic_cache.index` FAISS 索引