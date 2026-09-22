"""
llm_client.py — LLM 客户端（OpenAI 兼容 API + Function Calling）

设计要点（doc03 §3.6）：
- 用 httpx 异步 POST 到 {LLM_BASE_URL}/v1/chat/completions
- 携带 functions=[EXECUTE_DATA_QUERY_FUNCTION] + function_call={"name": "execute_data_query"}
- 解析 choices[0].message.function_call.arguments → dict
- 失败重试：指数退避 2 次（429/5xx/timeout）
- 4xx 错误（除 429）→ 立即抛 LLMAuthError
- LLM 未触发 function_call → 降级 _fallback_parse（正则提取 JSON 块）
- 暴露 last_error 给 QueryProcessor 写日志

使用方式：
    client = LLMClient()
    result = await client.analyze_question(question, data_profile)
    # result = {"sql": ..., "chart_type": ..., "insight": ..., ...} 或 None

    insight = await client.generate_insight(question, data_profile_summary, query_result)
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, Optional

import httpx

from config import LLM_CONFIG, is_llm_configured
from .function_schema import (
    EXECUTE_DATA_QUERY_FUNCTION,
    validate_function_call,
)
from .prompts import (
    SYSTEM_PROMPT_SQL,
    SYSTEM_PROMPT_INSIGHT,
    build_user_message,
    build_insight_prompt,
)

logger = logging.getLogger(__name__)


# ===== 错误类型 =====
class LLMError(Exception):
    """LLM 调用错误基类"""
    pass


class LLMAuthError(LLMError):
    """API Key 无效 / 权限错误"""
    pass


class LLMRateLimitError(LLMError):
    """429 限流"""
    pass


class LLMTimeoutError(LLMError):
    """超时"""
    pass


class LLMParseError(LLMError):
    """返回内容无法解析"""
    pass


# ===== 重试配置 =====
_MAX_RETRIES = 2  # 最多重试 2 次（共 3 次调用）
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class LLMClient:
    """LLM 客户端（OpenAI 兼容 + Function Calling）"""

    def __init__(self):
        self.api_key = LLM_CONFIG.get("api_key", "")
        self.base_url = LLM_CONFIG.get("base_url", "").rstrip("/")
        self.model = LLM_CONFIG.get("model", "")
        self.timeout = LLM_CONFIG.get("timeout", 30)
        self.temperature = LLM_CONFIG.get("temperature", 0)
        self.max_tokens = LLM_CONFIG.get("max_tokens", 512)

        # 上次错误（暴露给 QueryProcessor）
        self.last_error: Optional[str] = None

        # Backend Item B：错误统计（结构化监控 / 飞书推送用）
        self.error_stats: Dict[str, int] = {
            "auth_error": 0,       # 401/403
            "rate_limit": 0,       # 429
            "server_error": 0,     # 5xx
            "timeout": 0,          # 超时
            "network_error": 0,    # 网络/连接错误
            "parse_error": 0,      # JSON 解析失败
            "validation_error": 0, # 函数调用格式校验失败
            "other": 0,
        }
        self.total_calls: int = 0
        self.failed_calls: int = 0

        # HTTP 客户端（httpx.AsyncClient 复用连接池）
        self._client: Optional[httpx.AsyncClient] = None

    def _record_error(self, error_type: str, detail: str = "") -> None:
        """Backend Item B：记录错误类型（暴露给运维查询）"""
        self.error_stats[error_type] = self.error_stats.get(error_type, 0) + 1
        self.failed_calls += 1
        logger.error(
            f"[LLMClient] 错误类型={error_type} 详情={detail[:200]} "
            f"累计失败={self.failed_calls}/{self.total_calls}"
        )

    def get_health(self) -> Dict[str, Any]:
        """Backend Item B：健康状态（供 /api/diagnostics 查询）"""
        return {
            "configured": self.is_configured(),
            "model": self.model,
            "timeout": self.timeout,
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "error_stats": dict(self.error_stats),
            "last_error": self.last_error,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """懒加载 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        """LLM 是否已配置（API Key 非空）"""
        return is_llm_configured()

    # ===== 核心方法 1：分析问题（生成 SQL + 图表配置） =====
    async def analyze_question(
        self,
        question: str,
        data_profile: str,
        hint: Optional[str] = None,
        conversation_history: Optional[str] = None,
        entity_memory: Optional[Dict[str, str]] = None,
        relevant_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """调用 LLM 分析问题，返回结构化结果

        Args:
            question: 用户自然语言问题
            data_profile: 数据画像 Markdown
            hint: 可选上下文
            conversation_history: 对话历史（Markdown 摘要）
            entity_memory: 字段别名记忆 {alias: realField, ...}
            relevant_rules: 相关规则列表 [{category, text}, ...]（Layer 2 注入）

        Returns:
            校验后的 dict（含 sql/chart_type/insight/...）或 None（失败）
        """
        if not self.is_configured():
            self.last_error = "LLM 未配置（API Key 缺失）"
            logger.warning(f"[LLMClient] {self.last_error}")
            return None

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_SQL},
            {"role": "user", "content": build_user_message(
                question, data_profile, hint,
                conversation_history=conversation_history,
                entity_memory=entity_memory,
                relevant_rules=relevant_rules,
            )},
        ]

        result = await self._call_with_retry(
            messages=messages,
            functions=[EXECUTE_DATA_QUERY_FUNCTION],
            function_call={"name": "execute_data_query"},
        )

        if result is None:
            return None

        # 校验 + 补全
        try:
            validated = validate_function_call(result)
            return validated
        except ValueError as e:
            self.last_error = f"LLM 返回格式无效: {e}"
            logger.error(f"[LLMClient] {self.last_error}: {result}")
            return None

    # ===== 核心方法 2：生成洞察 =====
    async def generate_insight(
        self,
        question: str,
        data_profile_summary: str,
        query_result: Dict[str, Any],
    ) -> Optional[str]:
        """调用 LLM 生成数据洞察

        Args:
            question: 用户问题
            data_profile_summary: 简短数据画像
            query_result: {columns, rows, row_count}

        Returns:
            2-4 句中文洞察文字，失败返回 None
        """
        if not self.is_configured():
            self.last_error = "LLM 未配置"
            return None

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_INSIGHT},
            {"role": "user", "content": build_insight_prompt(question, data_profile_summary, query_result)},
        ]

        # 洞察用普通 chat（不用 function calling）
        result_text = await self._chat_with_retry(messages)

        if result_text is None:
            return None

        # 后处理：清理空白
        insight = result_text.strip()
        if not insight:
            return None

        return insight

    # ===== 底层方法 =====
    async def _call_with_retry(
        self,
        messages: list,
        functions: list,
        function_call: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """带重试的 Function Calling 调用

        Returns:
            解析后的 arguments dict，或 None（所有重试失败）
        """
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "functions": functions,
            "function_call": function_call,
        }

        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            self.total_calls += 1
            try:
                client = await self._get_client()
                t0 = time.time()
                response = await client.post(url, json=payload, headers=headers)
                elapsed_ms = int((time.time() - t0) * 1000)

                # 错误码处理
                if response.status_code == 401 or response.status_code == 403:
                    self.last_error = f"API Key 无效 ({response.status_code})"
                    logger.error(f"[LLMClient] {self.last_error}")
                    self._record_error("auth_error", self.last_error)
                    raise LLMAuthError(self.last_error)

                if response.status_code == 429:
                    self.last_error = f"限流 ({response.status_code})"
                    last_err = self.last_error
                    logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(1 * (2 ** attempt))  # 1s, 2s
                        continue
                    self._record_error("rate_limit", self.last_error)
                    raise LLMRateLimitError(self.last_error)

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    self.last_error = f"服务错误 ({response.status_code})"
                    last_err = self.last_error
                    logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(1 * (2 ** attempt))
                        continue
                    self._record_error("server_error", self.last_error)
                    raise LLMError(self.last_error)

                if response.status_code != 200:
                    self.last_error = f"未知错误 ({response.status_code}): {response.text[:200]}"
                    logger.error(f"[LLMClient] {self.last_error}")
                    self._record_error("other", self.last_error)
                    return None

                # 解析成功响应
                data = response.json()
                logger.debug(f"[LLMClient] 调用成功: status=200, elapsed_ms={elapsed_ms}")

                # 提取 function_call.arguments
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                func_call = message.get("function_call")
                content = message.get("content", "")

                if func_call and func_call.get("name") == "execute_data_query":
                    args_str = func_call.get("arguments", "{}")
                    try:
                        args = json.loads(args_str)
                        return args
                    except json.JSONDecodeError as e:
                        self.last_error = f"function_call.arguments 不是合法 JSON: {e}"
                        logger.error(f"[LLMClient] {self.last_error}: {args_str[:200]}")
                        self._record_error("parse_error", self.last_error)
                        # 尝试 fallback 解析 content
                        return self._fallback_parse(content)

                # 未触发 function_call → 尝试从 content 提取 JSON
                logger.warning("[LLMClient] LLM 未触发 function_call，尝试 fallback parse")
                return self._fallback_parse(content)

            except httpx.TimeoutException as e:
                self.last_error = f"LLM 调用超时 ({self.timeout}s)"
                last_err = self.last_error
                logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                logger.error(f"[LLMClient] 重试 {_MAX_RETRIES} 次仍超时")
                self._record_error("timeout", self.last_error)
                return None

            except httpx.RequestError as e:
                self.last_error = f"网络错误: {e}"
                last_err = self.last_error
                logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                self._record_error("network_error", self.last_error)
                return None

            except (LLMAuthError, LLMRateLimitError):
                # 不可重试的错误
                return None

            except LLMError:
                # 重试已耗尽
                return None

        # 重试耗尽
        self.last_error = last_err or "未知错误"
        return None

    async def _chat_with_retry(self, messages: list) -> Optional[str]:
        """带重试的普通 chat 调用（用于洞察生成）"""
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            self.total_calls += 1
            try:
                client = await self._get_client()
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 401 or response.status_code == 403:
                    self.last_error = f"API Key 无效 ({response.status_code})"
                    logger.error(f"[LLMClient] {self.last_error}")
                    self._record_error("auth_error", self.last_error)
                    return None

                if response.status_code == 429:
                    self.last_error = f"限流 ({response.status_code})"
                    last_err = self.last_error
                    logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(1 * (2 ** attempt))
                        continue
                    self._record_error("rate_limit", self.last_error)
                    return None

                if response.status_code in _RETRYABLE_STATUS_CODES:
                    self.last_error = f"服务错误 ({response.status_code})"
                    last_err = self.last_error
                    logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(1 * (2 ** attempt))
                        continue
                    self._record_error("server_error", self.last_error)
                    return None

                if response.status_code != 200:
                    self.last_error = f"未知错误 ({response.status_code}): {response.text[:200]}"
                    logger.error(f"[LLMClient] {self.last_error}")
                    self._record_error("other", self.last_error)
                    return None

                data = response.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                return content

            except httpx.TimeoutException:
                self.last_error = f"LLM 调用超时 ({self.timeout}s)"
                last_err = self.last_error
                logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                self._record_error("timeout", self.last_error)
                return None

            except httpx.RequestError as e:
                self.last_error = f"网络错误: {e}"
                last_err = self.last_error
                logger.warning(f"[LLMClient] {self.last_error}, attempt={attempt}")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                self._record_error("network_error", self.last_error)
                return None

        # 重试耗尽（理论上不应到达此分支，但保留兜底）
        if last_err and self.failed_calls == 0:
            self._record_error("other", last_err)
        return None

    # ===== Fallback 解析 =====
    def _fallback_parse(self, content: str) -> Optional[Dict[str, Any]]:
        """当 LLM 未触发 function_call 时，从 content 提取 JSON 块

        尝试 3 种模式：
        1. ```json ... ``` 代码块
        2. {...} JSON 对象
        3. 整体当 JSON
        """
        if not content:
            return None

        # 模式 1：```json ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 模式 2：花括号包裹的 JSON
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        # 模式 3：整体
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        self.last_error = "LLM 返回内容无法解析为 JSON"
        logger.error(f"[LLMClient] {self.last_error}: {content[:200]}")
        return None


# ===== 模块单例 =====
_llm_client_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例（懒加载）"""
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LLMClient()
    return _llm_client_instance


# ===== 模块暴露 =====
__all__ = [
    "LLMClient",
    "LLMError",
    "LLMAuthError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMParseError",
    "get_llm_client",
]
