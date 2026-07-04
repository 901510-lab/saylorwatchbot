#!/usr/bin/env bash
# User systemd: ежедневный пост CoinGecko-таблиц в @Paper_wallet_co в 12:00 MSK.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

ENV_FILE="$REPO/scripts/paper_wallet.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Создайте $ENV_FILE из scripts/paper_wallet.example.env" >&2
  exit 1
fi

for f in paper-wallet-daily.service paper-wallet-daily.timer; do
  sed -e "s|@REPO@|$REPO|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$REPO/scripts/systemd/$f" > "$UNIT_DIR/$f"
  echo "→ $UNIT_DIR/$f"
done

systemctl --user daemon-reload
systemctl --user enable paper-wallet-daily.timer
systemctl --user start paper-wallet-daily.timer

echo ""
echo "✅ Timer: каждый день 12:00 Europe/Moscow"
echo ""
echo "Проверка:"
echo "  python3 scripts/paper_wallet_post.py --check"
echo "  python3 scripts/paper_wallet_post.py --dry-run"
echo "  systemctl --user list-timers paper-wallet-daily.timer"
echo ""
echo "Ручной пост (игнор «уже сегодня»):"
echo "  python3 scripts/paper_wallet_post.py --force"
echo ""
echo "Автозапуск при выключенном ПК не сработает — нужен включённый ПК или VPS."
echo "Один раз: loginctl enable-linger \$USER"
