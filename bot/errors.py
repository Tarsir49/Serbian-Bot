"""Ошибки, которые бот умеет показывать пользователю."""

from __future__ import annotations


class BotError(RuntimeError):
    """Базовая ошибка пайплайна. Текст показывается пользователю."""


class TranscriptionError(BotError):
    """Не удалось распознать речь."""


class TranslationError(BotError):
    """Не удалось получить перевод."""


class SynthesisError(BotError):
    """Не удалось синтезировать речь."""


class EmptySpeechError(BotError):
    """В сообщении не распознано ни одного слова."""
