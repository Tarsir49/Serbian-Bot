"""Пайплайн: голос -> текст -> перевод в обратную сторону -> голос."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .errors import EmptySpeechError
from .language import SERBIAN, detect_by_script, other_language
from .speech import SpeechService
from .translation import Translator, is_unintelligible

logger = logging.getLogger(__name__)

UNCLEAR_AUDIO = (
    "Плохо слышно — не разобрал, что сказано. "
    "Запиши ещё раз поближе к микрофону и потише вокруг 🙏"
)


@dataclass(frozen=True)
class TranslationResult:
    """Готовый ответ пользователю."""

    source_text: str
    translated_text: str
    audio: bytes
    # Язык перевода: "sr" (прислали русский) или "ru" (прислали сербский).
    target_lang: str = SERBIAN


class TranslationPipeline:
    """Связывает распознавание, перевод и синтез."""

    def __init__(self, config: Config, speech: SpeechService, translator: Translator) -> None:
        self._config = config
        self._speech = speech
        self._translator = translator

    async def from_voice(self, audio: bytes, filename: str) -> TranslationResult:
        """Полный цикл для голосового сообщения."""
        transcript = await self._speech.transcribe(audio, filename)
        text = transcript.text.strip()
        if not text:
            raise EmptySpeechError("Не расслышал ни слова. Запиши сообщение ещё раз, пожалуйста")

        if not transcript.is_reliable(
            self._config.stt_min_logprob, self._config.stt_max_no_speech
        ):
            # На плохой записи Whisper выдаёт гладкий, но выдуманный текст. Перевести
            # его — значит уверенно соврать, поэтому лучше признаться, что не расслышали.
            logger.info(
                "Расшифровка отклонена: logprob=%.3f no_speech=%.3f",
                transcript.avg_logprob,
                transcript.no_speech_prob,
            )
            raise EmptySpeechError(UNCLEAR_AUDIO)

        logger.info("Распознано %d символов, язык %s", len(text), transcript.lang)
        return await self._translate(text, transcript.lang)

    async def from_text(self, source_text: str) -> TranslationResult:
        """Перевод и озвучка готового текста; язык определяем по самому тексту."""
        return await self._translate(source_text.strip(), None)

    async def _translate(self, source_text: str, source_lang: str | None) -> TranslationResult:
        if not source_text:
            raise EmptySpeechError("Не понял, что нужно перевести. Попробуй сказать это иначе")

        if source_lang is None:
            source_lang = await self._detect_language(source_text)
        target_lang = other_language(source_lang)

        translated = (await self._translator.translate(source_text, target_lang)).strip()
        if not translated or is_unintelligible(translated):
            raise EmptySpeechError("Не понял, что нужно перевести. Попробуй сказать это иначе")

        logger.info("Направление перевода: %s -> %s", source_lang, target_lang)
        audio = await self._speech.synthesize(translated, target_lang)
        return TranslationResult(
            source_text=source_text,
            translated_text=translated,
            audio=audio,
            target_lang=target_lang,
        )

    async def _detect_language(self, text: str) -> str:
        """Сначала бесплатно по алфавиту, и только для спорных фраз — запросом к модели."""
        by_script = detect_by_script(text)
        if by_script is not None:
            return by_script
        detected = await self._translator.detect_language(text)
        logger.info("Язык определён запросом к модели: %s", detected)
        return detected

    async def aclose(self) -> None:
        await self._speech.aclose()
        await self._translator.aclose()
