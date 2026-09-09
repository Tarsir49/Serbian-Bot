import pytest

from bot.config import Config
from bot.errors import EmptySpeechError
from bot.handlers import build_caption
from bot.pipeline import TranslationPipeline, TranslationResult


class FakeSpeech:
    def __init__(self, transcript="Привет, как дела?"):
        self.transcript = transcript
        self.synthesized: list[str] = []
        self.closed = False

    async def transcribe(self, audio: bytes, filename: str, language: str = "ru") -> str:
        self.audio = audio
        self.filename = filename
        return self.transcript

    async def synthesize(self, text: str) -> bytes:
        self.synthesized.append(text)
        return b"OggS-fake-audio"

    async def aclose(self) -> None:
        self.closed = True


class FakeTranslator:
    def __init__(self, translation="Ćao, kako si?"):
        self.translation = translation
        self.seen: list[str] = []
        self.closed = False

    async def translate(self, text: str) -> str:
        self.seen.append(text)
        return self.translation

    async def aclose(self) -> None:
        self.closed = True


def make_pipeline(speech, translator) -> TranslationPipeline:
    config = Config(telegram_token="t", openai_api_key="k")
    return TranslationPipeline(config=config, speech=speech, translator=translator)


async def test_voice_roundtrip():
    speech, translator = FakeSpeech(), FakeTranslator()
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.source_text == "Привет, как дела?"
    assert result.translated_text == "Ćao, kako si?"
    assert result.audio == b"OggS-fake-audio"
    # Озвучиваем именно перевод, а не оригинал.
    assert speech.synthesized == ["Ćao, kako si?"]
    assert translator.seen == ["Привет, как дела?"]


async def test_empty_transcript_is_reported():
    pipeline = make_pipeline(FakeSpeech(transcript="   "), FakeTranslator())
    with pytest.raises(EmptySpeechError):
        await pipeline.from_voice(b"raw", "voice.ogg")


async def test_unintelligible_translation_is_reported():
    pipeline = make_pipeline(FakeSpeech(), FakeTranslator(translation="???"))
    with pytest.raises(EmptySpeechError):
        await pipeline.from_text("бу-бу-бу")


async def test_aclose_releases_clients():
    speech, translator = FakeSpeech(), FakeTranslator()
    await make_pipeline(speech, translator).aclose()
    assert speech.closed and translator.closed


def test_caption_escapes_and_truncates():
    result = TranslationResult(source_text="а" * 400 + " <b>", translated_text="Ćao", audio=b"")
    caption = build_caption(result, max_source=50)
    assert caption.startswith("🇷🇸 Ćao")
    assert "…" in caption
    assert "<b>" not in caption
