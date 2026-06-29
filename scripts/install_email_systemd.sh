#!/usr/bin/env bash
# Установка user systemd: catch-up при входе + опрос каждые 30 мин пока ПК включён.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

for f in saylorwatch-email-startup.service saylorwatch-email-poll.service saylorwatch-email-poll.timer; do
  sed -e "s|@REPO@|$REPO|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$REPO/scripts/systemd/$f" > "$UNIT_DIR/$f"
  echo "→ $UNIT_DIR/$f"
done

systemctl --user daemon-reload
systemctl --user enable saylorwatch-email-startup.service
systemctl --user enable saylorwatch-email-poll.timer
systemctl --user start saylorwatch-email-startup.service || true

echo ""
echo "✅ User systemd установлен."
echo "   При каждом входе: catch-up (--startup)"
echo "   Пока ПК включён: опрос каждые 30 мин"
echo ""
echo "Проверка:"
echo "  systemctl --user status saylorwatch-email-startup.service"
echo "  journalctl --user -u saylorwatch-email-startup.service -n 30"
echo ""
echo "Автозапуск systemd user при логине (один раз):"
echo "  loginctl enable-linger \$USER"
