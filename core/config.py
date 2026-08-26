"""全局配置：从 .env 读取，pydantic-settings 做类型校验。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置项（全部可通过环境变量覆盖）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram（bot-api）
    telegram_bot_token: str = ""
    telegram_proxy: str = ""  # 访问 api.telegram.org 的代理（如 http://127.0.0.1:7897），留空直连

    # LLM（经 RouterHub 中转，OpenAI 兼容协议）
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # 对话参数
    system_prompt: str = "你是一个乐于助人的中文AI助手"
    max_context_messages: int = 20
    llm_timeout: int = 60
    llm_max_retries: int = 3  # 瞬态错误最大尝试次数（含首次）

    # 服务地址（bot-api / admin-web 调用 agent 用）
    agent_base_url: str = "http://127.0.0.1:8100"
    agent_listen_addr: str = "0.0.0.0:8100"
    admin_listen_addr: str = "0.0.0.0:8200"
    agent_internal_token: str = ""

    # 数据库（agent 持有）
    db_path: str = "data/bot.db"

    # 管理后台
    admin_username: str = "admin"
    admin_password: str = ""
    jwt_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    """返回全局配置单例。"""
    return Settings()
