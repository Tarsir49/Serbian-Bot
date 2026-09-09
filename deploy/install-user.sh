#!/usr/bin/env bash
# Установка бота БЕЗ прав root — целиком в домашнюю папку пользователя.
#   bash deploy/install-user.sh
# Каталог можно переопределить: APP_DIR=~/bots/serbian bash deploy/install-user.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/serbian-bot}"
REPO_URL="${REPO_URL:-https://github.com/Tarsir49/Serbian-Bot.git}"
BRANCH="${BRANCH:-main}"

command -v git >/dev/null || { echo "Нужен git: попроси админа поставить (apt install git)"; exit 1; }
command -v python3 >/dev/null || { echo "Нужен python3"; exit 1; }
python3 -m venv --help >/dev/null 2>&1 || {
  echo "Нет модуля venv. Поставь python3-venv (нужен root) или используй python3 -m virtualenv"; exit 1;
}

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ">>> Заполни ключи в $APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"

# Пользовательский systemd-юнит: root не нужен.
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  sed "s|%h/serbian-bot|$APP_DIR|g" "$APP_DIR/deploy/serbian-bot.user.service" \
    > "$HOME/.config/systemd/user/serbian-bot.service"
  systemctl --user daemon-reload
  systemctl --user enable serbian-bot

  # Без lingering сервис остановится при выходе из SSH.
  if loginctl enable-linger "$USER" 2>/dev/null; then
    echo "Автозапуск после перезагрузки включён (linger)."
  else
    echo "ВНИМАНИЕ: не удалось включить linger без root."
    echo "Попроси админа выполнить: loginctl enable-linger $USER"
    echo "Либо добавь автозапуск через cron:  (crontab -e)"
    echo "  @reboot cd $APP_DIR && .venv/bin/python -m bot.main >> $APP_DIR/bot.log 2>&1"
  fi

  systemctl --user restart serbian-bot
  echo "Готово. Логи: journalctl --user -u serbian-bot -f"
else
  echo "systemd --user недоступен. Запусти бота через cron:"
  echo "  (crontab -e) @reboot cd $APP_DIR && .venv/bin/python -m bot.main >> $APP_DIR/bot.log 2>&1"
  echo "Проверить прямо сейчас: cd $APP_DIR && .venv/bin/python -m bot.main"
fi
