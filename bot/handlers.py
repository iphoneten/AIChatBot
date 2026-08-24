"""Telegram 命令与消息处理器。"""

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
    "/new - 开启新对话（清空上下文）\n\n"
    "直接发送文字即可与我对话。"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """注册用户并发送欢迎语。"""
    await message.answer(
        f"你好，<b>{message.from_user.first_name}</b>！我是 AI 助手。\n\n{HELP_TEXT}"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    """清空会话上下文（M3 接入 agent 后实现）。"""
    await message.answer("已开启新对话。（上下文清理将在后续版本接入）")


@router.message(F.text)
async def on_text(message: Message) -> None:
    """普通文本消息 → 经 ai-agent 调用大模型并回复。"""
    settings = get_settings()
    async with AgentClient(settings.agent_base_url) as client:
        reply = await client.chat(
            telegram_id=message.from_user.id,
            chat_id=message.chat.id,
            text=message.text,
        )
    if reply:
        await message.answer(reply)
    else:
        await message.answer("抱歉，AI 服务暂时不可用，请稍后重试。")
