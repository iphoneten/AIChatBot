"""ai-agent 内部 REST API 路由。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.llm import LLMClient, LLMError
from agent.session import SessionStore
from core.config import get_settings
from core.logging import setup_logging

logger = setup_logging("ai-agent")


class ChatRequest(BaseModel):
    """对话请求体。"""

    telegram_id: int = Field(gt=0)
    chat_id: int
    text: str = Field(min_length=1, max_length=8000)
    username: str | None = None
    first_name: str | None = None


class ChatResponse(BaseModel):
    """对话响应体。"""

    reply: str
    model: str


class ClearRequest(BaseModel):
    """清空上下文请求体。"""

    telegram_id: int = Field(gt=0)
    chat_id: int


class SetModelRequest(BaseModel):
    """设置偏好模型请求体。"""

    telegram_id: int = Field(gt=0)
    model: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    """用户注册请求体。"""

    telegram_id: int = Field(gt=0)
    username: str | None = None
    first_name: str | None = None


def create_router(llm: LLMClient, store: SessionStore) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        """多轮对话：加载历史 → 调 LLM → 保存本轮消息。"""
        settings = get_settings()
        await store.ensure_user(req.telegram_id, req.username, req.first_name)

        model = (await store.get_preferred_model(req.telegram_id)) or settings.llm_model
        history = await store.get_history(req.telegram_id, req.chat_id, settings.max_context_messages)
        messages = [{"role": "system", "content": settings.system_prompt}, *history, {"role": "user", "content": req.text}]

        try:
            reply = await llm.chat(messages, model=model)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e)) from None

        await store.append_messages(
            req.telegram_id,
            req.chat_id,
            [
                {"role": "user", "content": req.text},
                {"role": "assistant", "content": reply},
            ],
            model=model,
        )
        logger.info(f"chat: user={req.telegram_id} model={model} history={len(history)} len={len(reply)}")
        return ChatResponse(reply=reply, model=model)

    @router.post("/users/register")
    async def register(req: RegisterRequest) -> dict[str, bool]:
        """注册/更新用户（对应 Bot 的 /start 命令）。"""
        await store.ensure_user(req.telegram_id, req.username, req.first_name)
        return {"ok": True}

    @router.post("/sessions/clear")
    async def clear_session(req: ClearRequest) -> dict[str, int]:
        """清空指定会话的上下文（对应 Bot 的 /new 命令）。"""
        deleted = await store.clear_history(req.telegram_id, req.chat_id)
        logger.info(f"clear: user={req.telegram_id} 删除 {deleted} 条")
        return {"deleted": deleted}

    @router.get("/models", response_model=list[str])
    async def models() -> list[str]:
        """从 RouterHub 获取可用模型列表。"""
        try:
            return await llm.list_models()
        except Exception as e:  # noqa: BLE001 - 统一转为服务错误
            logger.warning(f"获取模型列表失败：{type(e).__name__}: {e}")
            raise HTTPException(status_code=502, detail="无法获取模型列表，请检查 RouterHub。") from None

    @router.get("/models/current")
    async def current_model(telegram_id: int) -> dict[str, str]:
        """查询用户当前生效的模型。"""
        settings = get_settings()
        preferred = await store.get_preferred_model(telegram_id)
        return {"model": preferred or settings.llm_model}

    @router.post("/models/select")
    async def select_model(req: SetModelRequest) -> dict[str, str]:
        """设置用户偏好模型（校验模型在 RouterHub 可用列表内）。"""
        await store.ensure_user(req.telegram_id, None, None)
        available = await llm.list_models()
        if req.model not in available:
            raise HTTPException(status_code=400, detail=f"模型 {req.model} 不在可用列表中")
        ok = await store.set_preferred_model(req.telegram_id, req.model)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"model": req.model}

    return router
