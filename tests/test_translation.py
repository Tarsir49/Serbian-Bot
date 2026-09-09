import pytest

from bot.prompts import translation_system_prompt, tts_instructions
from bot.translation import clean_translation, is_unintelligible, parse_language


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ćao, kako si?", "Ćao, kako si?"),
        ("  Ćao!  ", "Ćao!"),
        ('"Ćao, kako si?"', "Ćao, kako si?"),
        ("«Ćao»", "Ćao"),
        ("Prevod: Ćao", "Ćao"),
        ("Перевод: Ćao", "Ćao"),
        ("Перевод на русский: Привет", "Привет"),
        ("```\nĆao\n```", "Ćao"),
        ("Dobar dan. Kako ste?", "Dobar dan. Kako ste?"),
    ],
)
def test_clean_translation(raw, expected):
    assert clean_translation(raw) == expected


def test_clean_keeps_inner_quotes():
    assert clean_translation('On je rekao "zdravo" i otišao.') == 'On je rekao "zdravo" i otišao.'


def test_unintelligible_marker():
    assert is_unintelligible("???")
    assert is_unintelligible(" ???. ")
    assert not is_unintelligible("Šta?")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sr", "sr"),
        ("ru", "ru"),
        ("  SR\n", "sr"),
        ("RU.", "ru"),
        # Промпт просит код, но модель иногда отвечает словом.
        ("Serbian", "sr"),
        ("Russian", "ru"),
    ],
)
def test_parse_language(raw, expected):
    assert parse_language(raw) == expected


@pytest.mark.parametrize("raw", ["", "не знаю", "ru or sr", "оба"])
def test_unparsable_answer_falls_back_to_russian(raw):
    # Падаем в исходный сценарий бота: русский на входе, сербский на выходе.
    assert parse_language(raw) == "ru"


def test_translation_prompt_is_one_directional():
    to_serbian = translation_system_prompt("latin", "sr")
    assert "translate Russian speech into Serbian" in to_serbian
    assert "Serbian Latin script" in to_serbian

    to_russian = translation_system_prompt("latin", "ru")
    assert "translate Serbian speech into Russian" in to_russian
    # Письменность имеет смысл только для сербского: у русского она одна.
    assert "Serbian Latin script" not in to_russian


def test_translation_prompt_mentions_script():
    assert "Cyrillic" in translation_system_prompt("cyrillic", "sr")
    # Неизвестное значение не должно ронять бота.
    assert "Latin" in translation_system_prompt("unknown", "sr")


def test_tts_instructions_differ_by_language():
    assert "Serbian" in tts_instructions("sr")
    assert "Russian" in tts_instructions("ru")
    # Неизвестный язык не должен ронять синтез.
    assert "Serbian" in tts_instructions("xx")
