import pytest

from bot.config import Config
from bot.errors import EmptySpeechError
from bot.handlers import build_caption
from bot.pipeline import TranslationPipeline, TranslationResult
from bot.speech import Hearing, Transcript


class FakeSpeech:
    def __init__(
        self,
        transcript="Привет, как дела?",
        lang="ru",
        avg_logprob=-0.25,
        no_speech_prob=0.05,
        variants=None,
    ):
        self.transcript = transcript
        self.lang = lang
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob
        # {язык прохода: (текст, avg_logprob)} — полноценная пара расшифровок.
        self.variants = variants
        # Пары (текст, язык): язык важен, от него зависит акцент диктора.
        self.synthesized: list[tuple[str, str]] = []
        self.closed = False

    async def transcribe(self, audio: bytes, filename: str) -> Hearing:
        self.audio = audio
        self.filename = filename
        if self.variants is not None:
            return Hearing(
                variants=tuple(
                    Transcript(
                        text=text,
                        lang=lang,
                        avg_logprob=logprob,
                        no_speech_prob=self.no_speech_prob,
                    )
                    for lang, (text, logprob) in self.variants.items()
                )
            )
        return Hearing(
            variants=(
                Transcript(
                    text=self.transcript,
                    lang=self.lang,
                    avg_logprob=self.avg_logprob,
                    no_speech_prob=self.no_speech_prob,
                ),
            )
        )

    async def synthesize(self, text: str, lang: str = "sr") -> bytes:
        self.synthesized.append((text, lang))
        return b"OggS-fake-audio"

    async def aclose(self) -> None:
        self.closed = True


class FakeTranslator:
    def __init__(self, translation="Ćao, kako si?", detected="ru", spoken=None):
        self.translation = translation
        self.detected = detected
        # Что ответит детектор, когда его спросят по паре расшифровок.
        self.spoken = spoken
        # Пары (текст, язык перевода).
        self.seen: list[tuple[str, str]] = []
        self.detect_calls: list[str] = []
        self.pick_calls: list[dict[str, str]] = []
        self.closed = False

    async def translate(self, text: str, target_lang: str) -> str:
        self.seen.append((text, target_lang))
        return self.translation

    async def detect_language(self, text: str) -> str:
        self.detect_calls.append(text)
        return self.detected

    async def pick_spoken_language(self, by_lang: dict[str, str]) -> str:
        self.pick_calls.append(dict(by_lang))
        return self.spoken or self.detected

    async def aclose(self) -> None:
        self.closed = True


def make_pipeline(speech, translator) -> TranslationPipeline:
    config = Config(telegram_token="t", openai_api_key="k")
    return TranslationPipeline(config=config, speech=speech, translator=translator)


async def test_russian_voice_goes_to_serbian():
    speech = FakeSpeech(transcript="Сколько это стоит?")
    translator = FakeTranslator(translation="Koliko to košta?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.source_text == "Сколько это стоит?"
    assert result.translated_text == "Koliko to košta?"
    assert result.target_lang == "sr"
    assert speech.synthesized == [("Koliko to košta?", "sr")]
    assert translator.seen == [("Сколько это стоит?", "sr")]


async def test_serbian_voice_goes_back_to_russian():
    speech = FakeSpeech(transcript="Ćao, kako si?", lang="sr")
    translator = FakeTranslator(translation="Привет, как дела?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "ru"
    # Диктору нужен русский, иначе он читает русский текст с сербским акцентом.
    assert speech.synthesized == [("Привет, как дела?", "ru")]
    assert translator.seen == [("Ćao, kako si?", "ru")]


async def test_winning_pass_does_not_decide_the_language():
    # На чистой записи оба прохода дают один и тот же текст, и победитель по logprob
    # случаен: здесь выиграл сербский проход, хотя речь очевидно русская («ы» в «ты»).
    # Решать должен текст, иначе бот «переводит» русский на русский.
    speech = FakeSpeech(transcript="Привет! Как ты сегодня?", lang="sr")
    translator = FakeTranslator(translation="Ćao! Kako si danas?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "sr"
    assert translator.seen == [("Привет! Как ты сегодня?", "sr")]


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


# --- направление перевода по двум расшифровкам одного аудио ---------------------

# Та самая поломка: сербскую речь русский проход расслышал русскими словами и
# выиграл по уверенности, язык «подтвердился» буквой «я» — и бот перевёл сербский
# на сербский. Побеждать должен язык речи, а не самый самоуверенный проход.
SERBIAN_SPEECH = {
    "ru": ("Я сам добро, хвала на питаню", -0.18),
    "sr": ("Ја сам добро, хвала на питању", -0.31),
}


async def test_serbian_speech_is_not_translated_into_serbian():
    speech = FakeSpeech(variants=SERBIAN_SPEECH)
    translator = FakeTranslator(translation="Я в порядке, спасибо", spoken="sr")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "ru"
    # Источником стала сербская расшифровка, а не победивший русский проход.
    assert result.source_text == "Ја сам добро, хвала на питању"
    assert translator.seen == [("Ја сам добро, хвала на питању", "ru")]
    assert speech.synthesized == [("Я в порядке, спасибо", "ru")]


async def test_both_transcriptions_go_to_the_detector():
    speech = FakeSpeech(variants=SERBIAN_SPEECH)
    translator = FakeTranslator(translation="Я в порядке, спасибо", spoken="sr")
    await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    # Модель судит по паре вариантов: порознь каждый выглядит убедительно.
    assert translator.pick_calls == [
        {
            "ru": "Я сам добро, хвала на питаню",
            "sr": "Ја сам добро, хвала на питању",
        }
    ]
    assert translator.detect_calls == []


async def test_serbian_letters_in_the_russian_pass_decide_for_free():
    # Русскому проходу велели слышать русский, а он выдал ћ — примета против
    # течения, спрашивать модель не о чем.
    speech = FakeSpeech(
        variants={
            "ru": ("Хвала пуно на помоћи", -0.20),
            "sr": ("Hvala puno na pomoći", -0.25),
        }
    )
    translator = FakeTranslator(translation="Большое спасибо за помощь")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "ru"
    assert translator.pick_calls == []
    assert translator.detect_calls == []


async def test_russian_letters_in_the_serbian_pass_decide_for_free():
    speech = FakeSpeech(
        variants={
            "ru": ("Привет! Как ты сегодня?", -0.22),
            "sr": ("Привет, как ты сегодня", -0.30),
        }
    )
    translator = FakeTranslator(translation="Ćao! Kako si danas?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "sr"
    assert translator.pick_calls == []


async def test_identical_transcriptions_need_no_pair_question():
    # Оба прохода услышали одно и то же — спорить не о чем, хватает алфавита.
    speech = FakeSpeech(
        variants={
            "ru": ("Сколько это стоит?", -0.21),
            "sr": ("Сколько это стоит?", -0.24),
        }
    )
    translator = FakeTranslator(translation="Koliko to košta?")
    result = await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    assert result.target_lang == "sr"
    assert translator.pick_calls == []
    assert translator.detect_calls == []


async def test_echo_instead_of_translation_is_refused():
    # Если перевод дословно равен исходнику — это не перевод, и выдавать его
    # за перевод нельзя.
    speech = FakeSpeech(transcript="Dobar dan, kako ste?", lang="sr")
    translator = FakeTranslator(translation="Dobar dan, kako ste?")
    with pytest.raises(EmptySpeechError):
        await make_pipeline(speech, translator).from_voice(b"raw", "voice.ogg")

    # Озвучивать эхо тоже не стали.
    assert speech.synthesized == []
