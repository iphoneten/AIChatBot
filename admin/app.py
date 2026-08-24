"""FastAPI 应用工厂：登录鉴权、后台 API、静态资源托管。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from admin.routes import create_admin_router
from core.config import get_settings
from core.logging import setup_logging

logger = setup_logging("admin-web")

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.jwt_secret:
        logger.warning("未配置 JWT_SECRET，管理后台登录不可用")
    app.state.settings = settings
    app.state.agent = httpx.AsyncClient(
        base_url=settings.agent_base_url,
        headers={"X-Internal-Token": settings.agent_internal_token}
        if settings.agent_internal_token
        else {},
        timeout=15.0,
    )
    yield
    await app.state.agent.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="admin-web", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "admin-web"}

    app.include_router(create_admin_router(), prefix="/api")

    # 基础版前端：静态页面托管在根路径（须最后注册避免遮蔽 API）
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")

    return app
