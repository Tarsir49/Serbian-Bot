import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.config import Config
from bot.handlers import (
    VOICE_FORBIDDEN_HINT,
    _reply_with_translation,
    build_text_fallback,
    is_voice_forbidden,
)
from bot.pipeline import TranslationResult


def bad_request(description: str) -> TelegramBadRequest:
    """Ошибка в том же виде, в каком её отдаёт aiogram при ответе Telegram."""
    return TelegramBadRequest(method=object(), message=description)


class FakeMessage:
    """Сообщение, которое запоминает отправленное вместо похода в Telegram."""

    def __init__(self, voice_error: Exception | None = None):
        self.voice_error = voice_error
        self.voices: list[tuple[object, str | None]] = []
        self.replies: list[str] = []
        self.answers: list[str] = []

    async def reply_voice(self, voice, caption: str | None = None) -> None:
        if self.voice_error is not None:
            raise self.voice_error
        self.voices.append((voice, caption))

    async def reply(self, text: str) -> None:
        self.replies.append(text)

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def make_config(send_translation_text: bool = True) -> Config:
    return Config(
        telegram_token="t",
        openai_api_key="k",
        send_translation_text=send_translation_text,
    )


def make_result(translated: str = "Ćao, kako si?") -> TranslationResult:
    return TranslationResult(
        source_text="Привет, как дела?", translated_text=translated, audio=b"OggS"
    )


def test_voice_forbidden_is_recognised():
    assert is_voice_forbidden(bad_request("Bad Request: VOICE_MESSAGES_FORBIDDEN"))


def test_other_bad_requests_are_not_voice_forbidden():
    assert not is_voice_forbidden(bad_request("Bad Request: message is too long"))


def test_text_fallback_keeps_translation_and_explains():
    fallback = build_text_fallback(make_result())
    assert "Ćao, kako si?" in fallback
    assert VOICE_FORBIDDEN_HINT in fallback


def test_text_fallback_trims_overlong_translation():
    fallback = build_text_fallback(make_result(translated="a" * 5000))
    # Оригинал отбрасываем, перевод режем, подсказка остаётся на месте.
    assert len(fallback) < 4096
    assert "🇷🇺" not in fallback
    assert fallback.endswith(VOICE_FORBIDDEN_HINT)


async def test_voice_sent_normally_when_allowed():
    message = FakeMessage()
    await _reply_with_translation(message, make_result(), make_config())

    assert len(message.voices) == 1
    assert not message.replies


async def test_falls_back_to_text_when_voice_forbidden():
    message = FakeMessage(
        voice_error=bad_request("Bad Request: VOICE_MESSAGES_FORBIDDEN")
    )
    await _reply_with_translation(message, make_result(), make_config())

    # Голосовое не ушло, но перевод пользователь всё равно получил.
    assert not message.voices
    assert len(message.replies) == 1
    assert "Ćao, kako si?" in message.replies[0]
    assert VOICE_FORBIDDEN_HINT in message.replies[0]


async def test_falls_back_even_without_translation_text():
    message = FakeMessage(
        voice_error=bad_request("Bad Request: VOICE_MESSAGES_FORBIDDEN")
    )
    await _reply_with_translation(
        message, make_result(), make_config(send_translation_text=False)
    )

    # SEND_TRANSLATION_TEXT=false отключает подпись, но не право на запасной ответ.
    assert "Ćao, kako si?" in message.replies[0]


async def test_other_errors_are_not_swallowed():
    message = FakeMessage(voice_error=bad_request("Bad Request: chat not found"))
    with pytest.raises(TelegramBadRequest):
        await _reply_with_translation(message, make_result(), make_config())

    assert not message.replies
