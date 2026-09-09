import pytest

from bot.config import Config
from bot.errors import EmptySpeechError
from bot.handlers import build_caption
from bot.pipeline import TranslationPipeline, TranslationResult
from bot.translation import Translation


class FakeSpeech:
    def __init__(self, transcript="Привет, как дела?"):
        self.transcript = transcript
        # Пары (текст, язык): язык важен, от него зависит акцент диктора.
        self.synthesized: list[tuple[str, str]] = []
        self.closed = False

    async def transcribe(
        self, audio: bytes, filename: str, language: str | None = None
    ) -> str:
        self.audio = audio
        self.filename = filename
        self.language = language
        return self.transcript

    async def synthesize(self, text: str, lang: str = "sr") -> bytes:
        self.synthesized.append((text, lang))
        return b"OggS-fake-audio"

    async def aclose(self) -> None:
        self.closed = True


class FakeTranslator:
    def __init__(self, translation="Ćao, kako si?", target_lang="sr"):
        self.translation = translation
        self.target_lang = target_lang
        self.seen: list[str] = []
        self.closed = False

    async def translate(self, text: str) -> Translation:
        self.seen.append(text)
        return Translation(text=self.translation, target_lang=self.target_lang)

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
    assert result.target_lang == "sr"
    # Озвучиваем именно перевод, а не оригинал.
    assert speech.synthesized == [("Ćao, kako si?", "sr")]
    assert translator.seen == ["Привет, как дела?"]


async def test_serbian_voice_is_translated_back_to_russian():
    speech = FakeSpeech(transcript="Ćao, kako si?")
    translator = FakeTranslator(translation="Привет, как дела?", target_lang="ru")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.translated_text == "Привет, как дела?"
    assert result.target_lang == "ru"
    # Диктору нужен русский, иначе он читает русский текст с сербским акцентом.
    assert speech.synthesized == [("Привет, как дела?", "ru")]


async def test_transcription_language_is_not_forced():
    speech, translator = FakeSpeech(), FakeTranslator()
    await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    # Подсказка языка заставила бы модель слышать сербский как русский.
    assert speech.language is None


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
