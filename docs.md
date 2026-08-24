# aiChatBot — Telegram 智能聊天机器人

## 1. 项目简介

基于 Telegram Bot API 的智能聊天机器人，通过对接大语言模型（LLM）实现自然、流畅的对话能力。项目分为三大模块：

| 模块 | 职责 |
|------|------|
| **bot-api** | Telegram 接入：命令解析、消息收发、用户体验（打字状态、分段回复） |
| **ai-agent** | AI 核心：会话上下文管理、Prompt 编排；通过 **RouterHub 中转服务**调用各大模型；持有数据库，提供内部 REST API |
| **admin-web** | 管理后台：用户管理、对话统计、人设 Prompt 与模型配置 |

> **RouterHub（RouteHub，仓库 `codexProxyHub`）**：已有的自研 Rust 桌面版 OpenAI 兼容中转网关。本项目所有 LLM 请求均经它发出：
>
> - 对接地址：`http://127.0.0.1:8000/v1`（可在其配置中修改），Bearer API Key 鉴权可选开启
> - 使用接口：`POST /v1/chat/completions`（对话）、`GET /v1/models`（动态获取可用模型列表，供 `/model` 命令使用）
> - 免费获得的能力：多渠道优先级/权重路由、模型 fallback、上游 429/5xx 重试与故障转移、流式断流续接、SQLite 用量日志
> - 厂商 API Key 由 RouterHub 统一管理；其 `api_keys` 支持 per-Key 日 token 限额与模型白名单，可直接作为本项目用户限额的底层依据

- **v1.0 目标**：三大模块骨架落地，重点完成 bot-api ↔ ai-agent ↔ 大模型的完整对话链路（含多轮上下文记忆）；admin-web 提供基础版（登录 + 用户/对话统计）
- **后续规划**：admin-web 完整功能（在线配置热更新）、群组支持、流式输出、RAG 知识库、语音/图片多模态等

---

## 2. 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | AI 生态最完善，迭代速度快 |
| 工程组织 | 单仓三服务 + 共享包 `core`，uv 管理依赖 | `bot` / `agent` / `admin` 独立进程，公共代码复用 |
| 异步运行时 | asyncio（Python 原生）+ uvloop（可选） | 全链路异步 IO |
| Bot 框架（bot-api） | aiogram 3.x | 异步、类型注解完善、社区活跃，支持 Long Polling 与 Webhook |
| Web 框架（ai-agent / admin-web） | FastAPI + uvicorn | 自动生成 OpenAPI 文档，Pydantic 校验，开发调试友好 |
| LLM 接入（ai-agent） | openai SDK（async）→ **RouterHub** | OpenAI 兼容协议客户端，`base_url` 指向 RouterHub 地址；模型切换由 RouterHub 承担 |
| HTTP 客户端 | httpx（异步） | 服务间调用与 LLM 请求 |
| 数据存储 | SQLite + aiosqlite | v1.0 轻量持久化：会话上下文、用户信息、管理后台数据；由 agent 统一持有 |
| 配置管理 | pydantic-settings | 从 `.env` 读取配置并做类型校验 |
| 认证（admin-web） | argon2 密码哈希（pwdlib/passlib）+ PyJWT | 管理后台登录鉴权 |
| 错误处理 | 自定义异常体系 | 按层定义异常，统一错误响应 |
| 日志 | loguru | 结构化日志，开箱即用 |
| 前端（admin-web） | 服务端渲染静态页（v1.0 基础版） | FastAPI 直接托管 HTML/静态资源；后续可升级 Vue3/React SPA |
| 部署 | Docker + docker-compose | 三个服务独立容器编排；开发期可分别 `python -m bot` 等启动 |

### 备选说明

- **Bot 框架备选**：python-telegram-bot v21+（同样成熟）；如需极致轻量可用 frankenstein 风格的手写 Long Polling。
- **Web 框架备选**：Litestar / aiohttp；FastAPI 为默认选择因生态与文档最全。
- **LLM 备选**：直接用 httpx 手写请求体（依赖更少但需自行维护协议）；后续 RAG 可引入 LangChain/LlamaIndex。
- **存储备选**：SQLAlchemy 2.0（async）+ aiosqlite；若后期需要 Postgres 可平滑切换。

---

## 3. 系统架构

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
│  会话管理器：加载/保存多轮上下文            │
│  LLM 客户端：OpenAI 兼容接口调用           │
│  SQLite：会话历史、用户、配置（统一持有）    │
└───────────────────┬─────────────────────┘
                    ▼
        ┌───────────────────────────┐
        │ RouterHub（codexProxyHub） │
        │ Rust 桌面版 OpenAI 兼容网关 │
        └───────────┬───────────────┘
                    ▼
             各大模型服务商 API
```

**通信方式**：bot-api 与 admin-web 均通过内部 REST 调用 ai-agent，不直连数据库；数据库由 ai-agent 统一持有，保证会话状态一致。

**LLM 链路**：ai-agent → RouterHub → 各模型服务商。厂商密钥由 RouterHub 统一管理，本项目只配置 RouterHub 地址与访问令牌；`/model` 切换模型即切换请求中的 model 名，由 RouterHub 路由到对应服务商。

**部署注意**：RouterHub 是桌面端应用，默认仅监听 `127.0.0.1:8000`。若 Bot 与 RouterHub 不同机部署，需将其 `server.host` 改为 `0.0.0.0` 并开启 `auth.enabled` + API Key 鉴权（同机部署可保持默认，无需鉴权）。

**v1.0 Bot 采用 Long Polling**（无需公网 IP 和 HTTPS 证书，开发部署最简单）；Webhook 模式作为后续可选优化。

---

## 4. 核心功能设计（v1.0）

### 4.1 命令与交互

| 命令/触发 | 功能 |
|-----------|------|
| `/start` | 注册用户、发送欢迎语 |
| `/help` | 显示帮助信息 |
| `/new` | 清空当前会话上下文，开启新对话 |
| `/model` | 经 `GET /v1/models` 从 RouterHub 获取可用模型列表，查看/切换当前模型 |
| 普通文本消息 | 直接作为 Prompt 发送给 LLM 并回复 |

### 4.2 多轮上下文

- 以 `(chat_id, user_id)` 为 key 维护会话历史。
- 每轮将历史 messages（含 system prompt）一并发送给 LLM。
- **上下文长度控制**：超过最大 token 上限时，裁剪最早的历史轮次（保留 system prompt）。

### 4.3 LLM 调用参数

- `system prompt` 可配置（`.env` 或配置文件），定义机器人人设。
- 温度、max_tokens 等参数集中到配置中，便于调整。

### 4.4 异常与体验

- LLM 超时/限流时返回友好错误提示并重试（指数退避，最多 N 次）。
- 回复前发送「正在思考…」状态（`send_chat_action`）。
- 单条回复超过 Telegram 4096 字符上限时自动分段发送。

---

## 5. 目录结构（规划）

```
aiChatBot/
├── .env                # 密钥与配置（不入库）
├── .env.example        # 配置模板
├── docs.md             # 项目文档
├── pyproject.toml      # uv 依赖管理（含 dev 依赖分组）
├── uv.lock             # 锁定文件（入库，保证环境一致）
├── core/               # 共享包：三个服务复用
│   ├── config.py       # 配置加载与校验（pydantic-settings）
│   ├── schemas.py      # 公共数据模型（Pydantic）
│   └── logging.py      # 日志初始化（loguru）
├── bot/                # bot-api：Telegram 接入
│   ├── __main__.py     # 入口：python -m bot 启动
│   ├── handlers.py     # /start /help /new /model 命令 + 文本消息处理
│   └── agent_api.py    # ai-agent 内部 REST 客户端（httpx）
├── agent/              # ai-agent：AI 核心服务
│   ├── __main__.py     # 入口：uvicorn agent.app 启动
│   ├── app.py          # FastAPI 应用工厂、中间件、内部鉴权
│   ├── routes.py       # 内部 REST API（对话/会话管理/模型列表）
│   ├── llm.py          # 大模型调用封装（openai SDK → RouterHub）
│   └── session.py      # 会话上下文管理（裁剪策略）
├── admin/              # admin-web：管理后台
│   ├── __main__.py     # 入口：uvicorn admin.app 启动
│   ├── app.py          # FastAPI 应用、静态资源托管
│   ├── auth.py         # 密码哈希 + JWT 登录
│   ├── routes.py       # 用户列表、对话统计等接口
│   └── static/         # 基础版前端页面
├── schema.sql          # SQLite 建表脚本（agent 启动时执行）
└── data/
    └── bot.db          # SQLite 数据文件（不入库）
```

---

## 6. 环境变量（.env）

```env
# Telegram（bot-api 使用）
TELEGRAM_BOT_TOKEN=你的BotToken        # 通过 @BotFather 创建获取

# LLM（经 RouterHub 中转，OpenAI 兼容协议）
LLM_BASE_URL=http://127.0.0.1:8000/v1 # RouterHub 服务地址（RouteHub 默认端口 8000）
LLM_API_KEY=RouterHub访问令牌           # RouterHub auth.api_keys 中签发的 Key（未开鉴权可留空占位）
LLM_MODEL=gpt-4o-mini                  # 默认模型名，须在 RouterHub 渠道模型列表内，由其路由到对应渠道

# 对话参数
SYSTEM_PROMPT=你是一个乐于助人的中文AI助手
MAX_CONTEXT_MESSAGES=20                # 保留的最大历史条数
LLM_TIMEOUT=60                         # 请求超时（秒）

# 服务地址（bot-api / admin-web 调用 agent 用）
AGENT_BASE_URL=http://127.0.0.1:8100   # ai-agent 内部 API 地址
ADMIN_LISTEN_ADDR=0.0.0.0:8200         # admin-web 监听地址
AGENT_INTERNAL_TOKEN=内部服务间鉴权Token # bot/admin 访问 agent 的简单鉴权

# 管理后台
ADMIN_USERNAME=admin                   # 初始管理员账号
ADMIN_PASSWORD=请修改为强密码            # 初始管理员密码
JWT_SECRET=用于签发管理后台JWT的随机密钥
```

---

## 7. 开发计划

- [ ] **M1 项目初始化**：uv 环境搭建、三服务 + core 骨架、配置加载与校验
- [ ] **M2 ai-agent 核心**：FastAPI 内部 API + LLM 客户端封装（openai SDK → RouterHub），单轮问答跑通
- [ ] **M3 bot-api 接入**：aiogram 命令与消息处理，经 agent 完成完整对话链路；多轮上下文（SQLite）+ `/new` 重置
- [ ] **M4 健壮性**：超时重试、长文本分段、错误兜底、日志、服务间鉴权
- [ ] **M5 admin-web 基础版**：JWT 登录 + 用户列表 + 对话统计
- [ ] **M6 部署**：Dockerfile（三个服务）+ docker-compose 编排

## 8. 后续版本路线（非 v1.0）

- v1.1：流式输出（编辑消息模拟打字效果）、Markdown 渲染
- v1.2：群组支持（@提及或回复触发）、按用户限额控制
- v1.3：RAG 知识库（向量检索）、语音消息转文字
