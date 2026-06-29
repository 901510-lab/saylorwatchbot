#!/usr/bin/env bash
# Создаёт локальную модель Ollama с системным промптом SaylorWatch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama не установлен: https://ollama.com" >&2
  exit 1
fi

BASE="${OLLAMA_BASE_MODEL:-qwen2.5:3b}"
echo "Generate Modelfile from bot_knowledge.py"
python3 scripts/generate_modelfile.py

echo "Pull base model: $BASE"
ollama pull "$BASE"

TMP="$(mktemp)"
sed "s/^FROM qwen2.5:3b/FROM ${BASE}/" scripts/Modelfile.saylorwatch-support >"$TMP"
ollama create saylorwatch-support -f "$TMP"
rm -f "$TMP"

echo ""
echo "Готово: saylorwatch-support"
echo "Добавьте в scripts/email_support.env:"
echo "  OLLAMA_MODEL=saylorwatch-support"
echo ""
echo "Проверка:"
echo "  python3 scripts/email_support_agent.py --test-reply 'Можно узнать курс биткоина в боте?'"
