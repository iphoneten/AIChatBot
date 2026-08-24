"""日志初始化（loguru）：统一格式，按服务名区分来源。"""

import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru._logger import Logger


def setup_logging(service_name: str) -> "Logger":
    """初始化日志并返回配置好的 loguru logger。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            f"<cyan>{service_name}</cyan> | "
            "<level>{message}</level>"
        ),
    )
    return logger
