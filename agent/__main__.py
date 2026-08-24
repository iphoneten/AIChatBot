"""ai-agent 入口：python -m agent 启动。"""

import uvicorn

from core.config import get_settings
from core.logging import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging("ai-agent")
    host, _, port = settings.agent_listen_addr.rpartition(":")
    uvicorn.run(
        "agent.app:create_app",
        factory=True,
        host=host or "0.0.0.0",
        port=int(port),
    )


if __name__ == "__main__":
    main()
