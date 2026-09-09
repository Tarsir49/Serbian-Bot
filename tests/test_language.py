import pytest

from bot.language import detect_by_script, other_language


@pytest.mark.parametrize(
    "text",
    [
        # Латиница: по-русски так не пишут.
        "Dobar dan, kako ste?",
        "Hvala puno",
        "Ćao!",
        # Кириллица с буквами, которых нет в русском алфавите.
        "Ћао, како си?",
        "Извини, где је најближа апотека?",
        "Њихова кућа",
    ],
)
def test_serbian_is_recognised(text):
    assert detect_by_script(text) == "sr"


@pytest.mark.parametrize(
    "text",
    [
        # Буквы, которых нет в сербском алфавите: ы, й, ь, э, ю, я, щ, ъ, ё.
        "Добрый день",
        "Сколько это стоит?",
        "Я тебя не понял",
        "Ещё раз, пожалуйста",
    ],
)
def test_russian_is_recognised(text):
    assert detect_by_script(text) == "ru"


@pytest.mark.parametrize(
    "text",
    [
        # Только общие буквы — по алфавиту не различить, нужна модель.
        "Хвала пуно",
        "Добар дан",
        "Привет, как дела?",
        "",
        "12:30",
    ],
)
def test_ambiguous_text_is_left_undecided(text):
    assert detect_by_script(text) is None


def test_latin_wins_over_stray_cyrillic():
    # Расшифровка может смешать письменности; решает то, чего больше.
    assert detect_by_script("Kada pričam sa njim, on skrene razgovor на temu") == "sr"


def test_other_language_flips_direction():
    assert other_language("ru") == "sr"
    assert other_language("sr") == "ru"
