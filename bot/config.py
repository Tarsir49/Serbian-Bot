"""Конфигурация бота: читается из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Некорректная или неполная конфигурация."""


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on", "да"}


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть числом, получено: {raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должен быть числом, получено: {raw!r}") from exc


def _get_ids(name: str) -> frozenset[int]:
    raw = _get(name)
    if not raw:
        return frozenset()
    ids = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"{name}: {chunk!r} не является Telegram user id") from exc
    return frozenset(ids)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    openai_api_key: str

    # Какой LLM переводит: "openai" или "anthropic".
    llm_provider: str = "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_effort: str = "low"
    openai_translation_model: str = "gpt-4.1-mini"

    # Речь: распознавание и синтез — через OpenAI Audio API.
    stt_model: str = "whisper-1"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    tts_speed: float = 1.0

    # Порог «я не расслышал»: ниже по уверенности или выше по «тут нет речи» —
    # честно просим перезаписать, а не переводим выдумку.
    stt_min_logprob: float = -0.7
    stt_max_no_speech: float = 0.4

    # Поведение бота.
    serbian_script: str = "latin"  # latin | cyrillic
    send_translation_text: bool = True
    max_voice_duration: int = 180  # секунд
    max_text_length: int = 1500  # символов на входе
    request_timeout: int = 90  # секунд на один вызов API
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    log_level: str = "INFO"

    @property
    def uses_anthropic(self) -> bool:
        return self.llm_provider == "anthropic"


def load_config(env_file: str | None = ".env") -> Config:
    """Собирает конфиг из окружения, подгружая .env, если он есть."""
    if env_file:
        load_dotenv(env_file, override=False)

    telegram_token = _get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ConfigError("Не задан TELEGRAM_BOT_TOKEN")

    # Ключ OpenAI нужен всегда: распознавание и синтез речи идут через OpenAI Audio API.
    openai_api_key = _get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ConfigError("Не задан OPENAI_API_KEY (нужен для распознавания и синтеза речи)")

    provider = _get("LLM_PROVIDER", "openai").lower()
    if provider not in {"openai", "anthropic"}:
        raise ConfigError(f"LLM_PROVIDER должен быть 'openai' или 'anthropic', получено: {provider!r}")

    anthropic_api_key = _get("ANTHROPIC_API_KEY")
    if provider == "anthropic" and not anthropic_api_key:
        raise ConfigError("LLM_PROVIDER=anthropic, но не задан ANTHROPIC_API_KEY")

    script = _get("SERBIAN_SCRIPT", "latin").lower()
    if script not in {"latin", "cyrillic"}:
        raise ConfigError(f"SERBIAN_SCRIPT должен быть 'latin' или 'cyrillic', получено: {script!r}")

    speed_raw = _get("TTS_SPEED", "1.0")
    try:
        tts_speed = float(speed_raw)
    except ValueError as exc:
        raise ConfigError(f"TTS_SPEED должен быть числом, получено: {speed_raw!r}") from exc
    if not 0.25 <= tts_speed <= 4.0:
        raise ConfigError("TTS_SPEED должен быть в диапазоне 0.25–4.0")

    return Config(
        telegram_token=telegram_token,
        openai_api_key=openai_api_key,
        llm_provider=provider,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=_get("ANTHROPIC_MODEL", "claude-opus-5"),
        anthropic_effort=_get("ANTHROPIC_EFFORT", "low").lower(),
        openai_translation_model=_get("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini"),
        stt_model=_get("STT_MODEL", "whisper-1"),
        stt_min_logprob=_get_float("STT_MIN_LOGPROB", -0.7),
        stt_max_no_speech=_get_float("STT_MAX_NO_SPEECH", 0.4),
        tts_model=_get("TTS_MODEL", "gpt-4o-mini-tts"),
        tts_voice=_get("TTS_VOICE", "alloy"),
        tts_speed=tts_speed,
        serbian_script=script,
        send_translation_text=_get_bool("SEND_TRANSLATION_TEXT", True),
        max_voice_duration=_get_int("MAX_VOICE_DURATION", 180),
        max_text_length=_get_int("MAX_TEXT_LENGTH", 1500),
        request_timeout=_get_int("REQUEST_TIMEOUT", 90),
        allowed_user_ids=_get_ids("ALLOWED_USER_IDS"),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
    )
