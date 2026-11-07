"""
Telegram Bot — minimal bot for Mini App entry point.
Handles /start (with optional referral deep link).
Sends the Mini App launch button to users.
Runs as asyncio background task inside the FastAPI process.
"""
import logging
import re

from app.core.config import settings

logger = logging.getLogger(__name__)


async def start_bot():
    """
    Start the Telegram bot using aiogram.
    Registered as an asyncio background task in app lifespan.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return

    try:
        from aiogram import Bot, Dispatcher, Router
        from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        from aiogram.filters import CommandStart, CommandObject

        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        dp = Dispatcher()
        router = Router()

        @router.message(CommandStart())
        async def cmd_start(message: Message, command: CommandObject):
            """
            /start handler.
            Deep link format: /start VS-XXXXXXX (referral code)
            Opens the Mini App with the referral code passed as start_param.
            """
            mini_app_url = settings.mini_app_url
            if not mini_app_url:
                logger.error("MINI_APP_URL is not set (and ALLOWED_ORIGINS has no https origin)")
                await message.answer("⚠️ App এখনো চালু করা হয়নি। কিছুক্ষণ পর আবার চেষ্টা করুন।")
                return

            # Referral deep link: /start VS-XXXXXXX. Only a well-formed code is forwarded
            # (the frontend sends it to the backend at login — a web_app button launch
            # does not put it into Telegram's initData).
            start_param = (command.args or "").strip()
            if re.fullmatch(r"VS-[A-Z0-9]{7}", start_param):
                mini_app_url_with_param = f"{mini_app_url}/?startapp={start_param}"
            else:
                mini_app_url_with_param = mini_app_url

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🎬 Video Store খুলুন",
                    web_app=WebAppInfo(url=mini_app_url_with_param),
                )
            ]])

            await message.answer(
                "👋 Video Store-এ স্বাগতম!\n\n"
                "🎬 হাজারো ভিডিও কিনুন বা বিনামূল্যে দেখুন।\n"
                "📦 সেরা Package অফার উপভোগ করুন।\n\n"
                "নিচের বোতাম চাপুন:",
                reply_markup=keyboard,
            )

        dp.include_router(router)

        # Start polling
        logger.info("Telegram Bot polling started")
        await dp.start_polling(bot, allowed_updates=["message"])

    except ImportError:
        logger.warning("aiogram not installed — bot disabled")
    except Exception as e:
        logger.error(f"Bot error: {e}")
