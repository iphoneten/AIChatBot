"""bot-api 入口：python -m bot 启动（Long Polling）。"""

import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent

from bot.handlers import router
from core.config import get_settings
from core.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    logger = setup_logging("bot-api")

    if not settings.telegram_bot_token:
        print("错误：未配置 TELEGRAM_BOT_TOKEN，请在 .env 中填写后重试。")
        sys.exit(1)

    # 配置了代理时经代理访问 Telegram API（网络受限环境必需）
    session = (
        AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    )
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> bool:
        """全局异常兜底：记录日志并尽力通知用户，避免静默失败。"""
        update = event.update
        logger.exception(f"处理更新时发生未捕获异常：{event.exception}")
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg is not None:
            try:
                await msg.answer("抱歉，处理消息时出现内部错误，请稍后重试。")
            except Exception as notify_err:  # noqa: BLE001 - 通知失败时仅保留日志
                logger.warning(f"错误提示发送失败：{notify_err}")
        return True

    await bot.delete_webhook(drop_pending_updates=True)

    # 注册 Telegram 命令菜单（输入框左侧菜单按钮）
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="开始使用"),
            BotCommand(command="new", description="开启新对话（清空上下文）"),
            BotCommand(command="model", description="查看/切换模型"),
            BotCommand(command="help", description="显示帮助"),
        ]
    )
    logger.info("命令菜单已注册")

    logger.info("bot-api 已启动，Long Polling 运行中……")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("bot-api 已停止")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
