# aiChatBot — Telegram 智能聊天机器人

基于 Telegram Bot API 的智能聊天机器人，通过 [RouterHub](../codexProxyHub)（自研 Rust OpenAI 兼容中转网关）对接各大模型，实现自然流畅的多轮对话。

> 详细设计文档见 [docs.md](docs.md)。

## 功能特性

- 🤖 对接大模型：所有 LLM 请求经 RouterHub 中转，厂商密钥统一管理
- 💬 多轮上下文记忆：SQLite 持久化会话历史，超长自动裁剪
- 🔀 动态模型切换：`/model` 命令实时获取 RouterHub 可用模型列表
- 🛡️ 健壮性保障：超时重试、长文本自动分段、错误兜底
- 📊 管理后台：用户管理、对话统计（基础版）

## 系统架构

项目分为三大模块：

```
Telegram 用户                    管理员浏览器
     │  (消息)                        │
     ▼                               ▼
┌─────────────┐              ┌─────────────┐
│   bot-api   │              │  admin-web  │
│  (aiogram)  │              │  (FastAPI)  │
└──────┬──────┘              └──────┬──────┘
       │ 内部 REST                   │ 内部 REST
       ▼                            ▼
┌─────────────────────────────────────────┐
│                ai-agent                 │
│  会话管理 / Prompt 编排 / LLM 调用         │
│  SQLite：会话历史、用户、配置（统一持有）    │
└───────────────────┬─────────────────────┘
                    ▼
        ┌───────────────────────────┐
        │ RouterHub（codexProxyHub） │
        └───────────┬───────────────┘
                    ▼
             各大模型服务商 API
```

| 模块 | 职责 |
|------|------|
| **bot-api** | Telegram 接入：命令解析、消息收发、用户体验 |
| **ai-agent** | AI 核心：会话上下文管理、Prompt 编排；持有数据库，提供内部 REST API |
| **admin-web** | 管理后台：用户管理、对话统计、人设与模型配置 |

## 技术栈

- **语言**：Python 3.11+（uv 管理依赖）
- **bot-api**：aiogram 3.x
- **ai-agent / admin-web**：FastAPI + uvicorn
- **LLM 接入**：openai SDK（async），`base_url` 指向 RouterHub
- **存储**：SQLite + aiosqlite
- **部署**：Docker + docker-compose

## 快速开始

### 前置要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- 运行中的 RouterHub 服务（默认 `http://127.0.0.1:8000/v1`）

### 安装与配置

```bash
# 克隆并安装依赖
git clone <repo-url> && cd aiChatBot
uv sync

# 创建配置文件
cp .env.example .env
# 编辑 .env，填入 Telegram Bot Token 与 RouterHub 地址/令牌
```

`.env` 关键配置：

```env
TELEGRAM_BOT_TOKEN=你的BotToken          # @BotFather 获取
LLM_BASE_URL=http://127.0.0.1:8000/v1   # RouterHub 地址
LLM_API_KEY=RouterHub访问令牌
LLM_MODEL=gpt-4o-mini                   # 默认模型名
ADMIN_PASSWORD=请设置为强密码             # 管理后台密码（支持 argon2 哈希）
JWT_SECRET=随机长密钥                    # 管理后台 JWT 签发密钥
```

### 本地开发：dev.sh 一键脚本

```bash
./dev.sh start     # 启动 agent / bot / admin 三个服务（后台运行）
./dev.sh stop      # 停止全部服务
./dev.sh restart   # 重启
./dev.sh status    # 查看运行状态
```

说明：

- 首次运行自动执行 `uv sync` 安装依赖；缺少 `.env` 会报错退出
- 未配置 `TELEGRAM_BOT_TOKEN` 时自动跳过 bot-api，agent/admin 可正常启动
- 日志输出到 `logs/<服务名>.log`，PID 记录在 `.run/`
- 服务地址：ai-agent `http://127.0.0.1:8100`（接口文档 `/docs`）、管理后台 `http://127.0.0.1:8200`

### 生产部署：Docker Compose

```bash
cp .env.example .env    # 填好配置后：
docker compose up -d --build
```

编排说明：

| 服务 | 容器 | 端口 | 说明 |
|------|------|------|------|
| agent | aichatbot-agent | 8100 | 带 healthcheck，SQLite 经 `./data` 卷持久化 |
| bot | aichatbot-bot | - | 等 agent 健康后自动启动 |
| admin | aichatbot-admin | 8200 | 等 agent 健康后自动启动 |

- 镜像内不含任何密钥，配置全部来自 `.env` 运行时注入
- 容器间通过服务名互访；RouterHub 在宿主机时经 `host.docker.internal:8000` 访问（Linux 兼容已处理），如 RouterHub 在其他机器，将 `.env` 中 `LLM_BASE_URL` 改为实际可达地址即可
- 查看日志：`docker compose logs -f bot`；更新部署：`git pull && docker compose up -d --build`

## Bot 命令

| 命令 | 功能 |
|------|------|
| `/start` | 注册用户、发送欢迎语 |
| `/help` | 显示帮助信息 |
| `/new` | 清空当前会话上下文，开启新对话 |
| `/model` | 查看/切换当前模型 |

## 开发计划

- [x] M1 项目初始化：uv 环境、三服务骨架、配置加载
- [x] M2 ai-agent 核心：内部 API + LLM 客户端封装
- [x] M3 bot-api 接入：完整对话链路 + 多轮上下文
- [x] M4 健壮性：重试、分段、错误兜底、日志
- [x] M5 admin-web 基础版：登录 + 用户列表 + 统计
- [x] M6 部署：Dockerfile + docker-compose 编排

> v1.0 已完成。后续路线见 [docs.md](docs.md) 第 8 节。

## License

MIT
