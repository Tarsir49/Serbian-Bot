# Serbian-Bot

Телеграм-бот: присылаешь голосовое на русском — получаешь голосовое на сербском.

```
🎤 голос (ru)  →  STT (Whisper)  →  LLM-перевод  →  TTS (сербский)  →  🔊 голос (sr)
```

Перевод делается с явной установкой: **простая разговорная речь, лаконично, без комментариев** —
модель возвращает только текст перевода. В ответ приходит голосовое сообщение и, по желанию,
текст перевода вместе с распознанным оригиналом (чтобы видеть, что бот вас расслышал).

## Что нужно

* VPS с Python 3.11+ (проверено на 3.11 и 3.12).
* Токен бота от [@BotFather](https://t.me/BotFather).
* **Ключ OpenAI** — обязателен: распознавание и синтез речи идут через OpenAI Audio API
  (у Anthropic нет ни STT, ни TTS).
* Ключ Anthropic — опционально, если перевод хочется делать через Claude.

## Архитектура

| Шаг | Что делает | Где живёт |
|-----|------------|-----------|
| 1 | Скачивает голосовое из Telegram | `bot/handlers.py` |
| 2 | Распознаёт русскую речь (`whisper-1`) | `bot/speech.py` |
| 3 | Переводит на сербский (OpenAI **или** Anthropic) | `bot/translation.py` |
| 4 | Озвучивает перевод (`gpt-4o-mini-tts`, OGG/Opus) | `bot/speech.py` |
| 5 | Отправляет `voice`-сообщение обратно | `bot/handlers.py` |

Оркестрация — `bot/pipeline.py`, конфиг — `bot/config.py`, промпты — `bot/prompts.py`.

Провайдер перевода переключается одной переменной `LLM_PROVIDER=openai|anthropic`,
интерфейс общий (`bot/translation.py::Translator`), так что добавить третий — это один класс.

## Быстрый старт локально

```bash
git clone https://github.com/Tarsir49/Serbian-Bot.git
cd Serbian-Bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # вписать TELEGRAM_BOT_TOKEN и OPENAI_API_KEY
python -m bot.main
```

## Деплой на VPS (systemd)

```bash
# на сервере, от root
git clone https://github.com/Tarsir49/Serbian-Bot.git /opt/serbian-bot
bash /opt/serbian-bot/deploy/install.sh
nano /opt/serbian-bot/.env          # вписать ключи
systemctl restart serbian-bot
journalctl -u serbian-bot -f        # логи
```

`deploy/install.sh` создаёт системного пользователя `serbian-bot`, ставит зависимости в
`/opt/serbian-bot/.venv`, кладёт unit-файл `deploy/serbian-bot.service` и включает автозапуск.
Бот работает на long polling — открытых портов, домена и TLS не требуется.

Обновление:

```bash
cd /opt/serbian-bot && git pull && .venv/bin/pip install -r requirements.txt
systemctl restart serbian-bot
```

## Деплой через Docker

```bash
cp .env.example .env   # заполнить
docker compose up -d --build
docker compose logs -f
```

## Настройки (`.env`)

| Переменная | По умолчанию | Зачем |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | токен бота (обязательно) |
| `OPENAI_API_KEY` | — | STT + TTS (обязательно) |
| `LLM_PROVIDER` | `openai` | кто переводит: `openai` или `anthropic` |
| `OPENAI_TRANSLATION_MODEL` | `gpt-4.1-mini` | модель перевода для OpenAI |
| `ANTHROPIC_API_KEY` | — | нужен при `LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | `claude-opus-5` | модель Claude |
| `ANTHROPIC_EFFORT` | `low` | глубина «раздумий» Claude; для перевода реплики хватает `low` |
| `STT_MODEL` | `whisper-1` | можно `gpt-4o-transcribe` |
| `TTS_MODEL` | `gpt-4o-mini-tts` | можно `tts-1`, `tts-1-hd` |
| `TTS_VOICE` | `alloy` | голос озвучки |
| `TTS_SPEED` | `1.0` | скорость (только для `tts-1*`) |
| `SERBIAN_SCRIPT` | `latin` | `latin` (latinica) или `cyrillic` (ćirilica) |
| `SEND_TRANSLATION_TEXT` | `true` | слать текст перевода вместе с аудио |
| `MAX_VOICE_DURATION` | `180` | лимит длины голосового, сек |
| `MAX_TEXT_LENGTH` | `1500` | лимит длины текста, символов |
| `REQUEST_TIMEOUT` | `90` | таймаут вызова API, сек |
| `ALLOWED_USER_IDS` | пусто | белый список id; пусто = бот открыт всем |
| `LOG_LEVEL` | `INFO` | уровень логов |

Свой Telegram id можно узнать у [@userinfobot](https://t.me/userinfobot). Пока `ALLOWED_USER_IDS`
пуст, ботом может пользоваться кто угодно, кто найдёт его по имени — и тратить ваши токены.

## Как пользоваться

* `/start`, `/help` — справка.
* Голосовое на русском → голосовое на сербском.
* Текст на русском → тоже переводится и озвучивается.
* Пересланные аудиофайлы и видео-кружки обрабатываются так же, как голосовые.

Один пользователь — один запрос за раз: пока предыдущее сообщение обрабатывается,
следующее вежливо отклоняется (защита от случайного спама и лишних расходов).

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Тесты не ходят в сеть: пайплайн проверяется на заглушках STT/LLM/TTS, отдельно —
разбор конфига и очистка ответа модели от лишних кавычек и подписей.

## Стоимость (порядок величин)

На одно голосовое ~15 секунд: распознавание `whisper-1` ≈ $0.0015, перевод на
`gpt-4.1-mini` — доли цента, озвучка `gpt-4o-mini-tts` ≈ $0.001–0.002.
Итого — примерно полцента за сообщение; Claude в роли переводчика дороже,
`ANTHROPIC_MODEL=claude-haiku-4-5` заметно дешевле `claude-opus-5`.
