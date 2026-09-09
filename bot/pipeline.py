"""Пайплайн: голос -> текст -> перевод в обратную сторону -> голос."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .errors import EmptySpeechError
from .speech import SpeechService
from .translation import DEFAULT_TARGET_LANG, Translator, is_unintelligible

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationResult:
    """Готовый ответ пользователю."""

    source_text: str
    translated_text: str
    audio: bytes
    # Язык перевода: "sr" (прислали русский) или "ru" (прислали сербский).
    target_lang: str = DEFAULT_TARGET_LANG


class TranslationPipeline:
    """Связывает распознавание, перевод и синтез."""

    def __init__(self, config: Config, speech: SpeechService, translator: Translator) -> None:
        self._config = config
        self._speech = speech
        self._translator = translator

    async def from_voice(self, audio: bytes, filename: str) -> TranslationResult:
        """Полный цикл для голосового сообщения."""
        source_text = (await self._speech.transcribe(audio, filename)).strip()
        if not source_text:
            raise EmptySpeechError("Не расслышал ни слова. Запиши сообщение ещё раз, пожалуйста")
        logger.info("Распознано %d символов", len(source_text))
        return await self.from_text(source_text)

    async def from_text(self, source_text: str) -> TranslationResult:
        """Перевод и озвучка готового текста; направление выбирает переводчик."""
        source_text = source_text.strip()
        translation = await self._translator.translate(source_text)
        translated = translation.text.strip()
        if not translated or is_unintelligible(translated):
            raise EmptySpeechError("Не понял, что нужно перевести. Попробуй сказать это иначе")

        logger.info("Направление перевода: -> %s", translation.target_lang)
        audio = await self._speech.synthesize(translated, translation.target_lang)
        return TranslationResult(
            source_text=source_text,
            translated_text=translated,
            audio=audio,
            target_lang=translation.target_lang,
        )

    async def aclose(self) -> None:
        await self._speech.aclose()
        await self._translator.aclose()
