"""Перевод между русским и сербским через LLM (OpenAI или Anthropic)."""

from __future__ import annotations

import logging
import re
from typing import Protocol

from .config import Config
from .errors import TranslationError
from .language import RUSSIAN, SERBIAN
from .prompts import (
    LANGUAGE_DETECTION_PROMPT,
    UNINTELLIGIBLE_MARKER,
    translation_system_prompt,
)

logger = logging.getLogger(__name__)

# Куда падаем, если детекция не сработала: исходный сценарий бота — русский на сербский.
FALLBACK_SOURCE_LANG = RUSSIAN

_LABEL_RE = re.compile(
    r"^\s*(prevod na srpski|prevod na ruski|prevod|перевод на сербский|перевод на русский"
    r"|перевод|translation)\s*[:\-–]\s*",
    re.IGNORECASE,
)
_QUOTE_PAIRS = (("«", "»"), ('"', '"'), ("“", "”"), ("'", "'"), ("`", "`"))


def clean_translation(raw: str) -> str:
    """Убирает обёртку, которую LLM иногда добавляет вопреки инструкции."""
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    text = _LABEL_RE.sub("", text).strip()
    for opening, closing in _QUOTE_PAIRS:
        if len(text) > 1 and text.startswith(opening) and text.endswith(closing):
            text = text[len(opening) : -len(closing)].strip()
            break
    return text


def parse_language(raw: str) -> str:
    """Ответ детектора -> код языка; всё непонятное считаем русским."""
    answer = raw.strip().lower()
    # Промпт просит ровно "ru" или "sr", но модель может ответить и словом.
    serbian = any(m in answer for m in ("sr", "serb", "срп", "серб"))
    russian = any(m in answer for m in ("ru", "russ", "рус"))
    if serbian and not russian:
        return SERBIAN
    if russian and not serbian:
        return RUSSIAN
    logger.warning("Детектор языка ответил непонятно: %r", raw[:40])
    return FALLBACK_SOURCE_LANG


class Translator(Protocol):
    """Общий интерфейс переводчика."""

    async def translate(self, text: str, target_lang: str) -> str: ...

    async def detect_language(self, text: str) -> str: ...

    async def aclose(self) -> None: ...


class OpenAITranslator:
    """Перевод через Chat Completions OpenAI."""

    def __init__(self, config: Config) -> None:
        from openai import AsyncOpenAI

        self._model = config.openai_translation_model
        self._prompts = {
            lang: translation_system_prompt(config.serbian_script, lang)
            for lang in (RUSSIAN, SERBIAN)
        }
        self._client = AsyncOpenAI(
            api_key=config.openai_api_key,
            timeout=config.request_timeout,
            max_retries=2,
        )

    async def _ask(self, system: str, text: str) -> str:
        import openai

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
            )
        except openai.APIError as exc:
            logger.exception("OpenAI: запрос не удался")
            raise TranslationError("Сервис перевода недоступен, попробуй ещё раз") from exc

        return response.choices[0].message.content or ""

    async def translate(self, text: str, target_lang: str) -> str:
        return clean_translation(await self._ask(self._prompts[target_lang], text))

    async def detect_language(self, text: str) -> str:
        return parse_language(await self._ask(LANGUAGE_DETECTION_PROMPT, text))

    async def aclose(self) -> None:
        await self._client.close()


class AnthropicTranslator:
    """Перевод через Messages API Anthropic."""

    def __init__(self, config: Config) -> None:
        from anthropic import AsyncAnthropic

        self._model = config.anthropic_model
        self._effort = config.anthropic_effort
        self._prompts = {
            lang: translation_system_prompt(config.serbian_script, lang)
            for lang in (RUSSIAN, SERBIAN)
        }
        self._client = AsyncAnthropic(
            api_key=config.anthropic_api_key,
            timeout=float(config.request_timeout),
            max_retries=2,
        )

    async def _ask(self, system: str, text: str) -> str:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                # Перевод реплики — простая задача: минимальные «раздумья» ради скорости и цены.
                output_config={"effort": self._effort},
                system=system,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIError as exc:
            logger.exception("Anthropic: запрос не удался")
            raise TranslationError("Сервис перевода недоступен, попробуй ещё раз") from exc

        if response.stop_reason == "refusal":
            raise TranslationError("Модель отказалась переводить это сообщение")

        return "".join(block.text for block in response.content if block.type == "text")

    async def translate(self, text: str, target_lang: str) -> str:
        return clean_translation(await self._ask(self._prompts[target_lang], text))

    async def detect_language(self, text: str) -> str:
        return parse_language(await self._ask(LANGUAGE_DETECTION_PROMPT, text))

    async def aclose(self) -> None:
        await self._client.close()


def build_translator(config: Config) -> Translator:
    """Создаёт переводчика, выбранного в LLM_PROVIDER."""
    if config.uses_anthropic:
        logger.info("Переводчик: Anthropic (%s)", config.anthropic_model)
        return AnthropicTranslator(config)
    logger.info("Переводчик: OpenAI (%s)", config.openai_translation_model)
    return OpenAITranslator(config)


def is_unintelligible(translation: str) -> bool:
    """Модель сообщила, что переводить нечего."""
    return translation.strip().strip(".") == UNINTELLIGIBLE_MARKER
