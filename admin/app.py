"""FastAPI 应用工厂：登录鉴权与后台 API。"""

from fastapi import FastAPI

from core.logging import setup_logging

logger = setup_logging("admin-web")


def create_app() -> FastAPI:
    app = FastAPI(title="admin-web")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "admin-web"}

    return app
