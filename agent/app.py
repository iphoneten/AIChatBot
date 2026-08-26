"""FastAPI 应用工厂：数据库初始化、健康检查、内部鉴权。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent.llm import LLMClient
from agent.routes import create_router
from agent.session import SessionStore
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
        # 兼容旧库：新增列已存在时忽略报错
        for column in ("preferred_model TEXT", "preferred_role TEXT"):
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {column}")
            except aiosqlite.OperationalError:
                pass
        await db.commit()
    logger.info(f"数据库就绪：{db_path}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    logger.info("LLM 客户端已就绪（RouterHub 对接）")
    yield
    await app.state.llm.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ai-agent", lifespan=lifespan)
    app.state.llm = LLMClient(settings)

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        """服务间简单鉴权：校验 X-Internal-Token（未配置 token 时跳过，便于本地开发）。"""
        if settings.agent_internal_token:
            public_paths = ("/docs", "/openapi.json", "/health")
            if request.url.path not in public_paths and request.headers.get(
                "X-Internal-Token"
            ) != settings.agent_internal_token:
                return JSONResponse({"detail": "无效的内部令牌"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ai-agent"}

    app.include_router(create_router(app.state.llm, SessionStore(settings.db_path)))

    return app
