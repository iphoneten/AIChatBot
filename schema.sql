-- aiChatBot 数据库结构（SQLite，agent 启动时执行；幂等）
-- 约定：bot 与 admin 不直连数据库，一律经 ai-agent 内部 API 访问。

-- Telegram 用户表
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL UNIQUE,          -- Telegram 用户 ID
    username     TEXT,                             -- @用户名（可变更）
    first_name   TEXT,                             -- 显示名
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 会话消息表（多轮上下文）
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER NOT NULL,                -- 所属用户
    chat_id       INTEGER NOT NULL,                -- Telegram 会话 ID
    role          TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content       TEXT NOT NULL,
    model         TEXT,                            -- assistant 消息记录所用模型
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_user
    ON messages (chat_id, telegram_id, id);
