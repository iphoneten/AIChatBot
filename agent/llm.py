"""大模型调用封装：openai SDK（async），base_url 指向 RouterHub。"""

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from core.config import Settings
from core.logging import setup_logging

logger = setup_logging("ai-agent")

# LLM 异常类型 → 面向用户的中文提示
_ERROR_HINTS: list[tuple[type[Exception], str]] = [
    (APITimeoutError, "模型响应超时，请稍后重试。"),
    (APIConnectionError, "无法连接模型服务（RouterHub），请检查其是否在运行。"),
    (RateLimitError, "模型服务限流中，请稍后重试。"),
]
_FALLBACK_HINT = "AI 服务暂时不可用，请稍后重试。"


class LLMError(Exception):
    """LLM 调用失败，message 为面向用户的中文提示。"""


class LLMClient:
    """RouterHub（OpenAI 兼容协议）对话客户端。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "unused",  # RouterHub 未开鉴权时占位
            timeout=settings.llm_timeout,
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """发送 messages（含 system prompt 与历史），返回助手回复文本。"""
        try:
            resp = await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,  # type: ignore[arg-type]
            )
            content = resp.choices[0].message.content
            if not content:
                raise LLMError("模型返回了空回复，请更换模型或稍后重试。")
            return content.strip()
        except LLMError:
            raise
        except (APITimeoutError, APIConnectionError, RateLimitError) as e:
            hint = next((h for t, h in _ERROR_HINTS if isinstance(e, t)), _FALLBACK_HINT)
            logger.warning(f"LLM 调用失败：{type(e).__name__}: {e}")
            raise LLMError(hint) from None
        except Exception as e:  # noqa: BLE001 - 兜底转为用户可读错误
            logger.warning(f"LLM 调用失败：{type(e).__name__}: {e}")
            raise LLMError(_FALLBACK_HINT) from None

    async def list_models(self) -> list[str]:
        """从 RouterHub 拉取可用模型列表（GET /v1/models）。"""
        page = await self._client.models.list()
        return sorted(m.id for m in page.data)

    async def aclose(self) -> None:
        await self._client.close()
