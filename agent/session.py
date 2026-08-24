"""会话上下文管理：SQLite 读写多轮历史与用户偏好模型。"""

from typing import Any

import aiosqlite


class SessionStore:
    """基于 SQLite 的会话存储（由 agent 独占访问）。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self._db_path)

    async def ensure_user(self, telegram_id: int, username: str | None, first_name: str | None) -> None:
        """注册/更新用户（幂等）。"""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO users (telegram_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    first_name = COALESCE(excluded.first_name, users.first_name)
                """,
                (telegram_id, username, first_name),
            )
            await db.commit()

    async def get_history(self, telegram_id: int, chat_id: int, limit: int) -> list[dict[str, str]]:
        """读取最近 limit 条历史（按时间正序返回）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT role, content FROM messages
                WHERE telegram_id = ? AND chat_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (telegram_id, chat_id, limit),
            )
            rows: list[Any] = await cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def append_messages(self, telegram_id: int, chat_id: int, items: list[dict[str, str]], model: str) -> None:
        """追加一轮消息（user + assistant）。"""
        async with self._connect() as db:
            await db.executemany(
                """
                INSERT INTO messages (telegram_id, chat_id, role, content, model)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (telegram_id, chat_id, m["role"], m["content"], model if m["role"] == "assistant" else None)
                    for m in items
                ],
            )
            await db.commit()

    async def clear_history(self, telegram_id: int, chat_id: int) -> int:
        """清空指定会话上下文，返回删除条数。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM messages WHERE telegram_id = ? AND chat_id = ?",
                (telegram_id, chat_id),
            )
            await db.commit()
        return cursor.rowcount or 0

    async def get_preferred_model(self, telegram_id: int) -> str | None:
        """获取用户偏好的模型（未设置时为 None，回退全局默认）。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT preferred_model FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_preferred_model(self, telegram_id: int, model: str) -> bool:
        """设置用户偏好模型，用户不存在时返回 False。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "UPDATE users SET preferred_model = ? WHERE telegram_id = ?",
                (model, telegram_id),
            )
            await db.commit()
        return (cursor.rowcount or 0) > 0
