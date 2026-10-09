"""Определение языка текста: сербский или русский.

Сербская и русская кириллицы почти совпадают, но их «личные» буквы не пересекаются
вообще: ђјљњћџ есть только в сербской, ёйщъыьэюя — только в русской. Поэтому в
большинстве случаев язык определяется по алфавиту, бесплатно и мгновенно. Остаются
короткие фразы на общих буквах («Хвала пуно», «Добар дан») — их разбирает LLM.
"""

from __future__ import annotations

from difflib import SequenceMatcher

SERBIAN = "sr"
RUSSIAN = "ru"

# Буквы, которых нет в русском алфавите.
SERBIAN_ONLY = frozenset("ђјљњћџ")
# Буквы, которых нет в сербском алфавите.
RUSSIAN_ONLY = frozenset("ёйщъыьэюя")

_CYRILLIC = range(0x0400, 0x0500)


def other_language(lang: str) -> str:
    """Второй язык пары: направление перевода всегда «в другой»."""
    return RUSSIAN if lang == SERBIAN else SERBIAN


def _is_cyrillic(ch: str) -> bool:
    return ord(ch) in _CYRILLIC


def detect_by_script(text: str) -> str | None:
    """Язык по алфавиту или None, если букв-примет не нашлось."""
    letters = [ch for ch in text.lower() if ch.isalpha()]
    if not letters:
        return None

    cyrillic = sum(1 for ch in letters if _is_cyrillic(ch))
    # Русский латиницей не пишут, а сербская латиница — половина всех текстов на нём.
    if cyrillic * 2 < len(letters):
        return SERBIAN

    serbian_hits = sum(1 for ch in letters if ch in SERBIAN_ONLY)
    russian_hits = sum(1 for ch in letters if ch in RUSSIAN_ONLY)
    if serbian_hits > russian_hits:
        return SERBIAN
    if russian_hits > serbian_hits:
        return RUSSIAN
    # Общие буквы с обеих сторон или поровну примет — решить нельзя.
    return None


def detect_against_grain(by_lang: dict[str, str]) -> str | None:
    """Язык по приметам, возникшим ВОПРЕКИ навязанному проходу распознавания.

    Два прохода одного аудио нельзя сравнивать по алфавиту напрямую: каждый
    пишет на том языке, который ему велели, и подтверждает сам себя. Зато
    примета против течения говорит много: если проход, которому сказали «это
    русский», всё равно выдал ђјљњћџ или латиницу — речь сербская, и наоборот.
    """
    russian_pass = by_lang.get(RUSSIAN, "")
    serbian_pass = by_lang.get(SERBIAN, "")
    if not russian_pass or not serbian_pass:
        return None

    russian_pass_says = detect_by_script(russian_pass)
    serbian_pass_says = detect_by_script(serbian_pass)
    # Проверяем и вторую сторону: когда оба прохода тянут против своего языка,
    # это шум, а не улика.
    if russian_pass_says == SERBIAN and serbian_pass_says != RUSSIAN:
        return SERBIAN
    if serbian_pass_says == RUSSIAN and russian_pass_says != SERBIAN:
        return RUSSIAN
    return None


_ECHO_RATIO = 0.95
_ECHO_MIN_LENGTH = 8


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).strip()


def looks_like_echo(source: str, translated: str) -> bool:
    """Вернул ли переводчик тот же текст вместо перевода.

    Защита от главного способа соврать молча: прислать исходную фразу как
    перевод. Короткие реплики не проверяем — там совпадение бывает законным
    («Taksi», «Mama»).
    """
    left, right = _normalize(source), _normalize(translated)
    if not left or not right:
        return False
    if len(left) < _ECHO_MIN_LENGTH or len(right) < _ECHO_MIN_LENGTH:
        return left == right
    return SequenceMatcher(None, left, right).ratio() >= _ECHO_RATIO
