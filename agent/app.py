"""FastAPI 应用工厂：数据库初始化、健康检查、内部鉴权。"""

import asyncio  # noqa: F401 - 预留：后续中间件/后台任务使用
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.logging import setup_logging

logger = setup_logging("ai-agent")

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


async def init_db() -> None:
    """启动时执行 schema.sql 建表（幂等，IF NOT EXISTS）。"""
    import aiosqlite

    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        await db.commit()
    logger.info(f"数据库就绪：{db_path}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ai-agent", lifespan=lifespan)

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        """服务间简单鉴权：校验 X-Internal-Token（未配置 token 时跳过，便于本地开发）。"""
        if settings.agent_internal_token:
            health_path = ("/docs", "/openapi.json", "/health")
            if request.url.path not in health_path and request.headers.get(
                "X-Internal-Token"
            ) != settings.agent_internal_token:
                return JSONResponse({"detail": "无效的内部令牌"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ai-agent"}

    return app
