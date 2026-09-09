import pytest

from bot.config import ConfigError, load_config


def _env(monkeypatch, **overrides):
    base = {
        "TELEGRAM_BOT_TOKEN": "123:ABC",
        "OPENAI_API_KEY": "sk-test",
    }
    base.update(overrides)
    for key in (
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "SERBIAN_SCRIPT",
        "ALLOWED_USER_IDS",
        "SEND_TRANSLATION_TEXT",
        "MAX_VOICE_DURATION",
        "TTS_SPEED",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in base.items():
        monkeypatch.setenv(key, value)


def test_defaults(monkeypatch):
    _env(monkeypatch)
    config = load_config(env_file=None)
    assert config.llm_provider == "openai"
    assert config.uses_anthropic is False
    assert config.serbian_script == "latin"
    assert config.send_translation_text is True
    assert config.allowed_user_ids == frozenset()


def test_missing_telegram_token(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(env_file=None)


def test_openai_key_required_even_with_anthropic(monkeypatch):
    _env(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant")
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_config(env_file=None)


def test_anthropic_requires_its_key(monkeypatch):
    _env(monkeypatch, LLM_PROVIDER="anthropic")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config(env_file=None)


def test_anthropic_provider(monkeypatch):
    _env(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant")
    config = load_config(env_file=None)
    assert config.uses_anthropic is True
    assert config.anthropic_model == "claude-opus-5"


def test_unknown_provider(monkeypatch):
    _env(monkeypatch, LLM_PROVIDER="mistral")
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        load_config(env_file=None)


def test_allowed_user_ids(monkeypatch):
    _env(monkeypatch, ALLOWED_USER_IDS="111, 222;333")
    assert load_config(env_file=None).allowed_user_ids == frozenset({111, 222, 333})


def test_bad_user_id(monkeypatch):
    _env(monkeypatch, ALLOWED_USER_IDS="111,вася")
    with pytest.raises(ConfigError):
        load_config(env_file=None)


def test_script_validation(monkeypatch):
    _env(monkeypatch, SERBIAN_SCRIPT="glagolitic")
    with pytest.raises(ConfigError, match="SERBIAN_SCRIPT"):
        load_config(env_file=None)


def test_tts_speed_range(monkeypatch):
    _env(monkeypatch, TTS_SPEED="9")
    with pytest.raises(ConfigError, match="TTS_SPEED"):
        load_config(env_file=None)
