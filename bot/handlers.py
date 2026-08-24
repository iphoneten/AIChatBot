"""Telegram 命令与消息处理器。"""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.agent_api import AgentClient
from core.config import get_settings

router = Router(name="main")

HELP_TEXT = (
    "可用命令：\n"
    "/start - 开始使用\n"
    "/help - 显示本帮助\n"
    "/new - 开启新对话（清空上下文）\n"
    "/model - 查看可用模型；/model 名称 - 切换模型\n\n"
    "直接发送文字即可与我对话，我会记住本次对话的上下文。"
)


def _client() -> AgentClient:
    """构造 agent 内部 API 客户端。"""
    settings = get_settings()
    return AgentClient(settings.agent_base_url, settings.agent_internal_token)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """注册用户并发送欢迎语。"""
    user = message.from_user
    async with _client() as client:
        await client.register(user.id, user.username, user.first_name)
    await message.answer(
        f"你好，<b>{user.first_name}</b>！我是 AI 助手。\n\n{HELP_TEXT}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    """清空会话上下文，开启新对话。"""
    async with _client() as client:
        ok = await client.clear_session(message.from_user.id, message.chat.id)
    if ok:
        await message.answer("已开启新对话，之前的上下文已清空。")
    else:
        await message.answer("操作失败，请稍后重试。")


@router.message(Command("model"))
async def cmd_model(message: Message) -> None:
    """查看或切换模型：/model 列出；/model 名称 切换。"""
    arg = (message.text or "").removeprefix("/model").strip()
    async with _client() as client:
        if not arg:
            models = await client.get_models()
            current = await client.get_current_model(message.from_user.id)
            if not models:
                await message.answer("无法获取模型列表，请检查 AI 服务是否在运行。")
                return
            listing = "\n".join(f"• <code>{m}</code>" for m in models)
            await message.answer(
                f"当前模型：<b>{current or '未知'}</b>\n可用模型：\n{listing}\n\n切换示例：<code>/model gpt-5.5</code>"
            )
        else:
            _, tip = await client.select_model(message.from_user.id, arg)
            await message.answer(tip)


@router.message(F.text)
async def on_text(message: Message) -> None:
    """普通文本消息 → 经 ai-agent 调用大模型并回复。"""
    # 打字状态为尽力而为：失败不阻塞对话
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception as e:  # noqa: BLE001 - 状态提示失败仅记录日志
        logging.getLogger(__name__).warning(f"发送 typing 状态失败：{e}")
    user = message.from_user
    async with _client() as client:
        reply = await client.chat(
            telegram_id=user.id,
            chat_id=message.chat.id,
            text=message.text or "",
            username=user.username,
            first_name=user.first_name,
        )
    if reply:
        for i in range(0, len(reply), 4000):  # Telegram 上限 4096 字符
            await message.answer(reply[i : i + 4000])
    else:
        await message.answer("抱歉，AI 服务暂时不可用，请稍后重试。")
