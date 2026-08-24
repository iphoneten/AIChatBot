"""ai-agent 内部 REST API 路由。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.llm import LLMClient, LLMError
from core.config import get_settings
from core.logging import setup_logging

logger = setup_logging("ai-agent")


class ChatRequest(BaseModel):
    """对话请求体。"""

    telegram_id: int = Field(gt=0)
    chat_id: int
    text: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    """对话响应体。"""

    reply: str


def create_router(llm: LLMClient) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        """单轮问答（M3 扩展为多轮上下文）。"""
        settings = get_settings()
        messages = [
            {"role": "system", "content": settings.system_prompt},
            {"role": "user", "content": req.text},
        ]
        try:
            reply = await llm.chat(messages)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e)) from None
        logger.info(f"chat: user={req.telegram_id} model={settings.llm_model} len={len(reply)}")
        return ChatResponse(reply=reply)

    @router.get("/models", response_model=list[str])
    async def models() -> list[str]:
        """从 RouterHub 获取可用模型列表。"""
        try:
            return await llm.list_models()
        except Exception as e:  # noqa: BLE001 - 统一转为服务错误
            logger.warning(f"获取模型列表失败：{type(e).__name__}: {e}")
            raise HTTPException(status_code=502, detail="无法获取模型列表，请检查 RouterHub。") from None

    return router
