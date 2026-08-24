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

    async def chat(
        self,
        telegram_id: int,
        chat_id: int,
        text: str,
        username: str | None = None,
        first_name: str | None = None,
    ) -> str | None:
        """多轮对话接口。"""
        try:
            resp = await self._client.post(
                "/chat",
                json={
                    "telegram_id": telegram_id,
                    "chat_id": chat_id,
                    "text": text,
                    "username": username,
                    "first_name": first_name,
                },
            )
            resp.raise_for_status()
            return str(resp.json()["reply"])
        except (httpx.HTTPError, KeyError) as e:
            logger.warning(f"agent 对话调用失败：{e}")
            return None

    async def register(self, telegram_id: int, username: str | None, first_name: str | None) -> None:
        """注册/更新用户（/start 命令）。"""
        try:
            resp = await self._client.post(
                "/users/register",
                json={
                    "telegram_id": telegram_id,
                    "username": username,
                    "first_name": first_name,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"用户注册失败：{e}")

    async def clear_session(self, telegram_id: int, chat_id: int) -> bool:
        """清空会话上下文（/new 命令）。"""
        try:
            resp = await self._client.post(
                "/sessions/clear",
                json={"telegram_id": telegram_id, "chat_id": chat_id},
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning(f"清空上下文失败：{e}")
            return False

    async def get_models(self) -> list[str]:
        """获取可用模型列表（/model 命令）。"""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            return [str(m) for m in resp.json()]
        except httpx.HTTPError as e:
            logger.warning(f"获取模型列表失败：{e}")
            return []

    async def get_current_model(self, telegram_id: int) -> str | None:
        """获取用户当前生效的模型。"""
        try:
            resp = await self._client.get("/models/current", params={"telegram_id": telegram_id})
            resp.raise_for_status()
            return str(resp.json()["model"])
        except httpx.HTTPError as e:
            logger.warning(f"获取当前模型失败：{e}")
            return None

    async def select_model(self, telegram_id: int, model: str) -> tuple[bool, str]:
        """设置用户偏好模型，返回 (是否成功, 提示信息)。"""
        try:
            resp = await self._client.post(
                "/models/select",
                json={"telegram_id": telegram_id, "model": model},
            )
            if resp.status_code == 400:
                return False, f"模型 {model} 不在可用列表中。"
            resp.raise_for_status()
            return True, f"已切换模型为 <b>{model}</b>。"
        except httpx.HTTPError as e:
            logger.warning(f"切换模型失败：{e}")
            return False, "AI 服务暂时不可用，请稍后重试。"
