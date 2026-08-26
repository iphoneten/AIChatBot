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

    async def get_history(
        self, telegram_id: int, chat_id: int, limit: int, shared: bool = False
    ) -> list[dict[str, str]]:
        """读取最近 limit 条历史（按时间正序返回）。

        shared=True 时为群组共享上下文：仅按 chat_id 过滤，不限发言人。
        """
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE chat_id = ?" if shared else "WHERE telegram_id = ? AND chat_id = ?"
            params: tuple[int, ...] = (
                (chat_id, limit) if shared else (telegram_id, chat_id, limit)
            )
            cursor = await db.execute(
                f"""
                SELECT role, content FROM messages
                {where}
                ORDER BY id DESC LIMIT ?
                """,
                params,
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

    async def clear_history(self, telegram_id: int, chat_id: int, shared: bool = False) -> int:
        """清空会话上下文（shared=True 为群组共享上下文），返回删除条数。"""
        async with self._connect() as db:
            if shared:
                cursor = await db.execute(
                    "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM messages WHERE telegram_id = ? AND chat_id = ?",
                    (telegram_id, chat_id),
                )
            await db.commit()
        return cursor.rowcount or 0

    async def list_users(self) -> list[dict[str, Any]]:
        """用户列表（含消息数、今日提问数、封禁与限额，供管理后台使用）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT u.telegram_id, u.username, u.first_name,
                       u.preferred_model, u.preferred_role, u.created_at,
                       u.banned, u.banned_reason, u.daily_limit,
                       COUNT(m.id) AS message_count,
                       MAX(m.created_at) AS last_active,
                       SUM(CASE WHEN m.role = 'user'
                                 AND m.created_at >= date('now', 'localtime')
                            THEN 1 ELSE 0 END) AS today_messages
                FROM users u
                LEFT JOIN messages m ON m.telegram_id = u.telegram_id
                GROUP BY u.id
                ORDER BY u.created_at DESC
                """
            )
            rows: list[Any] = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_stats(self) -> dict[str, Any]:
        """全局统计：用户数、消息数、今日消息数、各模型用量。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async def one(sql: str) -> int:
                cur = await db.execute(sql)
                row = await cur.fetchone()
                return row[0] if row else 0

            total_users = await one("SELECT COUNT(*) FROM users")
            total_messages = await one("SELECT COUNT(*) FROM messages")
            today_messages = await one(
                "SELECT COUNT(*) FROM messages WHERE created_at >= date('now', 'localtime')"
            )
            cur = await db.execute(
                """
                SELECT COALESCE(model, 'unknown') AS model, COUNT(*) AS count
                FROM messages WHERE role = 'assistant'
                GROUP BY model ORDER BY count DESC
                """
            )
            by_model = {r["model"]: r["count"] for r in await cur.fetchall()}
        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "today_messages": today_messages,
            "messages_by_model": by_model,
        }

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

    async def get_preferred_role(self, telegram_id: int) -> str | None:
        """获取用户偏好的角色人设（未设置时为 None，回退默认助手）。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT preferred_role FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_preferred_role(self, telegram_id: int, role: str) -> bool:
        """设置用户偏好角色人设，用户不存在时返回 False。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "UPDATE users SET preferred_role = ? WHERE telegram_id = ?",
                (role, telegram_id),
            )
            await db.commit()
        return (cursor.rowcount or 0) > 0

    # ---------- 角色人设管理 ----------

    async def list_personas(self) -> list[dict[str, Any]]:
        """全部角色人设（按创建顺序）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name, description, prompt FROM personas ORDER BY id"
            )
            rows: list[Any] = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_persona(self, name: str) -> dict[str, Any] | None:
        """按名称获取角色人设。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name, description, prompt FROM personas WHERE name = ?",
                (name,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def upsert_persona(self, name: str, description: str, prompt: str) -> None:
        """新增或更新角色人设。"""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO personas (name, description, prompt)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    prompt = excluded.prompt
                """,
                (name, description, prompt),
            )
            await db.commit()

    async def delete_persona(self, name: str) -> bool:
        """删除角色人设，返回是否存在。"""
        async with self._connect() as db:
            cursor = await db.execute("DELETE FROM personas WHERE name = ?", (name,))
            await db.commit()
        return (cursor.rowcount or 0) > 0

    async def count_personas(self) -> int:
        """人设数量（用于种子导入判断）。"""
        async with self._connect() as db:
            cursor = await db.execute("SELECT COUNT(*) FROM personas")
            row = await cursor.fetchone()
        return row[0] if row else 0

    # ---------- 应用设置（键值对） ----------

    async def get_setting(self, key: str) -> str | None:
        """读取设置项，不存在返回 None。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        """写入设置项。"""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            await db.commit()

    # ---------- 封禁与用量控制 ----------

    async def get_ban_info(self, telegram_id: int) -> tuple[bool, str | None]:
        """查询用户封禁状态，返回 (是否封禁, 原因)。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT banned, banned_reason FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return False, None
        return bool(row[0]), row[1]

    async def set_banned(self, telegram_id: int, banned: bool, reason: str | None = None) -> bool:
        """设置封禁状态，用户不存在时返回 False。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE users
                SET banned = ?, banned_reason = ?
                WHERE telegram_id = ?
                """,
                (int(banned), reason if banned else None, telegram_id),
            )
            await db.commit()
        return (cursor.rowcount or 0) > 0

    async def set_daily_limit(self, telegram_id: int, daily_limit: int) -> bool:
        """设置每日提问上限（0=不限），用户不存在时返回 False。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "UPDATE users SET daily_limit = ? WHERE telegram_id = ?",
                (daily_limit, telegram_id),
            )
            await db.commit()
        return (cursor.rowcount or 0) > 0

    async def get_daily_limit(self, telegram_id: int) -> int:
        """读取用户每日提问上限；用户或值不存在时返回 -1（表示用全局策略）。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT daily_limit FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else -1

    async def count_today_user_messages(self, telegram_id: int) -> int:
        """统计用户今日提问数（仅 user 角色消息）。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE telegram_id = ? AND role = 'user'
                  AND created_at >= date('now', 'localtime')
                """,
                (telegram_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def recent_messages(
        self, telegram_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """最近对话记录（可按用户过滤，时间倒序）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            if telegram_id is None:
                cursor = await db.execute(
                    """
                    SELECT m.telegram_id, u.username, u.first_name,
                           m.role, m.content, m.model, m.created_at
                    FROM messages m
                    LEFT JOIN users u ON u.telegram_id = m.telegram_id
                    ORDER BY m.id DESC LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT m.telegram_id, u.username, u.first_name,
                           m.role, m.content, m.model, m.created_at
                    FROM messages m
                    LEFT JOIN users u ON u.telegram_id = m.telegram_id
                    WHERE m.telegram_id = ?
                    ORDER BY m.id DESC LIMIT ?
                    """,
                    (telegram_id, limit),
                )
            rows: list[Any] = await cursor.fetchall()
        return [dict(r) for r in rows]
