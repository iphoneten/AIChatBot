"""bot-api 入口：python -m bot 启动（Long Polling）。"""

import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import router
from core.config import get_settings
from core.logging import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging("bot-api")

    if not settings.telegram_bot_token:
        print("错误：未配置 TELEGRAM_BOT_TOKEN，请在 .env 中填写后重试。")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    print("bot-api 已启动，Long Polling 运行中……")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
