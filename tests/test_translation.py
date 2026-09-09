import pytest

from bot.prompts import translation_system_prompt
from bot.translation import clean_translation, is_unintelligible


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
