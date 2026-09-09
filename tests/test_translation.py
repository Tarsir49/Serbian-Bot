import pytest

from bot.prompts import translation_system_prompt, tts_instructions
from bot.translation import clean_translation, is_unintelligible, parse_translation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ćao, kako si?", "Ćao, kako si?"),
        ("  Ćao!  ", "Ćao!"),
        ('"Ćao, kako si?"', "Ćao, kako si?"),
        ("«Ćao»", "Ćao"),
        ("Prevod: Ćao", "Ćao"),
        ("Перевод: Ćao", "Ćao"),
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


def test_system_prompt_mentions_script():
    assert "Latin" in translation_system_prompt("latin")
    assert "Cyrillic" in translation_system_prompt("cyrillic")
    # Неизвестное значение не должно ронять бота.
    assert "Latin" in translation_system_prompt("unknown")


def test_system_prompt_asks_for_both_directions():
    prompt = translation_system_prompt("latin")
    assert "Russian input" in prompt and "Serbian input" in prompt
    assert "LANG: sr" in prompt and "LANG: ru" in prompt


@pytest.mark.parametrize(
    ("raw", "text", "lang"),
    [
        ("LANG: sr\nĆao, kako si?", "Ćao, kako si?", "sr"),
        ("LANG: ru\nПривет, как дела?", "Привет, как дела?", "ru"),
        # Регистр и лишние пробелы модель иногда ставит по-своему.
        ("lang:SR\nĆao", "Ćao", "sr"),
        ("  LANG : ru \nПривет", "Привет", "ru"),
        # Чистка обёртки работает и после снятия метки.
        ('LANG: sr\n"Ćao"', "Ćao", "sr"),
        ("LANG: ru\nПеревод: Привет", "Привет", "ru"),
        # Многострочный перевод не должен схлопываться.
        ("LANG: sr\nDobar dan.\nKako ste?", "Dobar dan.\nKako ste?", "sr"),
    ],
)
def test_parse_translation(raw, text, lang):
    result = parse_translation(raw)
    assert result.text == text
    assert result.target_lang == lang


def test_parse_translation_without_tag_defaults_to_serbian():
    # Модель забыла метку — сохраняем прежнее поведение бота.
    result = parse_translation("Ćao, kako si?")
    assert result.text == "Ćao, kako si?"
    assert result.target_lang == "sr"


def test_parse_translation_keeps_unintelligible_marker():
    assert is_unintelligible(parse_translation("???").text)


def test_tts_instructions_differ_by_language():
    assert "Serbian" in tts_instructions("sr")
    assert "Russian" in tts_instructions("ru")
    # Неизвестный язык не должен ронять синтез.
    assert "Serbian" in tts_instructions("xx")
