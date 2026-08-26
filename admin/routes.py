"""admin-web 后台接口：登录签发 JWT，受保护数据接口代理 ai-agent。"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from admin.auth import create_jwt, decode_jwt, verify_password
from core.config import Settings
from core.logging import setup_logging

logger = setup_logging("admin-web")

_bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str
    password: str


class UpsertRoleRequest(BaseModel):
    """新增/更新人设请求体。"""

    name: str
    description: str = ""
    prompt: str


def require_admin(
    request: Request,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """JWT 鉴权依赖：校验通过返回管理员用户名。"""
    secret: str = get_settings(request).jwt_secret
    if not secret:
        raise HTTPException(status_code=503, detail="管理后台未配置 JWT_SECRET，无法鉴权")
    if cred is None:
        raise HTTPException(status_code=401, detail="未登录")
    subject = decode_jwt(cred.credentials, secret)
    if subject is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return subject


def get_settings(request: Request) -> Settings:
    """从应用状态获取配置。"""
    return request.app.state.settings


def _check_password(settings: Settings, password: str) -> bool:
    """校验密码：支持明文与 argon2 哈希两种配置形式。"""
    stored = settings.admin_password
    if not stored:
        return False
    if stored.startswith("$argon2"):
        return verify_password(password, stored)
    return hmac.compare_digest(stored.encode(), password.encode())


def create_admin_router() -> APIRouter:
    router = APIRouter()

    @router.post("/login")
    async def login(request: Request, req: LoginRequest) -> dict[str, str]:
        """管理员登录，成功返回 JWT。"""
        settings = get_settings(request)
        if not settings.jwt_secret:
            raise HTTPException(status_code=503, detail="管理后台未配置 JWT_SECRET")
        ok_user = hmac.compare_digest(
            settings.admin_username.encode(), req.username.encode()
        )
        if not (ok_user and _check_password(settings, req.password)):
            logger.warning(f"登录失败：{req.username}")
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return {"token": create_jwt(req.username, settings.jwt_secret)}

    @router.get("/stats")
    async def stats(request: Request, _: Annotated[str, Depends(require_admin)]) -> dict:
        """全局统计。"""
        resp = await request.app.state.agent.get("/admin/stats")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="无法从 AI 服务读取数据")
        data: dict = resp.json()
        return data

    @router.get("/users", response_model=list[dict])
    async def users(request: Request, _: Annotated[str, Depends(require_admin)]) -> list[dict]:
        """用户列表。"""
        resp = await request.app.state.agent.get("/admin/users")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="无法从 AI 服务读取数据")
        result: list[dict] = resp.json()
        return result

    @router.get("/roles", response_model=list[dict])
    async def roles(request: Request, _: Annotated[str, Depends(require_admin)]) -> list[dict]:
        """人设列表（含 prompt）。"""
        resp = await request.app.state.agent.get("/admin/roles")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="无法从 AI 服务读取数据")
        result: list[dict] = resp.json()
        return result

    @router.post("/roles")
    async def save_role(
        request: Request,
        req: UpsertRoleRequest,
        _: Annotated[str, Depends(require_admin)],
    ) -> dict:
        """新增/更新人设。"""
        resp = await request.app.state.agent.post("/admin/roles", json=req.model_dump())
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="保存失败")
        data: dict = resp.json()
        return data

    @router.delete("/roles/{name}")
    async def delete_role(
        request: Request, name: str, _: Annotated[str, Depends(require_admin)]
    ) -> dict:
        """删除人设。"""
        from urllib.parse import quote

        resp = await request.app.state.agent.delete(f"/admin/roles/{quote(name)}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="人设不存在")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="删除失败")
        return {"ok": True}

    return router
