#!/usr/bin/env bash
# Установка бота на VPS (Debian/Ubuntu). Запускать от root:
#   bash deploy/install.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/serbian-bot}"
APP_USER=serbian-bot
REPO_URL="${REPO_URL:-https://github.com/Tarsir49/Serbian-Bot.git}"
BRANCH="${BRANCH:-main}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Нужны права root: sudo bash deploy/install.sh"
  echo "Нет root? Поставь бота в домашнюю папку: bash deploy/install-user.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip git

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

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
  echo "Заполни ключи в $APP_DIR/.env и запусти: systemctl restart serbian-bot"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

install -m 644 "$APP_DIR/deploy/serbian-bot.service" /etc/systemd/system/serbian-bot.service
systemctl daemon-reload
systemctl enable serbian-bot
systemctl restart serbian-bot
systemctl --no-pager status serbian-bot || true
