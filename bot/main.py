"""Точка входа: сборка зависимостей и long-polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import Config, ConfigError, load_config
from .handlers import AccessMiddleware, router
from .pipeline import TranslationPipeline
from .speech import SpeechService
from .translation import build_translator

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="help", description="Как пользоваться"),
]


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # aiohttp-логи поллинга слишком шумные на DEBUG.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_pipeline(config: Config) -> TranslationPipeline:
    return TranslationPipeline(
        config=config,
        speech=SpeechService(config),
        translator=build_translator(config),
    )


async def run(config: Config) -> None:
    bot = Bot(
        token=config.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    pipeline = build_pipeline(config)

    dispatcher = Dispatcher()
    dispatcher["config"] = config
    dispatcher["pipeline"] = pipeline
    router.message.middleware(AccessMiddleware(config.allowed_user_ids))
    dispatcher.include_router(router)

    try:
        me = await bot.get_me()
        logger.info("Запущен бот @%s (провайдер перевода: %s)", me.username, config.llm_provider)
        await bot.set_my_commands(COMMANDS)
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await pipeline.aclose()
        await bot.session.close()


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    setup_logging(config.log_level)
    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
