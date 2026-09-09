import pytest

from bot.config import Config
from bot.errors import EmptySpeechError
from bot.handlers import build_caption
from bot.pipeline import TranslationPipeline, TranslationResult
from bot.speech import Transcript


class FakeSpeech:
    def __init__(
        self,
        transcript="Привет, как дела?",
        lang="ru",
        avg_logprob=-0.25,
        no_speech_prob=0.05,
    ):
        self.transcript = transcript
        self.lang = lang
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob
        # Пары (текст, язык): язык важен, от него зависит акцент диктора.
        self.synthesized: list[tuple[str, str]] = []
        self.closed = False

    async def transcribe(self, audio: bytes, filename: str) -> Transcript:
        self.audio = audio
        self.filename = filename
        return Transcript(
            text=self.transcript,
            lang=self.lang,
            avg_logprob=self.avg_logprob,
            no_speech_prob=self.no_speech_prob,
        )

    async def synthesize(self, text: str, lang: str = "sr") -> bytes:
        self.synthesized.append((text, lang))
        return b"OggS-fake-audio"

    async def aclose(self) -> None:
        self.closed = True


class FakeTranslator:
    def __init__(self, translation="Ćao, kako si?", detected="ru"):
        self.translation = translation
        self.detected = detected
        # Пары (текст, язык перевода).
        self.seen: list[tuple[str, str]] = []
        self.detect_calls: list[str] = []
        self.closed = False

    async def translate(self, text: str, target_lang: str) -> str:
        self.seen.append((text, target_lang))
        return self.translation

    async def detect_language(self, text: str) -> str:
        self.detect_calls.append(text)
        return self.detected

    async def aclose(self) -> None:
        self.closed = True


def make_pipeline(speech, translator) -> TranslationPipeline:
    config = Config(telegram_token="t", openai_api_key="k")
    return TranslationPipeline(config=config, speech=speech, translator=translator)


async def test_russian_voice_goes_to_serbian():
    speech, translator = FakeSpeech(), FakeTranslator()
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.source_text == "Привет, как дела?"
    assert result.translated_text == "Ćao, kako si?"
    assert result.target_lang == "sr"
    assert speech.synthesized == [("Ćao, kako si?", "sr")]
    assert translator.seen == [("Привет, как дела?", "sr")]


async def test_serbian_voice_goes_back_to_russian():
    speech = FakeSpeech(transcript="Ćao, kako si?", lang="sr")
    translator = FakeTranslator(translation="Привет, как дела?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "ru"
    # Диктору нужен русский, иначе он читает русский текст с сербским акцентом.
    assert speech.synthesized == [("Привет, как дела?", "ru")]
    assert translator.seen == [("Ćao, kako si?", "ru")]


async def test_language_from_stt_is_trusted_over_the_text():
    # Расшифровка сербская, но распознавание уверенно сказало "sr" — спрашивать модель незачем.
    speech = FakeSpeech(transcript="Добар дан", lang="sr")
    translator = FakeTranslator(translation="Добрый день")
    await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert translator.detect_calls == []
    assert translator.seen == [("Добар дан", "ru")]


async def test_unclear_audio_is_refused_instead_of_translated():
    # Гладкая выдумка по шуму: no_speech выше порога.
    speech = FakeSpeech(avg_logprob=-0.48, no_speech_prob=0.73)
    translator = FakeTranslator()
    with pytest.raises(EmptySpeechError):
        await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    # Ни перевода, ни озвучки — деньги на выдумку не тратим.
    assert translator.seen == []
    assert speech.synthesized == []


async def test_low_confidence_audio_is_refused():
    speech = FakeSpeech(avg_logprob=-0.94, no_speech_prob=0.10)
    with pytest.raises(EmptySpeechError):
        await make_pipeline(speech, FakeTranslator()).from_voice(b"raw", "voice.ogg")


async def test_borderline_confidence_still_passes():
    # Ровно на пороге — пропускаем: настоящая речь на шумной записи выглядит так.
    speech = FakeSpeech(avg_logprob=-0.7, no_speech_prob=0.4)
    result = await make_pipeline(speech, FakeTranslator()).from_voice(b"raw", "voice.ogg")
    assert result.translated_text == "Ćao, kako si?"


async def test_missing_metrics_do_not_block():
    # Модель без verbose_json метрик не даёт — это не повод отказывать.
    speech = FakeSpeech(avg_logprob=None, no_speech_prob=None, lang=None)
    translator = FakeTranslator(detected="ru")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")
    assert result.target_lang == "sr"


async def test_empty_transcript_is_reported():
    pipeline = make_pipeline(FakeSpeech(transcript="   "), FakeTranslator())
    with pytest.raises(EmptySpeechError):
        await pipeline.from_voice(b"raw", "voice.ogg")


async def test_unintelligible_translation_is_reported():
    pipeline = make_pipeline(FakeSpeech(), FakeTranslator(translation="???"))
    with pytest.raises(EmptySpeechError):
        await pipeline.from_text("бу-бу-бу")


async def test_text_language_detected_by_script_without_asking_the_model():
    translator = FakeTranslator(translation="Kako si danas?")
    await make_pipeline(FakeSpeech(), translator).from_text("Привет! Как ты сегодня?")

    # «ы» есть только в русском алфавите — запрос к модели не нужен.
    assert translator.detect_calls == []
    assert translator.seen == [("Привет! Как ты сегодня?", "sr")]


async def test_ambiguous_text_falls_back_to_the_model():
    translator = FakeTranslator(translation="Спасибо", detected="sr")
    await make_pipeline(FakeSpeech(), translator).from_text("Хвала пуно")

    # Общие буквы, примет нет — тут без модели не обойтись.
    assert translator.detect_calls == ["Хвала пуно"]
    assert translator.seen == [("Хвала пуно", "ru")]


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
