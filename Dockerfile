# aiChatBot 生产镜像：单镜像承载三个服务（agent / bot / admin）
# 构建镜像内不包含 .env 与任何密钥，配置全部由运行时注入。
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖（利用层缓存：pyproject/uv.lock 不变时跳过）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷贝业务代码
COPY schema.sql ./
COPY core ./core
COPY bot ./bot
COPY agent ./agent
COPY admin ./admin

# 默认启动 ai-agent；bot / admin 由 docker-compose 指定 command 覆盖
CMD ["uv", "run", "--no-sync", "python", "-m", "agent"]
