"""Перевод между русским и сербским через LLM (OpenAI или Anthropic)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from .config import Config
from .errors import TranslationError
from .prompts import LANG_TAG, UNINTELLIGIBLE_MARKER, translation_system_prompt

logger = logging.getLogger(__name__)

# Направление по умолчанию, если модель забыла метку: исходный сценарий — русский на сербский.
DEFAULT_TARGET_LANG = "sr"

_LABEL_RE = re.compile(
    r"^\s*(prevod na srpski|prevod na ruski|prevod|перевод на сербский|перевод на русский"
    r"|перевод|translation)\s*[:\-–]\s*",
    re.IGNORECASE,
)
_LANG_RE = re.compile(rf"^\s*{LANG_TAG}\s*[:\-]\s*(ru|sr)\b[^\S\n]*\n?", re.IGNORECASE)
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


@dataclass(frozen=True)
class Translation:
    """Перевод и язык, на который он сделан."""

    text: str
    target_lang: str = DEFAULT_TARGET_LANG


def parse_translation(raw: str) -> Translation:
    """Отделяет метку направления от текста и чистит текст."""
    text = raw.strip()
    match = _LANG_RE.match(text)
    if not match:
        # Метки нет — считаем, что перевели на сербский: так вёл себя бот до двух направлений.
        return Translation(text=clean_translation(text))
    return Translation(
        text=clean_translation(text[match.end() :]),
        target_lang=match.group(1).lower(),
    )


class Translator(Protocol):
    """Общий интерфейс переводчика."""

    async def translate(self, text: str) -> Translation: ...

    async def aclose(self) -> None: ...


class OpenAITranslator:
    """Перевод через Chat Completions OpenAI."""

    def __init__(self, config: Config) -> None:
        from openai import AsyncOpenAI

        self._model = config.openai_translation_model
        self._system_prompt = translation_system_prompt(config.serbian_script)
        self._client = AsyncOpenAI(
            api_key=config.openai_api_key,
            timeout=config.request_timeout,
            max_retries=2,
        )

    async def translate(self, text: str) -> Translation:
        import openai

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
                ],
            )
        except openai.APIError as exc:
            logger.exception("OpenAI: перевод не удался")
            raise TranslationError("Сервис перевода недоступен, попробуй ещё раз") from exc

        content = response.choices[0].message.content or ""
        return parse_translation(content)

    async def aclose(self) -> None:
        await self._client.close()


class AnthropicTranslator:
    """Перевод через Messages API Anthropic."""

    def __init__(self, config: Config) -> None:
        from anthropic import AsyncAnthropic

        self._model = config.anthropic_model
        self._effort = config.anthropic_effort
        self._system_prompt = translation_system_prompt(config.serbian_script)
        self._client = AsyncAnthropic(
            api_key=config.anthropic_api_key,
            timeout=float(config.request_timeout),
            max_retries=2,
        )

    async def translate(self, text: str) -> Translation:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                # Перевод реплики — простая задача: минимальные «раздумья» ради скорости и цены.
                output_config={"effort": self._effort},
                system=self._system_prompt,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIError as exc:
            logger.exception("Anthropic: перевод не удался")
            raise TranslationError("Сервис перевода недоступен, попробуй ещё раз") from exc

        if response.stop_reason == "refusal":
            raise TranslationError("Модель отказалась переводить это сообщение")

        parts = [block.text for block in response.content if block.type == "text"]
        return parse_translation("".join(parts))

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
