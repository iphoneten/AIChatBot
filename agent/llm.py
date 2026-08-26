"""大模型调用封装：openai SDK（async），base_url 指向 RouterHub。"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from core.config import Settings
from core.logging import setup_logging

logger = setup_logging("ai-agent")

T = TypeVar("T")

# 视为瞬态错误、可重试的状态码（429 限流 / 5xx 服务端错误）
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_FALLBACK_HINT = "AI 服务暂时不可用，请稍后重试。"


class LLMError(Exception):
    """LLM 调用失败，message 为面向用户的中文提示。"""


class _EmptyReplyError(Exception):
    """模型返回 200 但内容为空（RouterHub 渠道偶发现象，可重试）。"""


def _is_transient(e: Exception) -> bool:
    """判断是否为瞬态错误（超时/断连/限流/上游 5xx）。"""
    if isinstance(e, (APITimeoutError, APIConnectionError)):
        return True
    return isinstance(e, APIStatusError) and e.status_code in _RETRYABLE_STATUS_CODES


class LLMClient:
    """RouterHub（OpenAI 兼容协议）对话客户端。

    瞬态错误自动重试（指数退避）；非瞬态错误立即失败并转为用户可读提示。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "unused",  # RouterHub 未开鉴权时占位
            timeout=settings.llm_timeout,
            max_retries=0,  # SDK 内部重试关闭，统一由本类控制重试策略
        )

    async def _call_with_retry(self, do: Callable[[], Awaitable[T]], model: str) -> T:
        """执行调用并对瞬态错误做指数退避重试。"""
        max_attempts = max(1, self._settings.llm_max_retries)
        last_hint = _FALLBACK_HINT
        for attempt in range(1, max_attempts + 1):
            try:
                return await do()
            except _EmptyReplyError:
                # 空回复：RouterHub 渠道偶发现象，按瞬态错误重试
                last_hint = "模型返回了空回复，请稍后重试或更换模型。"
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)
                    logger.warning(f"LLM 空回复（第 {attempt}/{max_attempts} 次，{delay}s 后重试）")
                    await asyncio.sleep(delay)
                    continue
                logger.warning("LLM 空回复达到最大重试次数")
                break
            except LLMError as e:
                # 业务性失败（如无可用模型）：不重试，直接抛出
                logger.warning(f"LLM 业务失败（model={model}）：{e}")
                raise
            except Exception as e:  # noqa: BLE001 - 统一分类处理
                last_hint = self._hint_for(e)
                if attempt < max_attempts and _is_transient(e):
                    delay = 2 ** (attempt - 1)  # 1s, 2s, 4s ...
                    logger.warning(
                        f"LLM 瞬态错误（第 {attempt}/{max_attempts} 次，{delay}s 后重试）："
                        f"{type(e).__name__}: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning(f"LLM 调用最终失败（model={model}）：{type(e).__name__}: {e}")
                break
        raise LLMError(last_hint)

    @staticmethod
    def _hint_for(e: Exception) -> str:
        """异常类型 → 面向用户的中文提示。"""
        if isinstance(e, APITimeoutError):
            return "模型响应超时，请稍后重试。"
        if isinstance(e, APIConnectionError):
            return "无法连接模型服务（RouterHub），请检查其是否在运行。"
        if isinstance(e, APIStatusError):
            if e.status_code == 429:
                return "模型服务限流中，请稍后重试。"
            if e.status_code in (401, 403):
                return "模型服务鉴权失败，请检查访问令牌配置。"
        return _FALLBACK_HINT

    async def chat(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        """发送 messages（含 system prompt 与历史），返回助手回复文本。

        model 为空时使用全局默认模型。
        """
        use_model = model or self._settings.llm_model

        async def do() -> str:
            resp = await self._client.chat.completions.create(
                model=use_model,
                messages=messages,  # type: ignore[arg-type]
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise _EmptyReplyError()
            return content

        return await self._call_with_retry(do, use_model)

    async def chat_stream(
        self, messages: list[dict[str, str]], model: str | None = None
    ):
        """流式对话：逐段产出文本增量。

        重试语义与 chat 一致，但仅在首个增量产出前有效；
        输出中断（已产出部分内容）时直接失败，由调用方决定如何收尾。
        """
        use_model = model or self._settings.llm_model
        max_attempts = max(1, self._settings.llm_max_retries)
        for attempt in range(1, max_attempts + 1):
            produced = False
            try:
                stream = await self._client.chat.completions.create(
                    model=use_model,
                    messages=messages,  # type: ignore[arg-type]
                    stream=True,
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content
                    if delta:
                        produced = True
                        yield delta
                return
            except Exception as e:  # noqa: BLE001 - 统一分类处理
                if produced:
                    logger.warning(f"LLM 流式输出中断（model={use_model}）：{type(e).__name__}")
                    raise LLMError("模型输出中断，请重新发送。") from None
                if attempt < max_attempts and _is_transient(e):
                    delay = 2 ** (attempt - 1)
                    logger.warning(
                        f"LLM 瞬态错误（第 {attempt}/{max_attempts} 次，{delay}s 后重试）："
                        f"{type(e).__name__}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning(f"LLM 流式调用最终失败（model={use_model}）：{type(e).__name__}: {e}")
                raise LLMError(self._hint_for(e)) from None

    async def list_models(self) -> list[str]:
        """从 RouterHub 拉取可用模型列表（GET /v1/models）。"""

        async def do() -> list[str]:
            page = await self._client.models.list()
            ids = sorted(m.id for m in page.data)
            if not ids:
                raise LLMError("RouterHub 未返回任何可用模型。")
            return ids

        return await self._call_with_retry(do, self._settings.llm_model)

    async def aclose(self) -> None:
        await self._client.close()
