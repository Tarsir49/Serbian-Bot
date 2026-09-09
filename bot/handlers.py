"""Хендлеры Telegram: приём голоса и текста, ответ голосом на сербском."""

from __future__ import annotations

import asyncio
import logging
from html import escape
from io import BytesIO
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, Message, TelegramObject
from aiogram.utils.chat_action import ChatActionSender

from .config import Config
from .errors import BotError
from .pipeline import TranslationPipeline, TranslationResult

logger = logging.getLogger(__name__)

router = Router(name="translator")

GREETING = (
    "Привет! Я перевожу русскую речь на сербский.\n\n"
    "🎤 Пришли голосовое сообщение на русском — я отвечу голосовым на сербском.\n"
    "⌨️ Можно и текстом: пришли фразу, получишь перевод и озвучку.\n\n"
    "Перевод разговорный и короткий — как говорят в Сербии."
)

HELP = (
    "Как пользоваться:\n"
    "1. Запиши голосовое на русском (до {duration} сек).\n"
    "2. Подожди несколько секунд.\n"
    "3. Получи голосовое на сербском и его текст.\n\n"
    "Команды:\n"
    "/start — начало\n"
    "/help — эта справка"
)

VOICE_FORBIDDEN_HINT = (
    "🔇 Голосовое отправить не смог: в твоих настройках Telegram они запрещены.\n"
    "Настройки → Конфиденциальность → Голосовые сообщения → «Все», "
    "либо добавь бота в исключения."
)

# Лимит текстового сообщения в Telegram — 4096 символов; берём с запасом на разметку.
TEXT_FALLBACK_LIMIT = 3000

# Пользователи, чьё сообщение сейчас обрабатывается: один запрос за раз.
_busy: set[int] = set()


class AccessMiddleware(BaseMiddleware):
    """Пускает только пользователей из ALLOWED_USER_IDS (если список задан)."""

    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self._allowed = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._allowed:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is not None and user.id in self._allowed:
            return await handler(event, data)

        logger.warning("Отклонён доступ: user_id=%s", getattr(user, "id", None))
        if isinstance(event, Message):
            await event.answer("Извини, у тебя нет доступа к этому боту.")
        return None


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(GREETING)


@router.message(Command("help"))
async def handle_help(message: Message, config: Config) -> None:
    await message.answer(HELP.format(duration=config.max_voice_duration))


@router.message(F.voice | F.audio | F.video_note)
async def handle_voice(
    message: Message,
    bot: Bot,
    config: Config,
    pipeline: TranslationPipeline,
) -> None:
    """Голосовое/аудио на русском -> голосовое на сербском."""
    media = message.voice or message.audio or message.video_note
    duration = getattr(media, "duration", 0) or 0
    if duration > config.max_voice_duration:
        await message.reply(
            f"Слишком длинное сообщение ({duration} сек). "
            f"Максимум — {config.max_voice_duration} сек."
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id in _busy:
        await message.reply("Ещё перевожу предыдущее сообщение, подожди секунду 🙏")
        return

    _busy.add(user_id)
    try:
        buffer = BytesIO()
        await bot.download(media, destination=buffer)
        audio = buffer.getvalue()
        if not audio:
            await message.reply("Не удалось скачать аудио из Telegram. Попробуй ещё раз.")
            return

        filename = _source_filename(message)
        async with ChatActionSender(
            bot=bot, chat_id=message.chat.id, action=ChatAction.RECORD_VOICE
        ):
            result = await pipeline.from_voice(audio, filename)
        await _reply_with_translation(message, result, config)
    except BotError as exc:
        await message.reply(str(exc))
    except asyncio.TimeoutError:
        logger.exception("Таймаут обработки голосового")
        await message.reply("Сервис долго не отвечает. Попробуй ещё раз через минуту.")
    except Exception:
        logger.exception("Не удалось обработать голосовое сообщение")
        await message.reply("Что-то пошло не так. Попробуй ещё раз через минуту.")
    finally:
        _busy.discard(user_id)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(
    message: Message,
    bot: Bot,
    config: Config,
    pipeline: TranslationPipeline,
) -> None:
    """Текст на русском -> голосовое на сербском."""
    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > config.max_text_length:
        await message.reply(
            f"Слишком длинный текст ({len(text)} символов). "
            f"Максимум — {config.max_text_length}."
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id in _busy:
        await message.reply("Ещё перевожу предыдущее сообщение, подожди секунду 🙏")
        return

    _busy.add(user_id)
    try:
        async with ChatActionSender(
            bot=bot, chat_id=message.chat.id, action=ChatAction.RECORD_VOICE
        ):
            result = await pipeline.from_text(text)
        await _reply_with_translation(message, result, config)
    except BotError as exc:
        await message.reply(str(exc))
    except Exception:
        logger.exception("Не удалось обработать текст")
        await message.reply("Что-то пошло не так. Попробуй ещё раз через минуту.")
    finally:
        _busy.discard(user_id)


@router.message()
async def handle_other(message: Message) -> None:
    await message.reply("Пришли голосовое сообщение на русском 🎤 или текст.")


def _source_filename(message: Message) -> str:
    """Имя файла для API распознавания: расширение подсказывает формат."""
    if message.audio and message.audio.file_name:
        return message.audio.file_name
    if message.video_note:
        return "voice.mp4"
    return "voice.ogg"


def build_caption(result: TranslationResult, max_source: int = 300) -> str:
    """Подпись к голосовому: перевод и распознанный оригинал."""
    source = result.source_text.strip()
    if len(source) > max_source:
        source = source[: max_source - 1].rstrip() + "…"
    return f"🇷🇸 {escape(result.translated_text)}\n\n<i>🇷🇺 {escape(source)}</i>"


def is_voice_forbidden(exc: TelegramBadRequest) -> bool:
    """Получатель запретил присылать себе голосовые (настройка приватности Telegram)."""
    return "VOICE_MESSAGES_FORBIDDEN" in str(exc)


def build_text_fallback(result: TranslationResult) -> str:
    """Ответ текстом, когда голосовое отправить нельзя."""
    caption = build_caption(result)
    if len(caption) > TEXT_FALLBACK_LIMIT:
        # Перевод важнее распознанного оригинала: при переполнении оставляем только его.
        text = result.translated_text.strip()[: TEXT_FALLBACK_LIMIT - 1].rstrip()
        caption = f"🇷🇸 {escape(text)}…"
    return f"{caption}\n\n{VOICE_FORBIDDEN_HINT}"


async def _reply_with_translation(
    message: Message, result: TranslationResult, config: Config
) -> None:
    voice = BufferedInputFile(result.audio, filename="prevod.ogg")
    try:
        if not config.send_translation_text:
            await message.reply_voice(voice)
            return

        caption = build_caption(result)
        # Лимит подписи в Telegram — 1024 символа; длинный перевод шлём отдельным сообщением.
        if len(caption) <= 1000:
            await message.reply_voice(voice, caption=caption)
        else:
            await message.reply_voice(voice)
            await message.answer(f"🇷🇸 {escape(result.translated_text)}")
    except TelegramBadRequest as exc:
        if not is_voice_forbidden(exc):
            raise
        # Перевод уже готов и оплачен — отдаём его текстом, а не теряем.
        logger.info("Голосовые запрещены у получателя, отвечаю текстом")
        await message.reply(build_text_fallback(result))
