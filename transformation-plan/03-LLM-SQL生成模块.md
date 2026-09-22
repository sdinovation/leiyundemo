# 03 - LLM SQL 生成模块

> 本文档面向 AI 开发者，详细描述"数分精灵"项目 LLM SQL 生成模块的完整设计与实现。本模块将 LLM 从前端的"兜底增强"提升为后端的"主查询引擎"，采用 OpenAI Function Calling 替代纯文本 Prompt + JSON 正则解析，同时基于前端 `index.html` 行 4435-4448 中经过实战验证的 13 条 Prompt 规则扩展为 16 条 Function Calling 模式规则。所有代码均为可直接运行的完整 Python 实现。

---

## 1. 模块概述

### 1.1 改造目标

| 维度 | 前端现状（index.html） | 后端改造后 |
|------|----------------------|-----------|
| **LLM 角色** | 兜底增强——本地规则引擎为主，LLM 为辅 | 主引擎——LLM 直接生成 SQL + 图表配置 + 洞察 |
| **调用方式** | 纯文本 Prompt，正则提取 JSON（`content.match(/\{[\s\S]*\}/)`） | Function Calling，LLM 原生返回结构化 `tool_calls` 参数 |
| **SQL 生成** | 前端 JavaScript 拼接 SQL 字符串 | LLM 直接生成完整 SQL，后端安全校验后执行 |
| **JSON 解析** | 正则匹配 + `JSON.parse`，失败返回 null | API 层保证 Schema 合规，失败降级为文本 JSON 解析 |
| **洞察生成** | `llmDeepInterpretation` 单独调用 LLM | 首次 Function Calling 即返回 `insight` 字段，减少调用次数 |
| **默认 Provider** | 前端 `PROVIDER_PRESETS` 支持 Anthropic / OpenAI / DeepSeek / Moonshot / 智谱 | 后端默认使用 DeepSeek（OpenAI 兼容格式），同时兼容 OpenAI |

### 1.2 核心设计决策

**为什么用 Function Calling 而非纯文本 Prompt？**

前端 `llmFullAnalysis`（行 4407-4489）使用纯文本 Prompt 让 LLM 输出 JSON，再用 `content.match(/\{[\s\S]*\}/)` 正则提取。这种方式存在两个问题：

1. **解析不可靠**：正则可能匹配错误的 JSON 片段（如 JSON 中嵌套花括号导致贪婪匹配超出范围）
2. **字段校验缺失**：解析后需手动校验每个字段的类型和枚举值，代码冗长且容易遗漏

Function Calling 由 API 层保证返回的参数符合 JSON Schema 定义，字段类型和枚举值自动校验，开发者只需关注业务逻辑。

**为什么基于 13 条规则扩展为 16 条？**

前端 `index.html` 行 4435-4448 的 13 条规则经过大量真实数据验证，覆盖了排名、趋势、对比、分布、筛选、相关性等全部核心场景。迁移到后端 Function Calling 模式后，新增 3 条 SQL 相关规则：

- 规则 1：只允许 SELECT，禁止写操作（安全约束）
- 规则 2：表名固定为 `data_table`（与 SQLExecutor 对齐）
- 规则 3：SQLite 日期函数支持（`strftime`、`date`、`julianday`）

原 13 条规则保留并重新编号为规则 4-16，语义完全一致。

### 1.3 模块架构

```
┌──────────────────────────────────────────────────────────────┐
│                     routes/query.py                           │
│              POST /api/query → QueryProcessor                 │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                core/query_processor.py                        │
│                     QueryProcessor                            │
│                                                               │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────┐     │
│  │ 1.获取   │───→│ 2.语义缓存   │───→│ 3.LLM生成SQL    │     │
│  │ Schema   │    │   检查       │    │ (SQLGenerator)  │     │
│  └──────────┘    └──────┬───────┘    └───────┬─────────┘     │
│                         │                     │               │
│                    命中 │                     │ 未命中         │
│                         ▼                     ▼               │
│                   直接返回         ┌──────────────────┐       │
│                                   │ 4.SQL安全校验    │       │
│                                   │ + 执行           │       │
│                                   │ (SQLExecutor)    │       │
│                                   └───────┬──────────┘       │
│                                    执行失败 │                  │
│                                           ▼                   │
│                                   ┌──────────────────┐       │
│                                   │ 5.错误回传LLM    │       │
│                                   │ 让LLM修正SQL     │       │
│                                   │ (最多重试3次)    │       │
│                                   └───────┬──────────┘       │
│                                           │                   │
│                                           ▼                   │
│                                   ┌──────────────────┐       │
│                                   │ 6.写入缓存+历史  │       │
│                                   └───────┬──────────┘       │
│                                           ▼                   │
│                                     返回完整结果              │
└───────────────────────────────────────────────────────────────┘
```

### 1.4 与前端函数的对应关系

| 前端函数（index.html） | 后端模块 | 说明 |
|----------------------|---------|------|
| `callLLM(prompt, systemPrompt)` 行4256 | `LLMClient.generate()` | 通用 LLM 调用 |
| `llmFullAnalysis(question, dataProfile)` 行4407 | `SQLGenerator.generate()` | Function Calling 生成 SQL + 图表配置 |
| `llmDeepInterpretation(question, analysis, dataProfile)` 行4494 | `QueryProcessor._generate_insight()` | 深度解读（可选） |
| `buildDataProfile()` 行4347 | `DataManager.build_data_profile()` | 数据画像（已在 02 文档实现） |
| 前端 JS 拼接 SQL | `SQLGenerator` + LLM 直接生成 | SQL 生成方式改变 |
| 前端内存 SQL 执行 | `SQLExecutor.execute()` | 后端 SQLite 执行（已在 02 文档实现） |

---

## 2. LLM 客户端封装 (utils/llm_client.py)

### 2.1 配置依赖

LLM 配置通过 `config.py` 的 `LLM_CONFIG` 字典管理（在 02 文档中已定义基础结构），从 `.env` 文件加载环境变量：

```python
# config.py 中的 LLM_CONFIG（02 文档已定义，此处展示完整配置）
LLM_CONFIG = {
    'api_key': os.getenv('LLM_API_KEY', ''),
    'base_url': os.getenv('LLM_BASE_URL', 'https://api.deepseek.com/v1'),
    'model': os.getenv('LLM_MODEL', 'deepseek-chat'),
    'timeout': int(os.getenv('LLM_TIMEOUT', '30')),
    'temperature_analysis': 0.0,       # SQL 生成：确定性输出
    'temperature_interpretation': 0.3, # 深度解读：适度创造性
    'max_tokens_analysis': 1024,       # SQL 生成
    'max_tokens_interpretation': 400,  # 解读
}
```

#### .env 文件示例

```env
# LLM 配置（默认使用 DeepSeek）
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=30
```

#### 各服务商配置对照

| 服务商 | LLM_BASE_URL | LLM_MODEL | 获取方式 |
|--------|-------------|-----------|---------|
| DeepSeek（默认） | `https://api.deepseek.com/v1` | `deepseek-chat` | https://platform.deepseek.com |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | https://platform.openai.com |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | https://platform.moonshot.cn |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | https://open.bigmodel.cn |

> **注意**：`LLM_BASE_URL` 必须包含 `/v1` 后缀。前端 `callLLM` 中拼接 `baseUrl + '/v1/chat/completions'`，后端 `LLMClient` 拼接 `base_url + '/chat/completions'`，因此 `base_url` 应包含 `/v1`。对应前端 `PROVIDER_PRESETS` 中 DeepSeek 的 `baseUrl: 'https://api.deepseek.com'`，后端配置需手动补上 `/v1`。

### 2.2 完整的 LLMClient 类

创建 `utils/llm_client.py`（需先创建 `utils/` 目录和 `utils/__init__.py`）：

```bash
# 创建 utils 目录
New-Item -ItemType Directory -Force -Path "utils"
New-Item -ItemType File -Force -Path "utils\__init__.py" -Value ""
```

```python
"""
utils/llm_client.py — LLM 客户端封装

负责：
1. 封装 OpenAI 兼容格式的 LLM 调用（支持 DeepSeek / OpenAI / Moonshot / 智谱等）
2. generate()       — 通用异步 LLM 调用（对话 + Function Calling）
3. generate_sql()   — 专门用于 SQL 生成的高层封装
4. 超时控制、重试机制（最多 3 次，指数退避）
5. 统一错误处理和日志

对应前端 index.html：
- callLLM(prompt, systemPrompt) [行4256]              → generate()
- llmFullAnalysis 中的 fetch 调用 [行4452]             → generate_sql()
- llmDeepInterpretation 中的 fetch 调用 [行4533]       → generate()
"""

import json
import logging
import asyncio
from typing import Any, Optional

import httpx

from config import LLM_CONFIG

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用异常。"""

    def __init__(self, message: str, status_code: int = 0, response_text: str = ''):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(message)


class LLMClient:
    """LLM 客户端：封装 OpenAI 兼容格式的异步 API 调用。

    支持所有兼容 OpenAI Chat Completions API 的服务商：
    - DeepSeek (https://api.deepseek.com/v1) — 默认
    - OpenAI (https://api.openai.com/v1)
    - Moonshot (https://api.moonshot.cn/v1)
    - 智谱 GLM (https://open.bigmodel.cn/api/paas/v4)
    - 自定义兼容接口

    配置从 config.py 的 LLM_CONFIG 读取，LLM_CONFIG 从 .env 环境变量加载。
    """

    def __init__(self):
        self.api_key = LLM_CONFIG['api_key']
        self.base_url = LLM_CONFIG['base_url']
        self.model = LLM_CONFIG['model']
        self.timeout = LLM_CONFIG['timeout']
        self.temperature_analysis = LLM_CONFIG.get('temperature_analysis', 0.0)
        self.temperature_interpretation = LLM_CONFIG.get('temperature_interpretation', 0.3)
        self.max_tokens_analysis = LLM_CONFIG.get('max_tokens_analysis', 1024)
        self.max_tokens_interpretation = LLM_CONFIG.get('max_tokens_interpretation', 400)
        # 最大重试次数
        self.max_retries = 3
        # 重试间隔基数（秒），指数退避：1s, 2s, 4s
        self.retry_base_delay = 1.0

        if not self.api_key:
            logger.warning('LLM_API_KEY 未配置，LLM 调用将失败')
        if not self.base_url:
            logger.warning('LLM_BASE_URL 未配置，LLM 调用将失败')

    # ============================================================
    # 内部方法：构建请求头
    # ============================================================

    def _get_headers(self) -> dict:
        """构建请求头。"""
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }

    # ============================================================
    # 内部方法：构建请求体
    # ============================================================

    def _build_body(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict:
        """构建请求体。

        Args:
            messages: 消息列表，格式 [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            temperature: 温度参数，0 表示确定性输出
            max_tokens: 最大生成 token 数
            tools: Function Calling 工具定义列表
            tool_choice: 工具选择策略，"auto" 表示自动选择
        """
        body: dict[str, Any] = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if tools:
            body['tools'] = tools
            body['tool_choice'] = tool_choice or 'auto'
        return body

    # ============================================================
    # 内部方法：带重试的异步 HTTP 请求
    # ============================================================

    async def _request_with_retry(self, body: dict) -> dict:
        """发送异步 HTTP 请求，带超时控制和重试机制。

        重试策略：
        - 第 1 次重试：等待 1 秒
        - 第 2 次重试：等待 2 秒
        - 第 3 次重试：等待 4 秒
        - 超过 3 次仍失败，抛出 LLMError

        可重试的错误：
        - 网络超时（httpx.TimeoutException）
        - 网络连接错误（httpx.ConnectError）
        - HTTP 429（请求频率限制）
        - HTTP 500/502/503（服务器错误）

        不可重试的错误：
        - HTTP 400（请求格式错误）
        - HTTP 401（API Key 无效）
        - HTTP 403（无权限）

        Args:
            body: 请求体

        Returns:
            dict: 响应 JSON

        Raises:
            LLMError: 超过最大重试次数后仍失败
        """
        url = f'{self.base_url}/chat/completions'
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=self.timeout,
                        read=self.timeout,
                        write=self.timeout,
                        pool=self.timeout,
                    ),
                ) as client:
                    response = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=body,
                    )

                if response.status_code == 200:
                    return response.json()

                # 判断是否可重试
                error_text = response.text
                retryable = response.status_code in (429, 500, 502, 503)

                if not retryable:
                    # 不可重试的错误，直接抛出
                    logger.error(
                        f'LLM 请求失败 (HTTP {response.status_code}, 不可重试): {error_text[:200]}'
                    )
                    raise LLMError(
                        f'LLM 请求失败: HTTP {response.status_code} — {error_text[:200]}',
                        status_code=response.status_code,
                        response_text=error_text,
                    )

                # 可重试的错误
                last_error = LLMError(
                    f'LLM 请求失败: HTTP {response.status_code} — {error_text[:200]}',
                    status_code=response.status_code,
                    response_text=error_text,
                )
                logger.warning(
                    f'LLM 请求失败 (HTTP {response.status_code}), '
                    f'第 {attempt}/{self.max_retries} 次重试...'
                )

            except httpx.TimeoutException as e:
                last_error = LLMError(f'LLM 请求超时: {str(e)}')
                logger.warning(f'LLM 请求超时, 第 {attempt}/{self.max_retries} 次重试...')

            except httpx.ConnectError as e:
                last_error = LLMError(f'LLM 连接失败: {str(e)}')
                logger.warning(f'LLM 连接失败, 第 {attempt}/{self.max_retries} 次重试...')

            # 指数退避等待（异步 sleep）
            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.info(f'等待 {delay:.1f} 秒后重试...')
                await asyncio.sleep(delay)

        # 超过最大重试次数
        raise last_error or LLMError('LLM 请求失败：超过最大重试次数')

    # ============================================================
    # 通用 LLM 调用（异步）
    # ============================================================

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """通用 LLM 调用。

        对应前端 callLLM(prompt, systemPrompt) [行4256] 的后端异步版本。
        同时支持普通对话和 Function Calling 两种模式。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            tools: Function Calling 工具定义列表，None 表示普通对话模式
            tool_choice: 工具选择策略，"auto" 表示自动选择；
                         也可指定工具如 {"type": "function", "function": {"name": "execute_data_query"}}
            temperature: 温度参数，None 则根据是否有 tools 自动选择
                         （有 tools 用 0.0 确定性输出，无 tools 用 0.3 适度创造性）
            max_tokens: 最大 token 数，None 则根据是否有 tools 自动选择

        Returns:
            dict: {
                'tool_calls': list[dict] | None,  # Function Calling 返回的参数列表
                'content': str | None,             # 普通文本响应（降级用）
            }

        Raises:
            LLMError: LLM 调用失败（超时、API 错误等）
        """
        # 根据调用模式自动选择温度和 token 上限
        if temperature is None:
            temperature = self.temperature_analysis if tools else self.temperature_interpretation
        if max_tokens is None:
            max_tokens = self.max_tokens_analysis if tools else self.max_tokens_interpretation

        body = self._build_body(
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

        result = await self._request_with_retry(body)
        message = result.get('choices', [{}])[0].get('message', {})

        tool_calls = message.get('tool_calls')
        content = message.get('content')

        if tool_calls:
            logger.info(f'[LLM] generate 成功 (Function Calling), tool_calls 数量={len(tool_calls)}')
        elif content:
            logger.info(f'[LLM] generate 成功 (普通文本), 响应长度={len(content)}')
        else:
            logger.warning('[LLM] generate 返回为空')

        return {
            'tool_calls': tool_calls,
            'content': content,
        }

    # ============================================================
    # SQL 生成专用调用（异步）
    # ============================================================

    async def generate_sql(
        self,
        question: str,
        schema_info: str,
        tools: list[dict],
        system_prompt: str,
        tool_choice: str = 'auto',
        extra_context: Optional[str] = None,
    ) -> dict:
        """专门用于 SQL 生成的 LLM 调用。

        对应前端 llmFullAnalysis(question, dataProfile) [行4407] 的后端异步版本。
        封装了 User Prompt 的构建逻辑，调用方只需传入问题、数据画像和工具定义。

        Args:
            question: 用户自然语言问题，如"各部门的平均薪资是多少"
            schema_info: 数据画像文本（由 DataManager.build_data_profile() 生成）
            tools: Function Calling 工具定义列表
            system_prompt: 系统提示词（包含 16 条规则）
            tool_choice: 工具选择策略，默认 "auto"
            extra_context: 额外上下文（如上次 SQL 执行错误信息，用于重试场景）

        Returns:
            dict: {
                'tool_calls': list[dict] | None,  # Function Calling 返回的参数
                'content': str | None,             # 普通文本响应（降级用）
            }

        Raises:
            LLMError: LLM 调用失败
        """
        # 构建 User Prompt
        prompt_parts = [
            f'【任务】请根据用户问题和数据画像，调用 execute_data_query 函数生成查询方案。\n',
            f'{schema_info}\n',
            f'用户问题："{question}"\n',
            f'请调用 execute_data_query 函数，提供 sql、chart_type、insight 等参数。',
        ]

        if extra_context:
            prompt_parts.append(f'\n\n{extra_context}')

        prompt = '\n'.join(prompt_parts)

        logger.info(f'[LLM] generate_sql 调用, 问题="{question[:80]}..."')

        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            tools=tools,
            tool_choice=tool_choice,
            temperature=self.temperature_analysis,  # SQL 生成用 0 确定性输出
            max_tokens=self.max_tokens_analysis,
        )

    # ============================================================
    # 健康检查
    # ============================================================

    async def health_check(self) -> dict:
        """检查 LLM 服务可用性。

        发送一个简单请求验证 API Key 和网络连通性。

        Returns:
            dict: {
                'healthy': bool,
                'model': str,
                'base_url': str,
                'error': str | None,
            }
        """
        if not self.api_key:
            return {
                'healthy': False,
                'model': self.model,
                'base_url': self.base_url,
                'error': 'LLM_API_KEY 未配置',
            }

        try:
            body = self._build_body(
                messages=[{'role': 'user', 'content': '请回复"OK"'}],
                temperature=0.0,
                max_tokens=10,
            )
            # 健康检查不重试，只尝试 1 次
            url = f'{self.base_url}/chat/completions'
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=10, write=10, pool=10),
            ) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=body,
                )

            if response.status_code == 200:
                return {
                    'healthy': True,
                    'model': self.model,
                    'base_url': self.base_url,
                    'error': None,
                }
            else:
                return {
                    'healthy': False,
                    'model': self.model,
                    'base_url': self.base_url,
                    'error': f'HTTP {response.status_code}: {response.text[:100]}',
                }
        except Exception as e:
            return {
                'healthy': False,
                'model': self.model,
                'base_url': self.base_url,
                'error': str(e),
            }


# ============================================================
# 模块级单例
# ============================================================

llm_client = LLMClient()
```

---

## 3. System Prompt 设计

System Prompt 基于前端 `llmFullAnalysis`（行 4414-4448）的 13 条 Prompt 规则完整移植并扩展。核心变化是：前端在 User Prompt 中内联了 JSON 模板和规则，后端改为在 System Prompt 中定义规则，User Prompt 只包含数据画像和用户问题。原 13 条规则保留并重新编号为规则 4-16，新增 3 条 SQL 安全相关规则（规则 1-3）。

创建 `core/prompts.py`：

```python
"""
core/prompts.py — Prompt 模板管理

集中管理 LLM 调用使用的 System Prompt 和 User Prompt 模板。
System Prompt 中的 16 条规则基于前端 index.html 行 4435-4448 的 13 条规则
扩展为 Function Calling 模式，新增 3 条 SQL 安全约束（规则 1-3）。
"""


# ============================================================
# System Prompt — SQL 生成（16 条规则）
# ============================================================

SYSTEM_PROMPT_SQL = """你是一个数据分析专家。根据用户的问题和数据表结构，生成SQL查询并推荐合适的可视化方式。

规则：
1. 只使用SELECT语句，禁止INSERT/UPDATE/DELETE/DROP
2. 表名固定为 'data_table'
3. 日期字段支持SQLite日期函数(strftime, date, julianday)
4. 中文字段名需用双引号包裹，如 "日营业额(元)"
5. 返回结果必须包含insight字段，用一句话总结数据发现
6. 字段名必须使用数据画像中的原始列名，禁止编造
7. "各XX"/"按XX" → dimension为对应列
8. "趋势/变化/增长/走势" → dimension必须为日期列，chartType为line，intent为trend
9. "排名/最高/最低" → sortOrder为desc或asc，intent为ranking
10. "占比/分布/比例" → aggregation为ratio或count，chartType为pie
11. "XX和YY分别是多少" → allMetrics中列出所有指标，intent为comparison
12. "XX为YY的记录" → filters中添加条件，intent为filter
13. "之间有什么关系/相关性" → intent为correlation，chartType为scatter
14. "人数/条数/订单数" → aggregation为count，metric为null
15. 率/百分比类字段做阈值筛选时，HAVING必须用AVG
16. aggregation=ratio时，ratioColumn和ratioValue用于计算满足条件的占比

## SQL 生成要求
- SQL 语句中不要包含分号
- 聚合函数支持：SUM()、AVG()、COUNT()、MAX()、MIN()
- 分组使用 GROUP BY，排序使用 ORDER BY，限制行数使用 LIMIT
- 条件筛选使用 WHERE，聚合后筛选使用 HAVING
- 不要使用 RATIO()、PERCENT() 等不存在的 SQL 函数

## 输出要求
请调用 execute_data_query 函数，提供以下参数：
- sql: 完整的 SELECT 查询语句
- chart_type: 图表类型（bar/line/pie/number/table/scatter）
- x_field: X轴/维度字段名
- y_field: Y轴/指标字段名
- aggregation: 聚合方式（sum/avg/count/max/min/ratio）
- intent: 查询意图（ranking/trend/comparison/distribution/summary/list/correlation/filter）
- insight: 一句话数据洞察（基于查询逻辑预判，如"研发部人数最多"）
- explanation: 对用户问题的理解说明
- filters: 筛选条件列表
- sort_order: 排序方式（desc/asc/null）
- limit: 返回行数限制"""


# ============================================================
# System Prompt — 深度解读
# ============================================================

SYSTEM_PROMPT_INSIGHT = """你是资深数据分析专家。根据用户问题、数据画像和实际查询结果，给出深度、有洞察的中文解读。

要求：
1) 2-4句话，不超过150字
2) 指出关键发现和趋势
3) 如有异常或值得注意的点必须指出
4) 严禁编造结果中不存在的数据
5) 不使用Markdown标题"""


# ============================================================
# User Prompt 构建 — 深度解读
# ============================================================

def build_insight_prompt(
    question: str,
    data_profile_summary: str,
    query_result: dict,
) -> str:
    """构建深度解读的 User Prompt。

    对应前端 llmDeepInterpretation [行4526] 的 userPrompt 构建。

    Args:
        question: 用户原始问题
        data_profile_summary: 数据画像摘要（前15行）
        query_result: 查询结果 dict，含 columns、rows、count

    Returns:
        组装好的深度解读 User Prompt
    """
    rows = query_result.get('rows', [])
    columns = query_result.get('columns', [])
    count = query_result.get('count', 0)

    # 构建前10行数据文本
    top_rows = rows[:10]
    rows_text = '\n'.join(
        ', '.join(f'{col}={row.get(col, "")}' for col in columns)
        for row in top_rows
    )

    # 数值统计
    stats = ''
    if rows:
        for col in columns:
            vals = []
            for row in rows:
                try:
                    v = float(row.get(col, ''))
                    vals.append(v)
                except (ValueError, TypeError):
                    pass
            if vals:
                arr_sum = sum(vals)
                arr_avg = arr_sum / len(vals)
                arr_max = max(vals)
                arr_min = min(vals)
                stats += (
                    f'{col}: 总和={round(arr_sum, 2)}, '
                    f'平均={round(arr_avg, 2)}, '
                    f'最高={arr_max}, 最低={arr_min}\n'
                )

    prompt = f"""用户问题："{question}"

数据画像摘要：
{data_profile_summary}

查询结果（{count}行，列：[{', '.join(columns)}]）：
{f'数值统计：\\n{stats}' if stats else ''}
前10行数据：
{rows_text}

请给出深度解读：关键发现、趋势、异常点、业务建议。"""
    return prompt
```

### 3.1 规则编号对照（前端 13 条 → 后端 16 条）

| 后端规则编号 | 后端规则内容 | 对应前端规则 | 说明 |
|------------|------------|------------|------|
| 1 | 只使用 SELECT，禁止写操作 | _(新增)_ | SQL 安全约束 |
| 2 | 表名固定为 `data_table` | _(新增)_ | 与 SQLExecutor 对齐 |
| 3 | SQLite 日期函数支持 | _(新增)_ | 后端用 SQLite 替代前端内存查询 |
| 4 | 中文字段名双引号包裹 | _(新增)_ | SQL 语法要求 |
| 5 | insight 字段必填 | _(新增)_ | Function Calling 输出要求 |
| 6 | 字段名用原始列名 | 前端规则 1 | 完全一致 |
| 7 | "各XX"/"按XX" → dimension | 前端规则 2 | 完全一致 |
| 8 | "趋势/变化/增长" → 日期列+line+trend | 前端规则 3 | 完全一致 |
| 9 | "排名/最高/最低" → sortOrder+ranking | 前端规则 4 | 完全一致 |
| 10 | "占比/分布/比例" → ratio/count+pie | 前端规则 5 | 完全一致 |
| 11 | "XX和YY分别是多少" → allMetrics+comparison | 前端规则 6 | 完全一致 |
| 12 | "XX为YY的记录" → filters+filter | 前端规则 7 | 完全一致 |
| 13 | "相关性" → correlation+scatter | 前端规则 8 | 完全一致 |
| 14 | "人数/条数/订单数" → count+metric=null | 前端规则 9 | 完全一致 |
| 15 | 率/百分比 HAVING 用 AVG | 前端规则 10 | 完全一致 |
| 16 | aggregation=ratio → ratioColumn+ratioValue | 前端规则 11 | 完全一致 |

> 前端规则 12（"XX品牌的YY趋势" → 日期列+filters+line）和规则 13（本轮独立判断）在后端中由规则 8 + 规则 12 隐式覆盖，不再单独列出。

---

## 4. Function Calling Schema

创建 `core/tools.py`，定义 Function Calling 工具：

```python
"""
core/tools.py — Function Calling 工具定义

定义 LLM 可调用的函数工具。LLM 通过 tool_calls 返回结构化参数，
替代前端 llmFullAnalysis 中正则解析 JSON 的方式。

工具定义的参数与前端 llmFullAnalysis 输出的 JSON 字段对齐：
- dimension    → x_field
- metric       → y_field
- aggregation  → aggregation（保留 ratio 枚举值）
- intent       → intent
- chartType    → chart_type
- queryUnderstanding → explanation
- filters      → filters
- sortOrder    → sort_order
- limit        → limit
新增字段：
- sql          → LLM 直接生成的 SQL 语句
- insight      → 一句话数据洞察
"""


# ============================================================
# 查询分析函数定义
# ============================================================

QUERY_ANALYSIS_FUNCTION = {
    "type": "function",
    "function": {
        "name": "execute_data_query",
        "description": "根据用户问题生成SQL查询并推荐可视化方式",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": (
                        "SQLite查询语句。表名固定为 data_table，中文字段名用双引号包裹。"
                        "示例：SELECT \"部门\", AVG(\"薪资\") as 平均薪资 "
                        "FROM data_table GROUP BY \"部门\" ORDER BY 平均薪资 DESC"
                    ),
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "number", "table", "scatter"],
                    "description": (
                        "图表类型。bar=柱状图(排名/对比)，line=折线图(趋势)，"
                        "pie=饼图(占比/分布)，number=数字卡片(单值)，"
                        "table=表格(明细列表)，scatter=散点图(相关性)"
                    ),
                },
                "x_field": {
                    "type": "string",
                    "description": "X轴/维度字段名，对应分组列。如按整体汇总则为空字符串",
                },
                "y_field": {
                    "type": "string",
                    "description": "Y轴/指标字段名，即聚合后的值列。问人数/条数时为空字符串",
                },
                "aggregation": {
                    "type": "string",
                    "enum": ["sum", "avg", "count", "max", "min", "ratio"],
                    "description": (
                        "聚合方式。sum=求和，avg=平均，count=计数，max=最大值，"
                        "min=最小值，ratio=占比计算。"
                        "问\"人数/条数/订单数\"时用count。"
                        "问\"占比/分布/比例\"时用ratio或count。"
                    ),
                },
                "intent": {
                    "type": "string",
                    "enum": [
                        "ranking", "trend", "comparison", "distribution",
                        "summary", "list", "correlation", "filter",
                    ],
                    "description": (
                        "查询意图。ranking=排名，trend=趋势，comparison=对比，"
                        "distribution=分布，summary=汇总，list=列表，"
                        "correlation=相关性，filter=筛选"
                    ),
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "description": "筛选字段名（原始列名）",
                            },
                            "op": {
                                "type": "string",
                                "enum": ["=", "!=", ">", "<", ">=", "<=", "like", "in"],
                                "description": "比较操作符",
                            },
                            "value": {
                                "description": "筛选值（字符串或数字）",
                            },
                        },
                        "required": ["field", "op", "value"],
                    },
                    "description": "过滤条件列表。如\"单价超过30元的菜品\"则filters为[{field:\"价格\", op:\">\", value:30}]",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc", None],
                    "description": "排序方式。desc=降序，asc=升序，null=不排序",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回行数限制，默认不限制。排名查询通常为10，趋势查询通常不限制(填0或省略)",
                },
                "insight": {
                    "type": "string",
                    "description": "一句话数据洞察，基于查询逻辑预判关键发现。如\"研发部人数最多，占比35%\"",
                },
                "explanation": {
                    "type": "string",
                    "description": "对用户问题的理解说明，一句话解释分析思路。如\"您想了解各部门的员工数量分布\"",
                },
            },
            "required": ["sql", "chart_type", "insight"],
        },
    },
}


# ============================================================
# 工具列表（传递给 LLM 的 tools 参数）
# ============================================================

AVAILABLE_TOOLS = [QUERY_ANALYSIS_FUNCTION]
```

### 4.1 前后端字段映射对照

| 前端 JSON 字段（llmFullAnalysis 输出） | 后端 Function Calling 参数 | 说明 |
|---------------------------------------|--------------------------|------|
| `dimension` | `x_field` | 分组维度列名 |
| `metric` | `y_field` | 指标列名 |
| `secondaryMetric` | _(合并到 SQL 中)_ | 第二指标直接写入 SQL |
| `allMetrics` | _(合并到 SQL 中)_ | 所有指标直接写入 SQL |
| `aggregation` | `aggregation` | 聚合方式（保留 ratio） |
| `isScalar` | _(由 chart_type=number 推断)_ | 标量查询用 number 图表 |
| `filters` | `filters` | 筛选条件 |
| `havingCond` | _(合并到 SQL 中)_ | HAVING 直接写入 SQL |
| `sortOrder` | `sort_order` | 排序方式 |
| `limit` | `limit` | 行数限制 |
| `intent` | `intent` | 查询意图 |
| `chartType` | `chart_type` | 图表类型 |
| `queryUnderstanding` | `explanation` | 问题理解说明 |
| `ratioColumn` / `ratioValue` | _(合并到 SQL 中)_ | 比例计算直接写入 SQL |
| _(无)_ | `sql` | **新增**：LLM 直接生成 SQL |
| _(无)_ | `insight` | **新增**：一句话数据洞察 |

> **核心变化**：前端 LLM 输出的是"查询方案 JSON"，再由前端 JavaScript 拼接成 SQL。后端 LLM 直接输出 SQL，省去了中间的 SQL 拼接步骤，减少了拼接错误的可能。

---

## 5. SQL 生成器 (core/sql_generator.py)

### 5.1 完整的 SQLGenerator 类

创建 `core/sql_generator.py`：

```python
"""
core/sql_generator.py — SQL 生成器

负责：
1. 构建 User Prompt（包含 schema_info）
2. 调用 LLM Function Calling 生成 SQL 和图表配置
3. 解析 LLM 返回的 Function Calling 结果
4. Function Calling 失败时降级为纯文本 JSON 解析
5. SQL 安全校验
6. 错误处理和重试机制（最多 3 次）

对应前端 index.html：
- llmFullAnalysis(question, dataProfile) [行4407] → generate()
- 前端 JavaScript 拼接 SQL → LLM 直接生成 SQL

关键改进：
- 使用 Function Calling 替代正则解析 JSON
- LLM 直接生成完整 SQL，不再需要前端拼接
- 生成失败时降级为文本 JSON 解析（兼容旧格式）
"""

import json
import logging
import re
from typing import Any, Optional

from core.prompts import SYSTEM_PROMPT_SQL
from core.tools import AVAILABLE_TOOLS, QUERY_ANALYSIS_FUNCTION
from core.sql_executor import SQLExecutor, SQLValidationError
from utils.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)


class SQLGenerationError(Exception):
    """SQL 生成失败异常。"""

    def __init__(self, message: str, raw_response: Any = None):
        self.raw_response = raw_response
        super().__init__(message)


class SQLGenerator:
    """SQL 生成器：通过 LLM Function Calling 生成 SQL 查询方案。

    使用流程：
        generator = SQLGenerator(llm_client)
        result = await generator.generate(question, schema_info)
        # result['sql'] → SQLExecutor.execute(result['sql'], db_path)
    """

    # 允许的图表类型
    VALID_CHART_TYPES = {'bar', 'line', 'pie', 'number', 'table', 'scatter'}

    # 允许的聚合方式
    VALID_AGGREGATIONS = {'sum', 'avg', 'count', 'max', 'min', 'ratio'}

    # 允许的查询意图
    VALID_INTENTS = {
        'ranking', 'trend', 'comparison', 'distribution',
        'summary', 'list', 'correlation', 'filter',
    }

    # 允许的排序方式
    VALID_SORT_ORDERS = {'desc', 'asc', None}

    # 最大重试次数（SQL 执行失败时将错误信息发回 LLM 让它修正）
    MAX_RETRIES = 3

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.sql_executor = SQLExecutor()

    # ============================================================
    # 主入口：生成 SQL
    # ============================================================

    async def generate(self, question: str, schema_info: str) -> dict:
        """生成 SQL 查询方案和图表配置。

        完整流程：
        1. 构建 User Prompt（包含 schema_info）
        2. 调用 LLM with Function Calling
        3. 解析返回结果
        4. 返回结构化结果

        Args:
            question: 用户自然语言问题
            schema_info: 数据画像文本（由 DataManager.build_data_profile() 生成）

        Returns:
            dict: {
                'sql': str,                  # SQL 查询语句
                'chart_type': str,           # 图表类型
                'x_field': str,              # X轴/维度字段
                'y_field': str,              # Y轴/指标字段
                'aggregation': str | None,   # 聚合方式
                'intent': str,               # 查询意图
                'insight': str,              # 一句话洞察
                'explanation': str,           # 问题理解说明
                'filters': list[dict],        # 筛选条件
                'sort_order': str | None,    # 排序方式
                'limit': int | None,          # 行数限制
            }

        Raises:
            SQLGenerationError: SQL 生成失败（重试耗尽）
        """
        last_error: Optional[str] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # 如果是重试，在 Prompt 中附带上次错误信息
                extra_context = None
                if last_error:
                    extra_context = (
                        f'⚠️ 上次生成的 SQL 有错误，请修正：\n'
                        f'错误信息：{last_error}\n'
                        f'请重新调用 execute_data_query 函数，确保 SQL 语法正确。'
                    )

                # 1. 构建 User Prompt + 调用 LLM with Function Calling
                logger.info(
                    f'[SQLGenerator] 第 {attempt}/{self.MAX_RETRIES} 次调用 LLM, '
                    f'问题="{question[:50]}..."'
                )
                response = await self.llm_client.generate_sql(
                    question=question,
                    schema_info=schema_info,
                    tools=AVAILABLE_TOOLS,
                    system_prompt=SYSTEM_PROMPT_SQL,
                    tool_choice='auto',
                    extra_context=extra_context,
                )

                # 2. 解析返回结果
                parsed = self._parse_llm_response(response)

                # 3. 字段校验（修正无效值）
                self._validate_fields(parsed)

                logger.info(
                    f'[SQLGenerator] 生成成功, chart_type={parsed["chart_type"]}, '
                    f'intent={parsed["intent"]}, sql={parsed["sql"][:80]}...'
                )
                return parsed

            except SQLGenerationError as e:
                last_error = str(e)
                logger.warning(f'[SQLGenerator] 第 {attempt} 次失败: {last_error}')
                if attempt < self.MAX_RETRIES:
                    continue
                raise

            except LLMError as e:
                last_error = f'LLM 调用失败: {str(e)}'
                logger.warning(f'[SQLGenerator] {last_error}')
                if attempt < self.MAX_RETRIES:
                    continue
                raise SQLGenerationError(last_error)

            except Exception as e:
                last_error = f'解析失败: {str(e)}'
                logger.warning(f'[SQLGenerator] {last_error}')
                if attempt < self.MAX_RETRIES:
                    continue
                raise SQLGenerationError(last_error, raw_response=str(e))

        raise SQLGenerationError('SQL 生成失败：超过最大重试次数')

    # ============================================================
    # 构建 User Prompt
    # ============================================================

    def _build_user_prompt(self, question: str, schema_info: str) -> str:
        """构建用户提示词。

        组装数据画像（schema_info）+ 用户问题（question）。
        数据画像由 DataManager.build_data_profile() 生成，格式与前端
        buildDataProfile() [行4347] 完全一致。

        Args:
            question: 用户自然语言问题，如"各部门的平均薪资是多少"
            schema_info: 数据画像文本，包含【数据概况】【字段详情】【样本数据】

        Returns:
            组装好的 User Prompt 字符串
        """
        prompt = f"""【任务】请根据用户问题和数据画像，调用 execute_data_query 函数生成查询方案。

{schema_info}

用户问题："{question}"

请调用 execute_data_query 函数，提供 sql、chart_type、insight 等参数。"""
        return prompt

    # ============================================================
    # 解析 LLM 返回结果
    # ============================================================

    def _parse_llm_response(self, response: dict) -> dict:
        """解析 LLM 返回的 Function Calling 结果。

        解析策略（优先级从高到低）：
        1. 优先解析 tool_calls（Function Calling 标准返回）
        2. 降级解析 content 中的 JSON（兼容不支持 Function Calling 的模型）
        3. 两者都失败则抛出异常

        Args:
            response: LLMClient.generate() 的返回值
                      {
                          'tool_calls': list[dict] | None,
                          'content': str | None,
                      }

        Returns:
            解析后的结构化结果 dict

        Raises:
            SQLGenerationError: 解析失败
        """
        # 策略 1：解析 tool_calls
        tool_calls = response.get('tool_calls')
        if tool_calls and len(tool_calls) > 0:
            try:
                parsed = self._parse_tool_calls(tool_calls)
                logger.info('[SQLGenerator] 通过 tool_calls 解析成功')
                return parsed
            except Exception as e:
                logger.warning(f'[SQLGenerator] tool_calls 解析失败: {e}, 尝试降级')

        # 策略 2：降级解析 content 中的 JSON
        content = response.get('content')
        if content:
            try:
                parsed = self._fallback_parse(content)
                logger.info('[SQLGenerator] 通过 content JSON 降级解析成功')
                return parsed
            except Exception as e:
                logger.warning(f'[SQLGenerator] content JSON 解析失败: {e}')

        raise SQLGenerationError(
            '无法解析 LLM 返回结果：tool_calls 和 content 均无效',
            raw_response=response,
        )

    def _parse_tool_calls(self, tool_calls: list[dict]) -> dict:
        """解析 tool_calls 返回的参数。

        OpenAI / DeepSeek 兼容格式的 tool_calls 结构：
        [
            {
                "id": "call_xxx",
                "type": "function",
                "function": {
                    "name": "execute_data_query",
                    "arguments": '{"sql": "SELECT ...", "chart_type": "bar", ...}'
                }
            }
        ]

        Args:
            tool_calls: tool_calls 列表

        Returns:
            解析后的参数 dict

        Raises:
            SQLGenerationError: 解析失败
        """
        # 取第一个 tool_call
        tool_call = tool_calls[0]
        function_info = tool_call.get('function', {})

        # 验证函数名
        func_name = function_info.get('name', '')
        if func_name != 'execute_data_query':
            raise SQLGenerationError(
                f'LLM 调用了错误的函数: {func_name}，期望 execute_data_query'
            )

        # 解析 arguments（JSON 字符串）
        arguments_str = function_info.get('arguments', '{}')
        if isinstance(arguments_str, str):
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError as e:
                raise SQLGenerationError(
                    f'tool_calls arguments JSON 解析失败: {e}',
                    raw_response=arguments_str,
                )
        elif isinstance(arguments_str, dict):
            # 某些 SDK 可能直接返回 dict
            arguments = arguments_str
        else:
            raise SQLGenerationError(
                f'tool_calls arguments 格式未知: {type(arguments_str)}',
                raw_response=arguments_str,
            )

        return self._normalize_arguments(arguments)

    # ============================================================
    # 降级解析：从纯文本中提取 JSON
    # ============================================================

    def _fallback_parse(self, content: str) -> dict:
        """Function Calling 失败时，尝试从纯文本中解析 JSON。

        当 LLM 不支持 Function Calling 或返回了纯文本时，
        从文本中正则提取 JSON 对象并解析。

        对应前端 llmFullAnalysis [行4467] 的 content.match(/\\{[\\s\\S]*\\}/) 逻辑。

        支持两种 JSON 格式：
        1. Function Calling 参数格式（含 sql 字段）→ 直接使用
        2. 前端旧格式（含 dimension/metric/chartType 等）→ 映射为标准格式

        Args:
            content: LLM 返回的文本内容

        Returns:
            解析后的参数 dict

        Raises:
            SQLGenerationError: 解析失败
        """
        # 正则提取 JSON 对象（与前端逻辑一致）
        match = re.search(r'\{[\s\S]*\}', content)
        if not match:
            raise SQLGenerationError(
                'content 中未找到 JSON 对象',
                raw_response=content,
            )

        json_str = match.group(0)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise SQLGenerationError(
                f'content JSON 解析失败: {e}',
                raw_response=json_str,
            )

        # 判断是 Function Calling 参数格式还是前端旧格式
        if 'sql' in data:
            # Function Calling 参数格式（含 sql 字段）
            return self._normalize_arguments(data)
        else:
            # 前端旧格式（含 dimension/metric/chartType 等）
            return self._normalize_legacy_json(data)

    def _normalize_legacy_json(self, data: dict) -> dict:
        """将前端 llmFullAnalysis 的 JSON 格式映射为标准参数格式。

        前端 JSON 字段 → 后端参数字段：
        - dimension → x_field
        - metric → y_field
        - aggregation → aggregation
        - intent → intent
        - chartType → chart_type
        - queryUnderstanding → explanation
        - filters → filters
        - sortOrder → sort_order
        - limit → limit

        注意：前端 JSON 中没有 sql 字段（前端靠 JS 拼接），
        降级解析时需要根据其他字段拼接基础 SQL。

        Args:
            data: 前端格式的 JSON dict

        Returns:
            标准参数格式 dict
        """
        chart_type = data.get('chartType', 'table')
        intent = data.get('intent', 'summary')

        # 降级模式：从 JSON 字段拼接基础 SQL
        sql = self._build_sql_from_legacy(data)

        return {
            'sql': sql,
            'chart_type': chart_type,
            'x_field': data.get('dimension') or '',
            'y_field': data.get('metric') or '',
            'aggregation': data.get('aggregation'),
            'intent': intent,
            'insight': data.get('queryUnderstanding', ''),
            'explanation': data.get('queryUnderstanding', ''),
            'filters': data.get('filters', []),
            'sort_order': data.get('sortOrder'),
            'limit': data.get('limit'),
        }

    def _build_sql_from_legacy(self, data: dict) -> str:
        """降级模式：从前端 JSON 字段拼接基础 SQL。

        当 LLM 不支持 Function Calling 时，从解析出的 JSON 字段
        拼接一个基础的 SELECT 语句。此方法仅为降级方案，
        优先使用 Function Calling 模式。

        Args:
            data: 前端格式 JSON dict

        Returns:
            SQL 字符串
        """
        dimension = data.get('dimension')
        metric = data.get('metric')
        aggregation = data.get('aggregation', 'sum')
        filters = data.get('filters', [])
        sort_order = data.get('sortOrder')
        limit = data.get('limit', 10)
        having = data.get('havingCond')

        parts_select = []
        parts_group = []
        parts_where = []
        parts_order = []

        # 维度字段
        if dimension:
            dim_field = f'"{dimension}"' if not dimension.isascii() else dimension
            parts_select.append(dim_field)
            parts_group.append(dim_field)
        else:
            parts_select.append('1')

        # 指标字段
        if metric and aggregation != 'count':
            metric_field = f'"{metric}"' if not metric.isascii() else metric
            agg_field = f'{aggregation.upper()}({metric_field})'
            parts_select.append(f'{agg_field} as {aggregation}_{metric}')
        elif aggregation == 'count':
            parts_select.append('COUNT(*) as count')

        # WHERE 条件
        for f in filters:
            field = f.get('field', '')
            op = f.get('op', '=')
            value = f.get('value', '')
            field_quoted = f'"{field}"' if not field.isascii() else field
            # 数值不加引号，字符串加引号
            try:
                float(value)
                parts_where.append(f'{field_quoted} {op} {value}')
            except (ValueError, TypeError):
                parts_where.append(f'{field_quoted} {op} \'{value}\'')

        # 组装 SQL
        sql = f"SELECT {', '.join(parts_select)} FROM data_table"
        if parts_where:
            sql += f" WHERE {' AND '.join(parts_where)}"
        if parts_group:
            sql += f" GROUP BY {', '.join(parts_group)}"
        if having:
            sql += f" HAVING {having}"
        if sort_order and sort_order != 'null':
            order_field = parts_select[-1].split(' as ')[0] if ' as ' in parts_select[-1] else parts_select[-1]
            sql += f" ORDER BY {order_field} {sort_order.upper()}"
        if limit:
            sql += f" LIMIT {limit}"

        return sql

    # ============================================================
    # 参数标准化
    # ============================================================

    def _normalize_arguments(self, arguments: dict) -> dict:
        """标准化 Function Calling 返回的参数。

        确保所有字段都有默认值，处理 None / 空字符串等情况。

        Args:
            arguments: LLM 返回的原始参数

        Returns:
            标准化后的参数 dict
        """
        return {
            'sql': arguments.get('sql', '').strip(),
            'chart_type': arguments.get('chart_type', 'table'),
            'x_field': arguments.get('x_field') or '',
            'y_field': arguments.get('y_field') or '',
            'aggregation': arguments.get('aggregation'),
            'intent': arguments.get('intent', 'summary'),
            'insight': arguments.get('insight', ''),
            'explanation': arguments.get('explanation', ''),
            'filters': arguments.get('filters', []),
            'sort_order': arguments.get('sort_order'),
            'limit': arguments.get('limit'),
        }

    # ============================================================
    # 字段校验
    # ============================================================

    def _validate_fields(self, parsed: dict) -> None:
        """校验解析结果的字段有效性。

        校验规则：
        1. sql 不为空
        2. chart_type 在允许的枚举值中
        3. aggregation（如有）在允许的枚举值中
        4. intent 在允许的枚举值中
        5. sort_order（如有）在允许的枚举值中

        无效字段会被修正为默认值，而非抛出异常（容错策略）。
        但 sql 为空会抛出异常，触发重试。

        Args:
            parsed: 解析后的结果 dict

        Raises:
            SQLGenerationError: SQL 语句为空
        """
        # sql 校验
        if not parsed['sql']:
            raise SQLGenerationError('SQL 语句为空')

        # chart_type 校验
        if parsed['chart_type'] not in self.VALID_CHART_TYPES:
            logger.warning(
                f'无效的 chart_type: {parsed["chart_type"]}, 修正为 table'
            )
            parsed['chart_type'] = 'table'

        # aggregation 校验
        if parsed['aggregation'] and parsed['aggregation'] not in self.VALID_AGGREGATIONS:
            logger.warning(
                f'无效的 aggregation: {parsed["aggregation"]}, 设为 None'
            )
            parsed['aggregation'] = None

        # intent 校验
        if parsed['intent'] not in self.VALID_INTENTS:
            logger.warning(
                f'无效的 intent: {parsed["intent"]}, 修正为 summary'
            )
            parsed['intent'] = 'summary'

        # sort_order 校验
        if parsed['sort_order'] is not None and parsed['sort_order'] not in self.VALID_SORT_ORDERS:
            logger.warning(
                f'无效的 sort_order: {parsed["sort_order"]}, 设为 None'
            )
            parsed['sort_order'] = None

        # limit 校验
        if parsed['limit'] is not None:
            try:
                parsed['limit'] = int(parsed['limit'])
                if parsed['limit'] < 0:
                    parsed['limit'] = None
            except (ValueError, TypeError):
                parsed['limit'] = None
```

### 5.2 结果解析策略

结果解析采用**三级降级策略**，确保最大兼容性：

```
LLM 返回
    │
    ▼
┌─────────────────────────┐
│ 策略1: 解析 tool_calls   │ ── 优先（Function Calling 标准返回）
│ (LLM 原生结构化参数)      │
└───────────┬─────────────┘
            │ 失败/不存在
            ▼
┌─────────────────────────┐
│ 策略2: 解析 content JSON │ ── 降级（正则提取 JSON，兼容旧模型）
│ (正则匹配 + JSON.parse)   │    对应前端 llmFullAnalysis 行4467
└───────────┬─────────────┘
            │ 失败/不存在
            ▼
┌─────────────────────────┐
│ 策略3: 抛出异常           │ ── 最终失败
│ (SQLGenerationError)     │    触发重试机制
└─────────────────────────┘
```

---

## 6. 查询处理器 (core/query_processor.py)

这是编排模块，协调缓存检查、LLM 调用、SQL 执行、洞察生成的完整流程。

### 6.1 完整的 QueryProcessor 类

创建 `core/query_processor.py`：

```python
"""
core/query_processor.py — 查询处理器

这是编排模块，协调以下组件完成一次完整的查询：
1. DataManager    — 获取数据 schema 和数据画像
2. CacheManager   — 语义缓存检查（FAISS 向量相似度）
3. SQLGenerator   — LLM 生成 SQL 查询方案
4. SQLExecutor    — SQL 安全校验和执行
5. LLMClient      — 生成深度洞察（可选）

完整流程：
    用户问题 → 缓存检查 → LLM生成SQL → SQL执行 → 洞察生成 → 写入缓存 → 返回结果

对应前端：
- analyzeQuestion(question) [行4584] → QueryProcessor.process()
- executeSQL(sql) → SQLExecutor.execute()
- llmDeepInterpretation(question, analysis, dataProfile) [行4494] → _generate_insight()
"""

import json
import logging
import time
from typing import Any, Optional

from core.data_manager import DataManager
from core.sql_executor import SQLExecutor, SQLValidationError
from core.sql_generator import SQLGenerator, SQLGenerationError
from core.prompts import SYSTEM_PROMPT_INSIGHT, build_insight_prompt
from utils.llm_client import LLMClient, LLMError
from models import get_session
from models.query_history import QueryHistory

logger = logging.getLogger(__name__)


class QueryProcessor:
    """查询处理器：编排完整查询流程。

    依赖注入：
        processor = QueryProcessor(
            cache=cache_manager,         # FAISS 语义缓存
            sql_generator=sql_generator,  # LLM SQL 生成器
            sql_executor=sql_executor,   # SQL 执行器
            data_manager=data_manager,    # 数据管理器
        )
        result = await processor.process(question, dataset_id)
    """

    # SQL 执行失败时的最大重试次数（将错误信息发回 LLM 让它修正 SQL）
    SQL_EXEC_MAX_RETRIES = 3

    def __init__(
        self,
        cache: Any,
        sql_generator: SQLGenerator,
        sql_executor: SQLExecutor,
        data_manager: DataManager,
        llm_client: Optional[LLMClient] = None,
    ):
        self.cache = cache
        self.sql_generator = sql_generator
        self.sql_executor = sql_executor
        self.data_manager = data_manager
        self.llm = llm_client  # 用于深度解读，None 时跳过

    # ============================================================
    # 主入口：处理查询
    # ============================================================

    async def process(self, question: str, dataset_id: str) -> dict:
        """完整查询处理流程。

        流程步骤：
        1. 获取数据 schema 和数据画像
        2. 检查语义缓存（FAISS 向量相似度）
        3. 缓存命中 → 直接返回缓存结果
        4. 缓存未命中 → 调用 LLM 生成 SQL
        5. 执行 SQL（安全校验 + SQLite 执行）
        6. SQL 执行失败 → 将错误信息发回 LLM 修正 SQL（最多重试 3 次）
        7. 生成深度洞察（LLM，可选）
        8. 写入语义缓存
        9. 保存查询历史
        10. 返回完整结果

        Args:
            question: 用户自然语言问题
            dataset_id: 数据集 ID

        Returns:
            dict: {
                'sql': str,                    # SQL 查询语句
                'result': dict,                # 查询结果 {columns, rows, count}
                'chart_config': dict,          # 图表配置
                'insight': str,                # 深度洞察文本
                'explanation': str,            # 问题理解说明
                'cached': bool,                # 是否命中缓存
                'response_time_ms': int,        # 响应时间（毫秒）
            }

        Raises:
            ValueError: 数据集不存在
            SQLGenerationError: SQL 生成失败
        """
        start_time = time.time()

        # 1. 获取数据 schema 和数据画像
        logger.info(
            f'[QueryProcessor] 开始处理: question="{question}", dataset_id={dataset_id}'
        )

        schema = self.data_manager.get_schema(dataset_id)
        data_profile = self.data_manager.build_data_profile(dataset_id)
        db_path = self._get_db_path(dataset_id)

        # 2. 检查语义缓存
        cached_result = None
        if self.cache:
            try:
                cached_result = self.cache.search(question, dataset_id)
                if cached_result:
                    logger.info(
                        f'[QueryProcessor] 缓存命中, '
                        f'similarity={cached_result.get("similarity_score", 0):.4f}'
                    )
            except Exception as e:
                logger.warning(f'[QueryProcessor] 缓存查询失败: {e}')

        # 3. 缓存命中 → 直接返回
        if cached_result:
            elapsed_ms = int((time.time() - start_time) * 1000)
            result = {
                'sql': cached_result.get('sql_text', ''),
                'result': (
                    json.loads(cached_result['result_json'])
                    if cached_result.get('result_json')
                    else None
                ),
                'chart_config': (
                    json.loads(cached_result['chart_config_json'])
                    if cached_result.get('chart_config_json')
                    else None
                ),
                'insight': cached_result.get('insight', ''),
                'explanation': cached_result.get('explanation', ''),
                'cached': True,
                'response_time_ms': elapsed_ms,
            }
            # 保存查询历史（缓存命中也记录）
            self._save_history(dataset_id, question, result, cached=True, elapsed_ms=elapsed_ms)
            logger.info(f'[QueryProcessor] 缓存命中, 耗时={elapsed_ms}ms')
            return result

        # 4. 缓存未命中 → 调用 LLM 生成 SQL
        logger.info('[QueryProcessor] 缓存未命中, 调用 LLM 生成 SQL')
        try:
            generated = await self.sql_generator.generate(
                question=question,
                schema_info=data_profile,
            )
        except SQLGenerationError as e:
            logger.error(f'[QueryProcessor] SQL 生成失败: {e}')
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                'sql': '',
                'result': None,
                'chart_config': None,
                'insight': '抱歉，无法理解您的问题。请尝试更具体的表述。',
                'explanation': str(e),
                'cached': False,
                'response_time_ms': elapsed_ms,
                'error': str(e),
            }

        sql = generated['sql']
        chart_config = {
            'type': generated['chart_type'],
            'x_field': generated['x_field'],
            'y_field': generated['y_field'],
            'aggregation': generated['aggregation'],
            'intent': generated['intent'],
        }

        # 5. 执行 SQL（带错误重试：将错误信息发回 LLM 修正 SQL）
        query_result = None
        sql_error = None
        current_sql = sql
        current_generated = generated

        for exec_attempt in range(1, self.SQL_EXEC_MAX_RETRIES + 1):
            try:
                logger.info(
                    f'[QueryProcessor] 执行 SQL (第{exec_attempt}次): {current_sql[:100]}'
                )
                query_result = self.sql_executor.execute(current_sql, db_path)
                sql_error = None
                break  # 执行成功，跳出重试循环

            except SQLValidationError as e:
                sql_error = f'SQL 安全校验失败: {str(e)}'
                logger.warning(f'[QueryProcessor] {sql_error}')

            except Exception as e:
                sql_error = f'SQL 执行错误: {str(e)}'
                logger.warning(f'[QueryProcessor] {sql_error}')

            # SQL 执行失败，将错误信息发回 LLM 让它修正 SQL
            if exec_attempt < self.SQL_EXEC_MAX_RETRIES:
                logger.info(
                    f'[QueryProcessor] SQL 执行失败, '
                    f'将错误信息发回 LLM 修正 (第{exec_attempt}次重试)'
                )
                try:
                    # 构建修正提示，包含原始 SQL 和错误信息
                    error_context = (
                        f'⚠️ 上次生成的 SQL 执行失败，请修正：\n'
                        f'原 SQL：{current_sql}\n'
                        f'错误信息：{sql_error}\n'
                        f'请重新调用 execute_data_query 函数，确保 SQL 语法正确。'
                    )
                    retry_response = await self.llm.generate_sql(
                        question=question,
                        schema_info=data_profile,
                        tools=self._get_tools(),
                        system_prompt=SYSTEM_PROMPT_SQL_FULL,
                        tool_choice='auto',
                        extra_context=error_context,
                    )
                    current_generated = self.sql_generator._parse_llm_response(retry_response)
                    self.sql_generator._validate_fields(current_generated)
                    current_sql = current_generated['sql']
                    # 更新 chart_config
                    chart_config = {
                        'type': current_generated['chart_type'],
                        'x_field': current_generated['x_field'],
                        'y_field': current_generated['y_field'],
                        'aggregation': current_generated['aggregation'],
                        'intent': current_generated['intent'],
                    }
                except Exception as retry_err:
                    logger.error(f'[QueryProcessor] LLM 修正 SQL 失败: {retry_err}')
                    break

        # SQL 执行最终失败
        if query_result is None:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = sql_error or 'SQL 执行失败'
            return {
                'sql': current_sql,
                'result': None,
                'chart_config': chart_config,
                'insight': f'查询执行失败: {error_msg}',
                'explanation': current_generated.get('explanation', ''),
                'cached': False,
                'response_time_ms': elapsed_ms,
                'error': error_msg,
            }

        # 6. 生成深度洞察（可选）
        insight = current_generated.get('insight', '')
        if self.llm:
            try:
                deep_insight = await self._generate_insight(
                    question, data_profile, query_result,
                )
                if deep_insight:
                    insight = deep_insight
            except Exception as e:
                logger.warning(
                    f'[QueryProcessor] 深度洞察生成失败, 使用 LLM 预生成洞察: {e}'
                )

        # 7. 写入语义缓存
        if self.cache:
            try:
                self.cache.add(
                    question=question,
                    dataset_id=dataset_id,
                    sql_text=current_sql,
                    result_json=json.dumps(query_result, ensure_ascii=False),
                    chart_config_json=json.dumps(chart_config, ensure_ascii=False),
                    insight=insight,
                )
                logger.info('[QueryProcessor] 已写入缓存')
            except Exception as e:
                logger.warning(f'[QueryProcessor] 写入缓存失败: {e}')

        # 8. 组装最终结果
        elapsed_ms = int((time.time() - start_time) * 1000)
        result = {
            'sql': current_sql,
            'result': query_result,
            'chart_config': chart_config,
            'insight': insight,
            'explanation': current_generated.get('explanation', ''),
            'cached': False,
            'response_time_ms': elapsed_ms,
        }

        # 9. 保存查询历史
        self._save_history(dataset_id, question, result, cached=False, elapsed_ms=elapsed_ms)

        logger.info(
            f'[QueryProcessor] 处理完成, 耗时={elapsed_ms}ms, '
            f'rows={query_result.get("count", 0)}'
        )
        return result

    # ============================================================
    # 深度洞察生成
    # ============================================================

    async def _generate_insight(
        self,
        question: str,
        data_profile: str,
        query_result: dict,
    ) -> Optional[str]:
        """生成深度洞察文本。

        对应前端 llmDeepInterpretation(question, analysis, dataProfile) [行4494]。
        将查询结果和上下文喂给 LLM，生成 2-4 句话的深度解读。

        防幻觉策略：
        - 只提供实际查询结果，不提供推测数据
        - System Prompt 明确要求"严禁编造结果中不存在的数据"
        - 限制字数（150字），减少 LLM 发挥空间

        Args:
            question: 用户原始问题
            data_profile: 数据画像文本
            query_result: 查询结果 {columns, rows, count}

        Returns:
            深度洞察文本，或 None（LLM 不可用时）
        """
        # 截取数据画像摘要（前15行，与前端一致）
        profile_lines = data_profile.split('\n')
        data_profile_summary = '\n'.join(profile_lines[:15])

        # 构建洞察 Prompt
        prompt = build_insight_prompt(question, data_profile_summary, query_result)

        try:
            response = await self.llm.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT_INSIGHT,
                temperature=0.3,
                max_tokens=400,
            )
            content = response.get('content', '')
            return content.strip() if content else None
        except LLMError as e:
            logger.warning(f'[QueryProcessor] LLM 洞察生成失败: {e}')
            return None

    # ============================================================
    # 辅助方法
    # ============================================================

    def _get_tools(self) -> list[dict]:
        """获取 Function Calling 工具列表。"""
        from core.tools import AVAILABLE_TOOLS
        return AVAILABLE_TOOLS

    def _get_db_path(self, dataset_id: str) -> str:
        """获取数据集对应的 SQLite 文件路径。

        Args:
            dataset_id: 数据集 ID

        Returns:
            SQLite 文件路径

        Raises:
            ValueError: 数据集不存在
        """
        from models.dataset import Dataset
        session = get_session()
        try:
            dataset = session.query(Dataset).filter_by(id=dataset_id).first()
            if not dataset:
                raise ValueError(f'数据集不存在: {dataset_id}')
            return dataset.db_path
        finally:
            session.close()

    def _save_history(
        self,
        dataset_id: str,
        question: str,
        result: dict,
        cached: bool,
        elapsed_ms: int,
    ) -> None:
        """保存查询历史到数据库。

        Args:
            dataset_id: 数据集 ID
            question: 用户问题
            result: 查询结果 dict
            cached: 是否命中缓存
            elapsed_ms: 响应时间（毫秒）
        """
        session = get_session()
        try:
            history = QueryHistory(
                dataset_id=dataset_id,
                question=question,
                sql_text=result.get('sql', ''),
                result_json=(
                    json.dumps(result.get('result'), ensure_ascii=False)
                    if result.get('result')
                    else None
                ),
                chart_config_json=(
                    json.dumps(result.get('chart_config'), ensure_ascii=False)
                    if result.get('chart_config')
                    else None
                ),
                insight=result.get('insight', ''),
                cached=cached,
                response_time_ms=elapsed_ms,
            )
            session.add(history)
            session.commit()
            logger.info(f'[QueryProcessor] 查询历史已保存, id={history.id}')
        except Exception as e:
            session.rollback()
            logger.warning(f'[QueryProcessor] 保存查询历史失败: {e}')
        finally:
            session.close()


# ============================================================
# 导入 SYSTEM_PROMPT_SQL（用于 SQL 修正重试）
# ============================================================

from core.prompts import SYSTEM_PROMPT_SQL as SYSTEM_PROMPT_SQL_FULL


# ============================================================
# 模块级单例
# ============================================================

_query_processor: Optional[QueryProcessor] = None


def get_query_processor() -> QueryProcessor:
    """获取全局 QueryProcessor 实例（延迟初始化）。

    首次调用时初始化所有依赖组件：
    - DataManager
    - SQLExecutor
    - LLMClient
    - SQLGenerator
    - CacheManager（如果可用）
    """
    global _query_processor
    if _query_processor is None:
        from core.data_manager import data_manager
        from core.sql_executor import sql_executor
        from utils.llm_client import llm_client

        sql_generator = SQLGenerator(llm_client)

        # 尝试导入缓存管理器（04 文档实现）
        cache = None
        try:
            from core.cache_manager import cache_manager
            cache = cache_manager
        except ImportError:
            logger.info('[QueryProcessor] 缓存管理器未加载, 跳过缓存')

        _query_processor = QueryProcessor(
            cache=cache,
            sql_generator=sql_generator,
            sql_executor=sql_executor,
            data_manager=data_manager,
            llm_client=llm_client,
        )

    return _query_processor
```

### 6.2 响应格式

查询成功时的响应：

```json
{
  "sql": "SELECT \"部门\", COUNT(*) as count FROM data_table GROUP BY \"部门\" ORDER BY count DESC",
  "result": {
    "columns": ["部门", "count"],
    "rows": [
      {"部门": "研发部", "count": 45},
      {"部门": "销售部", "count": 35},
      {"部门": "市场部", "count": 28},
      {"部门": "财务部", "count": 15},
      {"部门": "人事部", "count": 12}
    ],
    "count": 5
  },
  "chart_config": {
    "type": "bar",
    "x_field": "部门",
    "y_field": "count",
    "aggregation": "count",
    "intent": "ranking"
  },
  "insight": "研发部人数最多（45人），占比约31%。人事部人数最少（12人），仅为研发部的四分之一。各部门人数分布不均，研发团队规模显著高于其他部门。",
  "explanation": "您想了解各部门的员工数量分布",
  "cached": false,
  "response_time_ms": 2340
}
```

缓存命中时的响应（`response_time_ms` 通常 < 50ms）：

```json
{
  "sql": "SELECT \"部门\", COUNT(*) as count FROM data_table GROUP BY \"部门\" ORDER BY count DESC",
  "result": {"columns": [...], "rows": [...], "count": 5},
  "chart_config": {"type": "bar", ...},
  "insight": "研发部人数最多...",
  "explanation": "您想了解各部门的员工数量分布",
  "cached": true,
  "response_time_ms": 15
}
```

SQL 执行失败（重试耗尽）时的响应：

```json
{
  "sql": "SELECT \"部门\" COUNT(*) FROM data_table GROUP BY \"部门\"",
  "result": null,
  "chart_config": {"type": "bar", ...},
  "insight": "查询执行失败: SQL 执行错误: near \"COUNT\": syntax error",
  "explanation": "您想了解各部门的员工数量分布",
  "cached": false,
  "response_time_ms": 8500,
  "error": "SQL 执行错误: near \"COUNT\": syntax error"
}
```

---

## 7. 查询 API 路由 (routes/query.py)

创建 `routes/query.py`：

```python
"""
routes/query.py — 查询路由

处理用户的自然语言查询请求，调用 QueryProcessor 完成完整的查询流程。

对应前端：
- 用户输入问题 → POST /api/query
- 前端 analyzeQuestion() [行4584] 的后端实现

请求格式：
    POST /api/query
    Content-Type: application/json
    {
        "question": "各部门的平均薪资是多少",
        "dataset_id": "ds-1234567890-abc"
    }

响应格式：
    {
        "success": true,
        "data": {
            "sql": "SELECT ...",
            "result": {"columns": [...], "rows": [...], "count": 10},
            "chart_config": {"type": "bar", ...},
            "insight": "研发部人数最多...",
            "explanation": "您想了解各部门的员工数量分布",
            "cached": false,
            "response_time_ms": 2340
        }
    }
"""

import logging
import asyncio

from flask import Blueprint, request, jsonify

from core.query_processor import get_query_processor

logger = logging.getLogger(__name__)

bp = Blueprint('query', __name__)


@bp.route('/api/query', methods=['POST'])
def query():
    """处理自然语言查询。

    请求体：
        {
            "question": "用户问题",
            "dataset_id": "数据集ID"
        }

    响应：
        成功: {"success": true, "data": {...}}
        失败: {"success": false, "error": "错误信息"}
    """
    data = request.get_json()

    # 参数校验
    if not data:
        return jsonify({'success': False, 'error': '请求体为空'}), 400

    question = data.get('question', '').strip()
    dataset_id = data.get('dataset_id', '').strip()

    if not question:
        return jsonify({'success': False, 'error': '问题不能为空'}), 400

    if not dataset_id:
        return jsonify({'success': False, 'error': '数据集ID不能为空'}), 400

    # 问题长度限制
    if len(question) > 500:
        return jsonify({'success': False, 'error': '问题过长，请限制在500字以内'}), 400

    logger.info(
        f'[API] 查询请求: question="{question[:80]}", dataset_id={dataset_id}'
    )

    try:
        # 获取 QueryProcessor 实例
        processor = get_query_processor()

        # 执行查询处理（异步调用，在 Flask 同步路由中通过 asyncio 运行）
        result = asyncio.run(
            processor.process(question=question, dataset_id=dataset_id)
        )

        logger.info(
            f'[API] 查询完成: cached={result.get("cached")}, '
            f'rows={result.get("result", {}).get("count", 0) if result.get("result") else 0}, '
            f'time={result.get("response_time_ms")}ms'
        )

        return jsonify({'success': True, 'data': result}), 200

    except ValueError as e:
        # 数据集不存在等业务错误
        logger.warning(f'[API] 查询失败(业务错误): {e}')
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        # 未知异常
        logger.error(f'[API] 查询失败(内部错误): {e}', exc_info=True)
        return jsonify({'success': False, 'error': f'内部错误: {str(e)}'}), 500


@bp.route('/api/query/async', methods=['POST'])
async def query_async():
    """异步查询接口（适用于 ASGI 服务器如 Hypercorn）。

    与 /api/query 功能相同，但使用 async/await 原生异步处理。
    需配合 ASGI 服务器使用：
        hypercorn app:app --worker-class asyncio

    请求格式同 /api/query。
    """
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': '请求体为空'}), 400

    question = data.get('question', '').strip()
    dataset_id = data.get('dataset_id', '').strip()

    if not question:
        return jsonify({'success': False, 'error': '问题不能为空'}), 400

    if not dataset_id:
        return jsonify({'success': False, 'error': '数据集ID不能为空'}), 400

    if len(question) > 500:
        return jsonify({'success': False, 'error': '问题过长，请限制在500字以内'}), 400

    logger.info(
        f'[API] 异步查询请求: question="{question[:80]}", dataset_id={dataset_id}'
    )

    try:
        processor = get_query_processor()
        result = await processor.process(question=question, dataset_id=dataset_id)

        logger.info(
            f'[API] 异步查询完成: cached={result.get("cached")}, '
            f'rows={result.get("result", {}).get("count", 0) if result.get("result") else 0}, '
            f'time={result.get("response_time_ms")}ms'
        )

        return jsonify({'success': True, 'data': result}), 200

    except ValueError as e:
        logger.warning(f'[API] 异步查询失败(业务错误): {e}')
        return jsonify({'success': False, 'error': str(e)}), 404

    except Exception as e:
        logger.error(f'[API] 异步查询失败(内部错误): {e}', exc_info=True)
        return jsonify({'success': False, 'error': f'内部错误: {str(e)}'}), 500
```

### 7.1 路由注册

在 `app.py` 的 `create_app()` 中注册查询路由蓝图：

```python
# 在 app.py 的 create_app() 函数中，已有的蓝图注册之后添加：

    from routes.query import bp as query_bp
    app.register_blueprint(query_bp)
```

### 7.2 前端调用示例

前端 `index.html` 中将查询请求发送到后端 API（替代原有的前端全流程分析）：

```javascript
// 前端调用后端 /api/query 接口
async function queryViaBackend(question, datasetId) {
    var resp = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question, dataset_id: datasetId })
    });
    var result = await resp.json();
    if (!result.success) {
        console.error('查询失败:', result.error);
        return null;
    }
    // result.data 包含 sql, result, chart_config, insight, explanation, cached, response_time_ms
    return result.data;
}

// 使用示例
var data = await queryViaBackend('各部门的平均薪资是多少', currentDatasetId);
if (data) {
    // 渲染图表
    renderChart(data.chart_config, data.result);
    // 显示洞察
    showInsight(data.insight);
    // 显示 SQL
    showSQL(data.sql);
}
```

---

## 8. 错误处理与重试

### 8.1 错误处理总览

| 错误类型 | 触发条件 | 处理方式 | 重试位置 | 最大重试 |
|---------|---------|---------|---------|---------|
| LLM 超时 | `httpx.TimeoutException` | 指数退避重试 | `LLMClient._request_with_retry()` | 3 次 |
| LLM 连接失败 | `httpx.ConnectError` | 指数退避重试 | `LLMClient._request_with_retry()` | 3 次 |
| LLM 限流 | HTTP 429 | 指数退避重试 | `LLMClient._request_with_retry()` | 3 次 |
| LLM 服务器错误 | HTTP 500/502/503 | 指数退避重试 | `LLMClient._request_with_retry()` | 3 次 |
| LLM API Key 无效 | HTTP 401 | 不重试，直接抛出 | — | 0 次 |
| LLM 请求格式错误 | HTTP 400 | 不重试，直接抛出 | — | 0 次 |
| Function Calling 解析失败 | tool_calls 和 content 均无效 | 抛出 `SQLGenerationError` | `SQLGenerator.generate()` | 3 次 |
| SQL 安全校验失败 | `SQLValidationError` | 附带错误信息重新调用 LLM | `SQLGenerator.generate()` | 3 次 |
| **SQL 执行错误** | `sqlite3.Error`（语法错误等） | **将错误信息发回 LLM 让它修正 SQL** | `QueryProcessor.process()` | 3 次 |
| 字段校验失败 | 无效的 chart_type/aggregation 等 | 修正为默认值 | — | 不重试 |
| API Key 未配置 | `LLM_CONFIG['api_key']` 为空 | 抛出 `LLMError` | — | 不重试 |

### 8.2 LLM 超时处理

`LLMClient._request_with_retry()` 内部实现指数退避重试：

```
第 1 次请求 → 超时
    │ 等待 1 秒
    ▼
第 2 次请求 → 超时
    │ 等待 2 秒
    ▼
第 3 次请求 → 超时
    │
    ▼
抛出 LLMError("LLM 请求失败：超过最大重试次数")
```

### 8.3 SQL 语法错误时将错误信息发回 LLM 修正

这是本模块的核心容错机制。当 SQL 执行失败（如语法错误、字段不存在等），`QueryProcessor` 不会直接返回错误，而是将错误信息拼接到 Prompt 中，重新调用 LLM 让它修正 SQL：

```
第 1 次执行 SQL → 失败（语法错误: near "COUNT": syntax error）
    │
    │ 构建 error_context:
    │   "⚠️ 上次生成的 SQL 执行失败，请修正：
    │    原 SQL：SELECT "部门" COUNT(*) FROM data_table GROUP BY "部门"
    │    错误信息：near "COUNT": syntax error
    │    请重新调用 execute_data_query 函数，确保 SQL 语法正确。"
    │
    ▼
LLM 修正 SQL → "SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门""
    │
    ▼
第 2 次执行 SQL → 成功
```

最大重试 3 次。如果 3 次都失败，返回包含错误信息的友好响应给前端。

### 8.4 重试流程图

```
                    QueryProcessor.process()
                            │
                    ┌───────▼────────┐
                    │ 1. 缓存检查     │
                    └───────┬────────┘
                            │
               命中 ─────────┼───────── 未命中
                    │                   │
                    ▼                   ▼
              直接返回        ┌──────────────────┐
                              │ 2. LLM 生成 SQL  │
                              │ (SQLGenerator)   │
                              └───────┬──────────┘
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
                成功            LLM 失败            解析失败
                    │                 │                  │
                    │                 ▼                  ▼
                    │          重试(最多3次)        重试(最多3次)
                    │            ┌────────┐          ┌────────┐
                    │            │附带错误 │          │降级解析 │
                    │            │重新调用 │          │或重试  │
                    │            └───┬────┘          └───┬────┘
                    │                │                   │
                    │          成功 ──┘  失败 ──┐  成功 ──┘  失败 ──┐
                    │              │            │       │            │
                    │              │            ▼       │            ▼
                    │              │      返回错误响应  │      返回错误响应
                    │              │                    │
                    ▼              ▼                    ▼
            ┌────────────────────────────────────────────────┐
            │ 3. 执行 SQL (SQLExecutor)                      │
            └───────────────────────┬────────────────────────┘
                                    │
                       成功 ────────┼──────── 失败
                         │                        │
                         │                        ▼
                         │              ┌──────────────────────┐
                         │              │ 4. 错误回传 LLM 修正  │
                         │              │ (最多3次)             │
                         │              └──────────┬───────────┘
                         │                         │
                         │               成功 ─────┼──── 失败
                         │                 │              │
                         │                 │              ▼
                         │                 │        返回错误响应
                         ▼                 ▼
                    ┌────────────────────────────┐
                    │ 5. 生成洞察 → 写入缓存      │
                    │    → 保存历史 → 返回结果    │
                    └────────────────────────────┘
```

### 8.5 返回友好错误信息给前端

所有错误路径都会返回结构化的 JSON 响应，前端可以据此显示友好的错误提示：

| 场景 | HTTP 状态码 | 响应示例 |
|------|-----------|---------|
| 参数缺失 | 400 | `{"success": false, "error": "问题不能为空"}` |
| 数据集不存在 | 404 | `{"success": false, "error": "数据集不存在: ds-xxx"}` |
| LLM 生成失败 | 200 | `{"success": true, "data": {"sql": "", "error": "SQL 生成失败", ...}}` |
| SQL 执行失败 | 200 | `{"success": true, "data": {"sql": "...", "error": "near \"COUNT\": syntax error", ...}}` |
| 内部异常 | 500 | `{"success": false, "error": "内部错误: ..."}` |

> **注意**：LLM 生成失败和 SQL 执行失败时 HTTP 状态码为 200，因为请求本身处理成功，只是查询结果为空。前端通过 `data.error` 字段判断是否有错误。

---

## 9. 测试用例

### 9.1 测试场景概览

| # | 测试场景 | 输入问题 | 期望 SQL | 期望 chart_type | 期望 intent |
|---|---------|---------|---------|----------------|------------|
| 1 | 简单汇总查询 | "总销售额是多少" | `SELECT SUM("销售额") as total FROM data_table` | `number` | `summary` |
| 2 | 分组查询 | "各部门的员工数量" | `SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC` | `bar` | `ranking` |
| 3 | 趋势查询 | "销售额的月度趋势" | `SELECT strftime('%Y-%m', "上架日期") as month, SUM("销售额") as total FROM data_table GROUP BY month ORDER BY month` | `line` | `trend` |
| 4 | 筛选查询 | "销售额超过10000的门店" | `SELECT "门店名称", "销售额" FROM data_table WHERE "销售额" > 10000 ORDER BY "销售额" DESC` | `table` | `filter` |
| 5 | 占比查询 | "各城市的销售额占比" | `SELECT "城市", SUM("销售额") as total FROM data_table GROUP BY "城市" ORDER BY total DESC` | `pie` | `distribution` |

### 9.2 单元测试

创建 `tests/test_sql_generator.py`：

```python
"""
tests/test_sql_generator.py — SQL 生成器单元测试

测试场景：
1. 简单汇总查询："总销售额是多少"
2. 分组查询："各部门的员工数量"
3. 趋势查询："销售额的月度趋势"
4. 筛选查询："销售额超过10000的门店"
5. 占比查询："各城市的销售额占比"

运行方式：
    cd e:\\数分精灵demo minmax\\最新版-数分ai
    python -m pytest tests/test_sql_generator.py -v
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from core.sql_generator import SQLGenerator, SQLGenerationError
from core.tools import QUERY_ANALYSIS_FUNCTION, AVAILABLE_TOOLS


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def mock_llm_client():
    """创建 Mock LLM 客户端（异步 Mock）。"""
    client = Mock()
    client.generate = AsyncMock()
    client.generate_sql = AsyncMock()
    return client


@pytest.fixture
def sql_generator(mock_llm_client):
    """创建 SQLGenerator 实例（使用 Mock LLM）。"""
    return SQLGenerator(mock_llm_client)


@pytest.fixture
def sales_schema():
    """销售数据画像（用于测试）。"""
    return """【数据概况】
文件名: sales_data.csv
总行数: 5000
字段数: 6

【字段详情】
─ 门店名称 (text)
  取值(50个), Top10: 北京旗舰店(320), 上海中心店(280), 广州天河店(250), 深圳南山店(230), 成都春熙店(200)
─ 城市 (text)
  取值(15个): 北京(980), 上海(850), 广州(620), 深圳(580), 成都(420), 杭州(380), 武汉(320)
─ 销售额 (currency)
  统计: 总和=12856000.00, 平均=2571.20, 最大=45000.00, 最小=120.00
─ 上架日期 (date)
  范围: 2024-01-01 ~ 2024-12-31
─ 分类 (text)
  取值(5个): 电子产品(1500), 服装(1200), 食品(800), 家居(900), 其他(600)
─ 库存数量 (int)
  统计: 总和=580000, 平均=116, 最大=2000, 最小=0

【样本数据(前5行)】
行1: 门店名称=北京旗舰店, 城市=北京, 销售额=35000, 上架日期=2024-01-15, 分类=电子产品, 库存数量=500
行2: 门店名称=上海中心店, 城市=上海, 销售额=28000, 上架日期=2024-02-20, 分类=服装, 库存数量=380
行3: 门店名称=广州天河店, 城市=广州, 销售额=22000, 上架日期=2024-03-10, 分类=食品, 库存数量=250
行4: 门店名称=深圳南山店, 城市=深圳, 销售额=18000, 上架日期=2024-04-05, 分类=家居, 库存数量=200
行5: 门店名称=成都春熙店, 城市=成都, 销售额=15000, 上架日期=2024-05-18, 分类=电子产品, 库存数量=180"""


def make_tool_call_response(arguments: dict) -> dict:
    """构造 Function Calling 响应。"""
    return {
        'tool_calls': [
            {
                'id': 'call_test_001',
                'type': 'function',
                'function': {
                    'name': 'execute_data_query',
                    'arguments': json.dumps(arguments, ensure_ascii=False),
                },
            }
        ],
        'content': None,
    }


def make_content_response(json_obj: dict) -> dict:
    """构造降级文本响应（模拟不支持 Function Calling 的模型）。"""
    return {
        'tool_calls': None,
        'content': json.dumps(json_obj, ensure_ascii=False),
    }


# ============================================================
# 测试用例 1：简单汇总查询 — "总销售额是多少"
# ============================================================

class TestSimpleAggregation:
    """测试简单汇总查询场景。

    验证规则：
    - 规则6：字段名使用原始列名
    - 规则14：整体汇总时 chart_type 为 number
    """

    @pytest.mark.asyncio
    async def test_total_sales(self, sql_generator, mock_llm_client, sales_schema):
        """测试：总销售额是多少 → SUM 聚合 + number 图表 + summary 意图。"""
        # 设置 Mock 返回
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': 'SELECT SUM("销售额") as total FROM data_table',
            'chart_type': 'number',
            'x_field': '',
            'y_field': 'total',
            'aggregation': 'sum',
            'intent': 'summary',
            'insight': '总销售额为12856000元',
            'explanation': '您想了解总销售额',
            'filters': [],
            'sort_order': None,
            'limit': None,
        })

        # 执行
        result = await sql_generator.generate(
            question='总销售额是多少',
            schema_info=sales_schema,
        )

        # 验证 SQL
        assert 'SUM' in result['sql']
        assert '"销售额"' in result['sql']
        assert 'data_table' in result['sql']

        # 验证图表配置
        assert result['chart_type'] == 'number'
        assert result['intent'] == 'summary'
        assert result['aggregation'] == 'sum'

        # 验证 LLM 被调用
        mock_llm_client.generate_sql.assert_called_once()
        call_kwargs = mock_llm_client.generate_sql.call_args.kwargs
        assert call_kwargs['question'] == '总销售额是多少'
        assert call_kwargs['tools'] is not None


# ============================================================
# 测试用例 2：分组查询 — "各部门的员工数量"
# ============================================================

class TestGroupByQuery:
    """测试分组查询场景。

    验证规则：
    - 规则7："各XX" → dimension 为对应列
    - 规则14："人数/条数" → aggregation 为 count，metric 为 null
    - 规则9："排名" → sort_order 为 desc，intent 为 ranking
    """

    @pytest.mark.asyncio
    async def test_department_employee_count(self, sql_generator, mock_llm_client):
        """测试：各部门的员工数量 → COUNT 聚合 + bar 图表 + ranking 意图。"""
        employee_schema = """【数据概况】
文件名: employees.csv
总行数: 135
字段数: 4

【字段详情】
─ 姓名 (text)
  取值(135个)
─ 部门 (text)
  取值(5个): 研发部(45), 市场部(28), 销售部(35), 人事部(12), 财务部(15)
─ 薪资 (currency)
  统计: 总和=2856000.00, 平均=21155.56, 最大=50000.00, 最小=8000.00
─ 入职日期 (date)
  范围: 2018-01-01 ~ 2024-12-01

【样本数据(前5行)】
行1: 姓名=张三, 部门=研发部, 薪资=25000, 入职日期=2020-03-15
行2: 姓名=李四, 部门=市场部, 薪资=30000, 入职日期=2019-06-20
行3: 姓名=王五, 部门=销售部, 薪资=20000, 入职日期=2021-01-10"""

        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': 'SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC',
            'chart_type': 'bar',
            'x_field': '部门',
            'y_field': 'count',
            'aggregation': 'count',
            'intent': 'ranking',
            'insight': '研发部人数最多，共45人',
            'explanation': '您想了解各部门的员工数量分布',
            'filters': [],
            'sort_order': 'desc',
            'limit': None,
        })

        result = await sql_generator.generate(
            question='各部门的员工数量',
            schema_info=employee_schema,
        )

        # 验证 SQL
        assert 'COUNT' in result['sql']
        assert '"部门"' in result['sql']
        assert 'GROUP BY' in result['sql']
        assert 'ORDER BY count DESC' in result['sql']

        # 验证图表配置
        assert result['chart_type'] == 'bar'
        assert result['intent'] == 'ranking'
        assert result['aggregation'] == 'count'
        assert result['x_field'] == '部门'
        assert result['sort_order'] == 'desc'


# ============================================================
# 测试用例 3：趋势查询 — "销售额的月度趋势"
# ============================================================

class TestTrendQuery:
    """测试趋势查询场景。

    验证规则：
    - 规则8："趋势" → dimension 必须为日期列，chart_type 为 line，intent 为 trend
    - 规则3：日期字段支持 SQLite 日期函数（strftime）
    """

    @pytest.mark.asyncio
    async def test_monthly_sales_trend(self, sql_generator, mock_llm_client, sales_schema):
        """测试：销售额的月度趋势 → 日期维度 + line 图表 + trend 意图。"""
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': (
                "SELECT strftime('%Y-%m', \"上架日期\") as month, "
                'SUM("销售额") as total_sales '
                'FROM data_table GROUP BY month ORDER BY month'
            ),
            'chart_type': 'line',
            'x_field': 'month',
            'y_field': 'total_sales',
            'aggregation': 'sum',
            'intent': 'trend',
            'insight': '销售额整体呈上升趋势，12月达到峰值',
            'explanation': '您想了解销售额的月度变化趋势',
            'filters': [],
            'sort_order': 'asc',
            'limit': None,
        })

        result = await sql_generator.generate(
            question='销售额的月度趋势',
            schema_info=sales_schema,
        )

        # 验证 SQL
        assert 'strftime' in result['sql']
        assert 'SUM' in result['sql']
        assert 'GROUP BY' in result['sql']
        assert 'ORDER BY' in result['sql']

        # 验证图表配置（规则8：趋势 → line + trend）
        assert result['chart_type'] == 'line'
        assert result['intent'] == 'trend'
        assert result['aggregation'] == 'sum'


# ============================================================
# 测试用例 4：筛选查询 — "销售额超过10000的门店"
# ============================================================

class TestFilterQuery:
    """测试筛选查询场景。

    验证规则：
    - 规则12："XX为YY的记录" → filters 中添加条件，intent 为 filter
    """

    @pytest.mark.asyncio
    async def test_sales_filter(self, sql_generator, mock_llm_client, sales_schema):
        """测试：销售额超过10000的门店 → WHERE 筛选 + table 图表 + filter 意图。"""
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': (
                'SELECT "门店名称", "销售额" FROM data_table '
                'WHERE "销售额" > 10000 ORDER BY "销售额" DESC'
            ),
            'chart_type': 'table',
            'x_field': '门店名称',
            'y_field': '销售额',
            'aggregation': None,
            'intent': 'filter',
            'insight': '共有N家门店销售额超过10000元',
            'explanation': '您想查看销售额超过10000的门店列表',
            'filters': [{'field': '销售额', 'op': '>', 'value': 10000}],
            'sort_order': 'desc',
            'limit': None,
        })

        result = await sql_generator.generate(
            question='销售额超过10000的门店',
            schema_info=sales_schema,
        )

        # 验证 SQL
        assert 'WHERE' in result['sql']
        assert '"销售额" > 10000' in result['sql']
        assert 'ORDER BY' in result['sql']

        # 验证图表配置（规则12：筛选 → table + filter）
        assert result['chart_type'] == 'table'
        assert result['intent'] == 'filter'

        # 验证 filters
        assert len(result['filters']) == 1
        assert result['filters'][0]['field'] == '销售额'
        assert result['filters'][0]['op'] == '>'
        assert result['filters'][0]['value'] == 10000


# ============================================================
# 测试用例 5：占比查询 — "各城市的销售额占比"
# ============================================================

class TestRatioQuery:
    """测试占比查询场景。

    验证规则：
    - 规则10："占比/分布/比例" → aggregation 为 ratio 或 count，chart_type 为 pie
    - 规则7："各XX" → dimension 为对应列
    """

    @pytest.mark.asyncio
    async def test_city_sales_ratio(self, sql_generator, mock_llm_client, sales_schema):
        """测试：各城市的销售额占比 → GROUP BY 城市 + pie 图表 + distribution 意图。"""
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': (
                'SELECT "城市", SUM("销售额") as total FROM data_table '
                'GROUP BY "城市" ORDER BY total DESC'
            ),
            'chart_type': 'pie',
            'x_field': '城市',
            'y_field': 'total',
            'aggregation': 'sum',
            'intent': 'distribution',
            'insight': '北京销售额占比最高，约30%',
            'explanation': '您想了解各城市的销售额占比分布',
            'filters': [],
            'sort_order': 'desc',
            'limit': None,
        })

        result = await sql_generator.generate(
            question='各城市的销售额占比',
            schema_info=sales_schema,
        )

        # 验证 SQL
        assert '"城市"' in result['sql']
        assert 'SUM' in result['sql']
        assert 'GROUP BY' in result['sql']
        assert 'ORDER BY total DESC' in result['sql']

        # 验证图表配置（规则10：占比 → pie + distribution）
        assert result['chart_type'] == 'pie'
        assert result['intent'] == 'distribution'
        assert result['x_field'] == '城市'


# ============================================================
# 测试用例 6：降级解析 — LLM 不支持 Function Calling
# ============================================================

class TestFallbackParsing:
    """测试降级解析场景。

    当 LLM 不支持 Function Calling 时，从纯文本中提取 JSON 并解析。
    对应前端 llmFullAnalysis [行4467] 的 content.match(/\\{[\\s\\S]*\\}/) 逻辑。
    """

    @pytest.mark.asyncio
    async def test_content_json_fallback(self, sql_generator, mock_llm_client, sales_schema):
        """测试：LLM 返回纯文本 JSON 时的降级解析。"""
        mock_llm_client.generate_sql.return_value = make_content_response({
            'dimension': '城市',
            'metric': '销售额',
            'secondaryMetric': None,
            'allMetrics': ['销售额'],
            'aggregation': 'sum',
            'isScalar': False,
            'filters': [],
            'havingCond': None,
            'sortOrder': 'desc',
            'limit': 10,
            'intent': 'distribution',
            'chartType': 'pie',
            'queryUnderstanding': '您想了解各城市的销售额占比分布',
            'ratioColumn': None,
            'ratioValue': None,
        })

        result = await sql_generator.generate(
            question='各城市的销售额占比',
            schema_info=sales_schema,
        )

        # 降级模式：从 JSON 字段拼接 SQL
        assert result['chart_type'] == 'pie'
        assert result['intent'] == 'distribution'
        assert result['x_field'] == '城市'
        assert 'SELECT' in result['sql']
        assert 'data_table' in result['sql']


# ============================================================
# 测试用例 7：SQL 执行失败时的重试
# ============================================================

class TestSQLExecutionRetry:
    """测试 SQL 执行失败时将错误信息发回 LLM 修正。

    验证 QueryProcessor 的 SQL_EXEC_MAX_RETRIES 重试机制。
    """

    @pytest.mark.asyncio
    async def test_sql_error_retry(self, mock_llm_client, sales_schema):
        """测试：SQL 语法错误 → 错误信息回传 LLM → LLM 修正 → 执行成功。"""
        from core.query_processor import QueryProcessor
        from core.sql_generator import SQLGenerator

        # Mock SQLGenerator
        sql_generator = Mock(spec=SQLGenerator)
        sql_generator.generate = AsyncMock()

        # Mock SQLExecutor — 第 1 次失败，第 2 次成功
        sql_executor = Mock()
        sql_executor.execute = Mock(
            side_effect=[
                Exception('near "COUNT": syntax error'),  # 第 1 次：语法错误
                {'columns': ['部门', 'count'], 'rows': [{'部门': '研发部', 'count': 45}], 'count': 1},  # 第 2 次：成功
            ]
        )

        # Mock DataManager
        data_manager = Mock()
        data_manager.get_schema = Mock(return_value={'db_path': '/tmp/test.db'})
        data_manager.build_data_profile = Mock(return_value=sales_schema)

        # Mock cache
        cache = Mock()
        cache.search = Mock(return_value=None)
        cache.add = Mock()

        # 第 1 次 generate 返回有语法错误的 SQL
        # 第 2 次 generate（重试）返回修正后的 SQL
        sql_generator.generate.side_effect = [
            {
                'sql': 'SELECT "部门" COUNT(*) FROM data_table GROUP BY "部门"',  # 缺逗号
                'chart_type': 'bar',
                'x_field': '部门',
                'y_field': 'count',
                'aggregation': 'count',
                'intent': 'ranking',
                'insight': '研发部人数最多',
                'explanation': '您想了解各部门的员工数量',
                'filters': [],
                'sort_order': 'desc',
                'limit': None,
            },
            {
                'sql': 'SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC',
                'chart_type': 'bar',
                'x_field': '部门',
                'y_field': 'count',
                'aggregation': 'count',
                'intent': 'ranking',
                'insight': '研发部人数最多',
                'explanation': '您想了解各部门的员工数量',
                'filters': [],
                'sort_order': 'desc',
                'limit': None,
            },
        ]

        # Mock LLM generate_sql for retry
        mock_llm_client.generate_sql = AsyncMock(return_value=make_tool_call_response({
            'sql': 'SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC',
            'chart_type': 'bar',
            'x_field': '部门',
            'y_field': 'count',
            'aggregation': 'count',
            'intent': 'ranking',
            'insight': '研发部人数最多',
            'explanation': '您想了解各部门的员工数量',
            'filters': [],
            'sort_order': 'desc',
            'limit': None,
        }))

        # Mock _parse_llm_response and _validate_fields
        sql_generator._parse_llm_response = Mock(return_value={
            'sql': 'SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC',
            'chart_type': 'bar',
            'x_field': '部门',
            'y_field': 'count',
            'aggregation': 'count',
            'intent': 'ranking',
            'insight': '研发部人数最多',
            'explanation': '您想了解各部门的员工数量',
            'filters': [],
            'sort_order': 'desc',
            'limit': None,
        })
        sql_generator._validate_fields = Mock()

        processor = QueryProcessor(
            cache=cache,
            sql_generator=sql_generator,
            sql_executor=sql_executor,
            data_manager=data_manager,
            llm_client=mock_llm_client,
        )

        # Mock _get_db_path and _save_history
        processor._get_db_path = Mock(return_value='/tmp/test.db')
        processor._save_history = Mock()

        result = await processor.process(
            question='各部门的员工数量',
            dataset_id='test-dataset',
        )

        # 验证：SQL 执行调用了 2 次（第 1 次失败，第 2 次成功）
        assert sql_executor.execute.call_count == 2
        # 验证：最终返回修正后的 SQL
        assert 'COUNT(*) as count' in result['sql']
        assert result['result'] is not None
        assert result['result']['count'] == 1


# ============================================================
# 测试用例 8：字段校验
# ============================================================

class TestFieldValidation:
    """测试字段校验。"""

    @pytest.mark.asyncio
    async def test_invalid_chart_type_corrected(self, sql_generator, mock_llm_client, sales_schema):
        """测试：无效的 chart_type 被修正为 table。"""
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': 'SELECT * FROM data_table',
            'chart_type': 'invalid_type',
            'x_field': '',
            'y_field': '',
            'aggregation': None,
            'intent': 'summary',
            'insight': '测试',
            'explanation': '测试',
            'filters': [],
            'sort_order': None,
            'limit': None,
        })

        result = await sql_generator.generate(
            question='查看所有数据',
            schema_info=sales_schema,
        )

        assert result['chart_type'] == 'table'

    @pytest.mark.asyncio
    async def test_empty_sql_rejected(self, sql_generator, mock_llm_client, sales_schema):
        """测试：空 SQL 被拒绝并触发重试。"""
        mock_llm_client.generate_sql.return_value = make_tool_call_response({
            'sql': '',
            'chart_type': 'table',
            'x_field': '',
            'y_field': '',
            'aggregation': None,
            'intent': 'summary',
            'insight': '测试',
            'explanation': '测试',
            'filters': [],
            'sort_order': None,
            'limit': None,
        })

        with pytest.raises(SQLGenerationError):
            await sql_generator.generate(
                question='无效问题',
                schema_info=sales_schema,
            )
```

### 9.3 测试场景与规则对照

| 测试用例 | 输入问题 | 期望 SQL | 期望 chart_type | 期望 intent | 验证的规则 |
|---------|---------|---------|----------------|------------|-----------|
| 1. 简单汇总 | 总销售额是多少 | `SELECT SUM("销售额") as total FROM data_table` | `number` | `summary` | 规则 6（原始列名）、规则 1（SELECT only） |
| 2. 分组查询 | 各部门的员工数量 | `SELECT "部门", COUNT(*) as count FROM data_table GROUP BY "部门" ORDER BY count DESC` | `bar` | `ranking` | 规则 7（各XX→dimension）、规则 14（人数→count）、规则 9（排名→desc） |
| 3. 趋势查询 | 销售额的月度趋势 | `SELECT strftime('%Y-%m', "上架日期") as month, SUM("销售额") as total FROM data_table GROUP BY month ORDER BY month` | `line` | `trend` | 规则 8（趋势→日期列+line+trend）、规则 3（SQLite日期函数） |
| 4. 筛选查询 | 销售额超过10000的门店 | `SELECT "门店名称", "销售额" FROM data_table WHERE "销售额" > 10000 ORDER BY "销售额" DESC` | `table` | `filter` | 规则 12（XX为YY→filters+filter） |
| 5. 占比查询 | 各城市的销售额占比 | `SELECT "城市", SUM("销售额") as total FROM data_table GROUP BY "城市" ORDER BY total DESC` | `pie` | `distribution` | 规则 10（占比→pie）、规则 7（各XX→dimension） |

### 9.4 运行测试

```bash
# 确保在项目根目录
cd "e:\数分精灵demo minmax\最新版-数分ai"

# 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 安装测试依赖
pip install pytest pytest-asyncio

# 运行单元测试（不需要 LLM API Key）
python -m pytest tests/test_sql_generator.py -v

# 生成测试覆盖率报告
pip install pytest-cov
python -m pytest tests/ --cov=core --cov=utils --cov-report=term-missing
```

---

## 附录：模块文件清单

| 文件路径 | 类型 | 说明 |
|---------|------|------|
| `utils/__init__.py` | 包标识 | 空文件 |
| `utils/llm_client.py` | 新建 | LLM 客户端封装（异步） |
| `core/prompts.py` | 新建 | Prompt 模板管理（System Prompt 16 条规则 + User Prompt） |
| `core/tools.py` | 新建 | Function Calling 工具定义（`QUERY_ANALYSIS_FUNCTION`） |
| `core/sql_generator.py` | 新建 | SQL 生成器 |
| `core/query_processor.py` | 新建 | 查询处理器（编排模块，含 SQL 执行失败重试） |
| `routes/query.py` | 新建 | 查询 API 路由 |
| `tests/test_sql_generator.py` | 新建 | SQL 生成器单元测试（8 个测试场景） |
| `app.py` | 修改 | 注册 query 蓝图 |
| `config.py` | 修改 | 补充 LLM 配置项 |

### 与前序文档的关系

| 文档 | 本文档依赖 |
|------|-----------|
| 00-项目总览与背景分析 | LLM 函数定位（callLLM / llmFullAnalysis / llmDeepInterpretation） |
| 01-技术选型与系统架构 | LLM 选型（DeepSeek 默认）、Function Calling 架构决策 |
| 02-Flask后端搭建指南 | `config.py`（LLM_CONFIG）、`DataManager`、`SQLExecutor`、`SQLValidationError`、`models/`、Flask 蓝图机制 |
| 本文档（03） | 定义 `LLMClient`、`SQLGenerator`、`QueryProcessor`、`routes/query.py` |
| 04-语义缓存与性能优化 | `CacheManager`（FAISS 语义缓存）、`build_insight_prompt` |
