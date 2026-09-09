"""Определение языка текста: сербский или русский.

Сербская и русская кириллицы почти совпадают, но их «личные» буквы не пересекаются
вообще: ђјљњћџ есть только в сербской, ёйщъыьэюя — только в русской. Поэтому в
большинстве случаев язык определяется по алфавиту, бесплатно и мгновенно. Остаются
короткие фразы на общих буквах («Хвала пуно», «Добар дан») — их разбирает LLM.
"""

from __future__ import annotations

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
