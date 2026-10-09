import pytest

from bot.language import (
    detect_against_grain,
    detect_by_script,
    looks_like_echo,
    other_language,
)


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


# --- выбор языка по двум расшифровкам одного аудио ------------------------------


def test_serbian_letters_in_the_russian_pass_mean_serbian_speech():
    # Проходу велели слышать русский, а он выдал ћ — так пишут только по-сербски.
    assert (
        detect_against_grain(
            {"ru": "Хвала пуно на помоћи", "sr": "Hvala puno na pomoći"}
        )
        == "sr"
    )


def test_latin_in_the_russian_pass_means_serbian_speech():
    assert (
        detect_against_grain({"ru": "Hvala puno", "sr": "Hvala puno na pomoći"}) == "sr"
    )


def test_russian_letters_in_the_serbian_pass_mean_russian_speech():
    assert (
        detect_against_grain(
            {"ru": "Привет! Как ты сегодня?", "sr": "Привет, как ты сегодня"}
        )
        == "ru"
    )


def test_each_pass_confirming_itself_decides_nothing():
    # Классический случай поломки: русский проход «услышал» сербскую речь русскими
    # словами, и оба варианта подтверждают свой собственный язык. Решать не нам.
    assert (
        detect_against_grain(
            {"ru": "Я сам добро, хвала на питаню", "sr": "Ја сам добро, хвала на питању"}
        )
        is None
    )


def test_single_pass_decides_nothing():
    assert detect_against_grain({"ru": "Привет"}) is None


# --- защита от эха вместо перевода ---------------------------------------------


def test_identical_text_is_echo():
    assert looks_like_echo("Dobar dan, kako ste?", "Dobar dan, kako ste?")


def test_punctuation_only_difference_is_echo():
    assert looks_like_echo("Извините, не понимаю", "Извините, не понимаю.")


def test_real_translation_is_not_echo():
    assert not looks_like_echo("Сколько это стоит?", "Koliko to košta?")
    assert not looks_like_echo("Хвала пуно на помоћи", "Большое спасибо за помощь")
    # Близкие пары в кириллице не должны ложно считаться эхом.
    assert not looks_like_echo("Добро јутро", "Доброе утро")
    assert not looks_like_echo("Добар дан, како сте?", "Добрый день, как вы?")


def test_short_words_compared_exactly():
    # «Такси» -> «Taksi» похоже лишь на слух; и наоборот, одно слово без изменений
    # — это всё-таки эхо.
    assert not looks_like_echo("Такси", "Taksi")
    assert looks_like_echo("Мама", "Мама")
