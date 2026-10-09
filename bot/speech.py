"""Распознавание (STT) и синтез (TTS) речи через OpenAI Audio API."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import Config
from .errors import SynthesisError, TranscriptionError
from .language import RUSSIAN, SERBIAN
from .prompts import tts_instructions

logger = logging.getLogger(__name__)

# Telegram голосовые сообщения — OGG/Opus; в таком же формате отдаём ответ,
# иначе Telegram не примет его как voice-сообщение.
VOICE_MIME = "audio/ogg"
VOICE_FORMAT = "opus"

# Языки, которые бот слушает: расшифровываем на каждом и берём тот, что лёг лучше.
CANDIDATE_LANGS = (SERBIAN, RUSSIAN)

# Посегментные метрики качества отдаёт только verbose_json, и только у whisper-1.
# У gpt-4o-transcribe его нет, поэтому там остаётся один проход с автоопределением.
VERBOSE_MODELS = frozenset({"whisper-1"})


@dataclass(frozen=True)
class Transcript:
    """Расшифровка и то, насколько модель в ней уверена."""

    text: str
    # None — язык неизвестен (один проход без подсказки), определяем по тексту.
    lang: str | None = None
    avg_logprob: float | None = None
    no_speech_prob: float | None = None

    def is_reliable(self, min_logprob: float, max_no_speech: float) -> bool:
        """Похоже ли это на расслышанную речь, а не на выдумку по шуму."""
        if self.avg_logprob is None or self.no_speech_prob is None:
            return True  # метрик нет — судить не о чем, пропускаем дальше
        return self.avg_logprob >= min_logprob and self.no_speech_prob <= max_no_speech


def _confidence(transcript: "Transcript") -> float:
    return transcript.avg_logprob if transcript.avg_logprob is not None else -99.0


@dataclass(frozen=True)
class Hearing:
    """Все расшифровки одного аудио — по одной на язык-кандидат.

    Варианты не сворачиваются в «лучший» заранее: пока язык речи неизвестен,
    выбирать между ними нечем. Проход, которому велели слышать русский, на
    сербской речи звучит убедительно (русский декодер уверен в себе), поэтому
    решение по logprob систематически заваливается в русский — язык определяет
    пайплайн по обоим вариантам, см. `bot.language`.
    """

    variants: tuple[Transcript, ...]

    @property
    def best(self) -> Transcript:
        """Самый уверенный вариант — для проверки «расслышали ли вообще»."""
        return max(self.variants, key=_confidence)

    @property
    def by_lang(self) -> dict[str, str]:
        """{язык прохода: текст} — только для проходов с известным языком."""
        return {t.lang: t.text for t in self.variants if t.lang and t.text}

    def text_for(self, lang: str) -> str:
        """Расшифровка, сделанная в расчёте на этот язык."""
        return self.by_lang.get(lang) or self.best.text


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

    async def transcribe(self, audio: bytes, filename: str) -> Hearing:
        """Распознаёт речь на каждом языке-кандидате и отдаёт все варианты.

        Автоопределению языка у Whisper доверять нельзя: на плохой записи оно
        уходит в русский и переписывает сербскую речь русскими словами. Поэтому
        расшифровываем дважды с явным языком — а выбор между вариантами делает
        пайплайн, когда определит язык речи.
        """
        if self._config.stt_model in VERBOSE_MODELS:
            return await self._transcribe_variants(audio, filename)
        return Hearing(variants=(await self._transcribe_once(audio, filename),))

    async def _transcribe_variants(self, audio: bytes, filename: str) -> Hearing:
        variants = await asyncio.gather(
            *(self._transcribe_as(audio, filename, lang) for lang in CANDIDATE_LANGS)
        )
        logger.info(
            "Расшифровка: %s",
            ", ".join(
                f"{t.lang}={t.avg_logprob:+.3f}" for t in variants if t.avg_logprob is not None
            ),
        )
        return Hearing(variants=tuple(variants))

    async def _transcribe_as(self, audio: bytes, filename: str, lang: str) -> Transcript:
        import openai

        try:
            result = await self._client.audio.transcriptions.create(
                file=(filename, audio),
                model=self._config.stt_model,
                language=lang,
                response_format="verbose_json",
            )
        except openai.APIError as exc:
            logger.exception("OpenAI: распознавание не удалось (%s)", lang)
            raise TranscriptionError("Не получилось распознать речь, попробуй ещё раз") from exc

        segments = getattr(result, "segments", None) or []
        if not segments:
            return Transcript(text=(result.text or "").strip(), lang=lang)
        return Transcript(
            text=(result.text or "").strip(),
            lang=lang,
            avg_logprob=sum(s.avg_logprob for s in segments) / len(segments),
            # Хватает одного уверенно пустого сегмента, чтобы насторожиться.
            no_speech_prob=max(s.no_speech_prob for s in segments),
        )

    async def _transcribe_once(self, audio: bytes, filename: str) -> Transcript:
        """Один проход с автоопределением: для моделей без verbose_json."""
        import openai

        try:
            result = await self._client.audio.transcriptions.create(
                file=(filename, audio),
                model=self._config.stt_model,
            )
        except openai.APIError as exc:
            logger.exception("OpenAI: распознавание не удалось")
            raise TranscriptionError("Не получилось распознать речь, попробуй ещё раз") from exc

        return Transcript(text=(result.text or "").strip())

    async def synthesize(self, text: str, lang: str = SERBIAN) -> bytes:
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
