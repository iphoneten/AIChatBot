"""ai-agent 内部 REST API 路由。"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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


class SetRoleRequest(BaseModel):
    """设置偏好角色请求体。"""

    telegram_id: int = Field(gt=0)
    role: str = Field(min_length=1)


class UpsertRoleRequest(BaseModel):
    """管理后台新增/更新人设请求体。"""

    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)


class BanRequest(BaseModel):
    """封禁/解封请求体。"""

    telegram_id: int = Field(gt=0)
    banned: bool
    reason: str | None = Field(default=None, max_length=200)


class LimitRequest(BaseModel):
    """设置每日提问上限请求体（0=跟随全局，-1=不限，>0=具体条数）。"""

    telegram_id: int = Field(gt=0)
    daily_limit: int = Field(ge=-1)


class UpdateAllowedModelsRequest(BaseModel):
    """更新可用模型白名单请求体（空列表=开放全部）。"""

    allowed: list[str] = Field(default_factory=list)


async def check_user_allowed(store: SessionStore, telegram_id: int) -> None:
    """对话入口校验：封禁与每日用量限制，不通过时抛出带中文提示的 403/429。

    限额语义：用户 daily_limit 为 0 时跟随全局默认，-1 为明确不限，>0 为具体上限。
    """
    banned, reason = await store.get_ban_info(telegram_id)
    if banned:
        detail = "你已被封禁"
        if reason:
            detail += f"（原因：{reason}）"
        raise HTTPException(status_code=403, detail=detail + "，如有疑问请联系管理员。")

    settings = get_settings()
    user_limit = await store.get_daily_limit(telegram_id)
    if user_limit == -1:
        return  # 该用户明确不限
    daily_limit = user_limit if user_limit > 0 else settings.default_daily_limit
    if daily_limit > 0:
        used = await store.count_today_user_messages(telegram_id)
        if used >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日提问次数已达上限（{used}/{daily_limit}），明天再来吧。",
            )


async def _allowed_models(llm: LLMClient, store: SessionStore) -> list[str]:
    """用户可见的模型列表：白名单为空时开放 RouterHub 全部模型。"""
    all_models = await llm.list_models()
    raw = await store.get_setting("allowed_models")
    if not raw:
        return all_models
    try:
        allowed = set(json.loads(raw))
    except json.JSONDecodeError:
        logger.warning("allowed_models 设置解析失败，回退开放全部模型")
        return all_models
    return [m for m in all_models if m in allowed]


async def _resolve_model(llm: LLMClient, store: SessionStore, telegram_id: int) -> str:
    """用户生效的模型：偏好模型仍在可用列表内则用之，否则回退全局默认。"""
    settings = get_settings()
    preferred = await store.get_preferred_model(telegram_id)
    if preferred:
        if preferred in await _allowed_models(llm, store):
            return preferred
        logger.warning(f"用户 {telegram_id} 的偏好模型 '{preferred}' 不可用，回退默认模型")
    return settings.llm_model


async def _system_prompt_for(store: SessionStore, telegram_id: int) -> tuple[str, str]:
    """取用户生效的人设，返回 (prompt, 角色名)。

    用户设置了偏好角色且存在时用其 prompt，否则回退全局默认。
    """
    settings = get_settings()
    preferred = await store.get_preferred_role(telegram_id)
    if preferred:
        persona = await store.get_persona(preferred)
        if persona:
            return persona["prompt"], str(persona["name"])
        # 人设可能已被后台删除，回退默认
        logger.warning(f"用户 {telegram_id} 的角色 '{preferred}' 不存在，回退默认人设")
    return settings.system_prompt, "默认"


def create_router(llm: LLMClient, store: SessionStore) -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        """多轮对话：加载历史 → 调 LLM → 保存本轮消息。"""
        settings = get_settings()
        await store.ensure_user(req.telegram_id, req.username, req.first_name)
        await check_user_allowed(store, req.telegram_id)

        system_prompt, _role_name = await _system_prompt_for(store, req.telegram_id)
        model = await _resolve_model(llm, store, req.telegram_id)
        history = await store.get_history(req.telegram_id, req.chat_id, settings.max_context_messages)
        messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": req.text}]

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

    @router.post("/chat/stream")
    async def chat_stream(req: ChatRequest) -> StreamingResponse:
        """流式多轮对话：以 SSE 返回增量，事件为 {"delta"} / {"error"} / {"done"}。

        仅在完整生成成功时持久化本轮消息。
        """
        settings = get_settings()
        await store.ensure_user(req.telegram_id, req.username, req.first_name)
        await check_user_allowed(store, req.telegram_id)
        system_prompt, _role_name = await _system_prompt_for(store, req.telegram_id)
        model = await _resolve_model(llm, store, req.telegram_id)
        history = await store.get_history(req.telegram_id, req.chat_id, settings.max_context_messages)
        messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": req.text}]

        async def generate():
            parts: list[str] = []
            try:
                async for delta in llm.chat_stream(messages, model=model):
                    parts.append(delta)
                    yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            except LLMError as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                return
            reply = "".join(parts)
            await store.append_messages(
                req.telegram_id,
                req.chat_id,
                [
                    {"role": "user", "content": req.text},
                    {"role": "assistant", "content": reply},
                ],
                model=model,
            )
            logger.info(f"chat/stream: user={req.telegram_id} model={model} history={len(history)} len={len(reply)}")
            yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.post("/sessions/clear")
    async def clear_session(req: ClearRequest) -> dict[str, int]:
        """清空指定会话的上下文（对应 Bot 的 /new 命令）。"""
        deleted = await store.clear_history(req.telegram_id, req.chat_id)
        logger.info(f"clear: user={req.telegram_id} 删除 {deleted} 条")
        return {"deleted": deleted}

    @router.get("/models", response_model=list[str])
    async def models() -> list[str]:
        """获取用户可见的模型列表（应用白名单过滤）。"""
        try:
            return await _allowed_models(llm, store)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e)) from None
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
        """设置用户偏好模型（校验模型在可见列表内）。"""
        await store.ensure_user(req.telegram_id, None, None)
        available = await _allowed_models(llm, store)
        if req.model not in available:
            raise HTTPException(status_code=400, detail=f"模型 {req.model} 不在可用列表中")
        ok = await store.set_preferred_model(req.telegram_id, req.model)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"model": req.model}

    @router.get("/roles", response_model=list[dict])
    async def roles() -> list[dict]:
        """可用角色人设列表。"""
        personas = await store.list_personas()
        return [{"name": p["name"], "description": p["description"]} for p in personas]

    @router.get("/roles/current")
    async def current_role(telegram_id: int) -> dict[str, str]:
        """查询用户当前生效的角色人设。"""
        _, role_name = await _system_prompt_for(store, telegram_id)
        return {"role": role_name}

    @router.post("/roles/select")
    async def select_role(req: SetRoleRequest) -> dict[str, str]:
        """设置用户偏好角色人设（校验角色存在）。"""
        await store.ensure_user(req.telegram_id, None, None)
        persona = await store.get_persona(req.role)
        if persona is None:
            raise HTTPException(status_code=400, detail=f"角色 '{req.role}' 不存在")
        ok = await store.set_preferred_role(req.telegram_id, req.role)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"role": req.role}

    @router.get("/admin/models")
    async def admin_models() -> dict:
        """模型设置（管理后台使用）：全部可选与当前白名单。"""
        try:
            all_models = await llm.list_models()
        except Exception as e:  # noqa: BLE001 - 统一转为服务错误
            logger.warning(f"获取模型列表失败：{type(e).__name__}: {e}")
            raise HTTPException(status_code=502, detail="无法获取模型列表，请检查 RouterHub。") from None
        raw = await store.get_setting("allowed_models")
        try:
            allowed: list[str] = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            allowed = []
        return {"all": all_models, "allowed": allowed}

    @router.post("/admin/models")
    async def update_admin_models(req: UpdateAllowedModelsRequest) -> dict[str, int]:
        """更新可用模型白名单（空列表=开放全部，即时生效）。"""
        await store.set_setting(
            "allowed_models", json.dumps(req.allowed, ensure_ascii=False)
        )
        logger.info(f"模型白名单已更新：{len(req.allowed)} 个")
        return {"count": len(req.allowed)}

    @router.get("/admin/roles", response_model=list[dict])
    async def admin_roles() -> list[dict]:
        """全部人设详情（含 prompt，管理后台使用）。"""
        return await store.list_personas()

    @router.post("/admin/roles")
    async def upsert_role(req: UpsertRoleRequest) -> dict[str, str]:
        """新增/更新人设（管理后台使用，即时生效）。"""
        await store.upsert_persona(req.name, req.description, req.prompt)
        logger.info(f"人设已保存：{req.name}")
        return {"name": req.name}

    @router.get("/admin/messages", response_model=list[dict])
    async def admin_messages(
        telegram_id: int | None = None, limit: int = 100
    ) -> list[dict]:
        """最近对话记录（可按用户过滤，管理后台使用）。"""
        return await store.recent_messages(
            telegram_id=telegram_id, limit=min(limit, 500)
        )

    @router.post("/admin/users/ban")
    async def admin_ban(req: BanRequest) -> dict[str, bool]:
        """封禁/解封用户（管理后台使用）。"""
        await store.ensure_user(req.telegram_id, None, None)
        ok = await store.set_banned(req.telegram_id, req.banned, req.reason)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        logger.info(f"用户 {req.telegram_id} 已{'封禁' if req.banned else '解封'}")
        return {"ok": True}

    @router.post("/admin/users/limit")
    async def admin_limit(req: LimitRequest) -> dict[str, int]:
        """设置用户每日提问上限（管理后台使用）。"""
        await store.ensure_user(req.telegram_id, None, None)
        ok = await store.set_daily_limit(req.telegram_id, req.daily_limit)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"telegram_id": req.telegram_id, "daily_limit": req.daily_limit}

    @router.delete("/admin/roles/{name}")
    async def delete_role(name: str) -> dict[str, bool]:
        """删除人设（管理后台使用）；已选该人设的用户自动回退默认。"""
        existed = await store.delete_persona(name)
        if not existed:
            raise HTTPException(status_code=404, detail="人设不存在")
        logger.info(f"人设已删除：{name}")
        return {"ok": True}

    @router.get("/admin/users", response_model=list[dict])
    async def admin_users() -> list[dict]:
        """用户列表（管理后台使用，经内部鉴权保护）。"""
        return await store.list_users()

    @router.get("/admin/stats")
    async def admin_stats() -> dict:
        """全局统计（管理后台使用）。"""
        return await store.get_stats()

    return router
