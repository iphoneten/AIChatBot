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
```

### 启动服务

```bash
# 1. ai-agent（AI 核心服务，端口 8100）
uv run python -m agent

# 2. bot-api（Telegram 接入）
uv run python -m bot

# 3. admin-web（管理后台，端口 8200，可选）
uv run python -m admin
```

## Bot 命令

| 命令 | 功能 |
|------|------|
| `/start` | 注册用户、发送欢迎语 |
| `/help` | 显示帮助信息 |
| `/new` | 清空当前会话上下文，开启新对话 |
| `/model` | 查看/切换当前模型 |

## 开发计划

- [ ] M1 项目初始化：uv 环境、三服务骨架、配置加载
- [ ] M2 ai-agent 核心：内部 API + LLM 客户端封装
- [ ] M3 bot-api 接入：完整对话链路 + 多轮上下文
- [ ] M4 健壮性：重试、分段、错误兜底、日志
- [ ] M5 admin-web 基础版：登录 + 用户列表 + 统计
- [ ] M6 部署：Dockerfile + docker-compose 编排

## License

MIT
