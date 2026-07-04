#!/usr/bin/env bash
# Виртуальное окружение для Google Calendar sync (Ubuntu PEP 668 — без system pip).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${ROOT}/.venv-social"
REQ="${ROOT}/scripts/requirements-social.txt"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install: sudo apt install python3 python3-venv" >&2
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  echo "Creating $VENV ..."
  python3 -m venv "$VENV"
fi

echo "Installing into $VENV ..."
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$REQ"

echo ""
echo "Done. Run sync:"
echo "  $VENV/bin/python $ROOT/scripts/social_calendar_sync.py"
echo ""
echo "Or from repo root:"
echo "  .venv-social/bin/python scripts/social_calendar_sync.py --weeks 12"
