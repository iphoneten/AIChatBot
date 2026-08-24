"""ai-agent 内部 REST 客户端（httpx 异步）。"""

from typing import Self

import httpx

from core.logging import setup_logging

logger = setup_logging("bot-api")


class AgentClient:
    """封装对 ai-agent 内部 API 的调用。"""

    def __init__(self, base_url: str, token: str = "", timeout: float = 90.0) -> None:
        headers = {"X-Internal-Token": token} if token else {}
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers)

    async def __aenter__(self) -> Self:  # type: ignore[override]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        """健康检查。"""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning(f"agent 健康检查失败：{e}")
            return False

    async def chat(self, telegram_id: int, chat_id: int, text: str) -> str | None:
        """对话接口（M2 由 agent 提供 /chat 后生效）。"""
        try:
            resp = await self._client.post(
                "/chat",
                json={
                    "telegram_id": telegram_id,
                    "chat_id": chat_id,
                    "text": text,
                },
            )
            resp.raise_for_status()
            return str(resp.json()["reply"])
        except (httpx.HTTPError, KeyError) as e:
            logger.warning(f"agent 对话调用失败：{e}")
            return None
