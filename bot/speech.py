"""Распознавание (STT) и синтез (TTS) речи через OpenAI Audio API."""

from __future__ import annotations

import logging

from .config import Config
from .errors import SynthesisError, TranscriptionError
from .prompts import tts_instructions

logger = logging.getLogger(__name__)

# Telegram голосовые сообщения — OGG/Opus; в таком же формате отдаём ответ,
# иначе Telegram не примет его как voice-сообщение.
VOICE_MIME = "audio/ogg"
VOICE_FORMAT = "opus"


class SpeechService:
    """Обёртка над OpenAI: аудио -> текст и текст -> аудио."""

    def __init__(self, config: Config) -> None:
        from openai import AsyncOpenAI

        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.openai_api_key,
            timeout=config.request_timeout,
            max_retries=2,
        )

    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str:
        """Распознаёт речь в аудио и возвращает текст.

        Язык по умолчанию не подсказываем: бот принимает и русский, и сербский,
        а жёсткая подсказка заставляет модель слышать чужую речь как свою.
        """
        import openai

        params: dict[str, object] = {
            "file": (filename, audio),
            "model": self._config.stt_model,
        }
        if language:
            params["language"] = language

        try:
            result = await self._client.audio.transcriptions.create(**params)
        except openai.APIError as exc:
            logger.exception("OpenAI: распознавание не удалось")
            raise TranscriptionError("Не получилось распознать речь, попробуй ещё раз") from exc

        return (result.text or "").strip()

    async def synthesize(self, text: str, lang: str = "sr") -> bytes:
        """Озвучивает текст на указанном языке и возвращает OGG/Opus для send_voice."""
        import openai

        params: dict[str, object] = {
            "model": self._config.tts_model,
            "voice": self._config.tts_voice,
            "input": text,
            "response_format": VOICE_FORMAT,
        }
        # instructions понимают только модели поколения gpt-4o-*-tts,
        # а speed — только классические tts-1/tts-1-hd.
        if self._config.tts_model.startswith("gpt-"):
            params["instructions"] = tts_instructions(lang)
        elif self._config.tts_speed != 1.0:
            params["speed"] = self._config.tts_speed

        try:
            async with self._client.audio.speech.with_streaming_response.create(**params) as response:
                audio = await response.read()
        except openai.APIError as exc:
            logger.exception("OpenAI: синтез речи не удался")
            raise SynthesisError("Не получилось озвучить перевод, попробуй ещё раз") from exc

        if not audio:
            raise SynthesisError("Сервис синтеза вернул пустое аудио")
        return audio

    async def aclose(self) -> None:
        await self._client.close()
