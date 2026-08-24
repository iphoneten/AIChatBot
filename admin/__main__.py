"""admin-web 入口：python -m admin 启动。"""

import uvicorn

from core.config import get_settings
from core.logging import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging("admin-web")
    host, _, port = settings.admin_listen_addr.rpartition(":")
    uvicorn.run(
        "admin.app:create_app",
        factory=True,
        host=host or "0.0.0.0",
        port=int(port),
    )


if __name__ == "__main__":
    main()
