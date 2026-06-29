#!/usr/bin/env python3
"""Генерирует Modelfile.saylorwatch-support из bot_knowledge.py (единый источник истины)."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from bot_knowledge import bot_knowledge_text, command_cheatsheet_for_llm  # noqa: E402

BASE = "qwen2.5:3b"
OUT = _SCRIPTS / "Modelfile.saylorwatch-support"

SYSTEM = f'''You are SaylorWatch email support (@Saylor_w_bot — Bitcoin treasury / whale tracker).

REPLY FORMAT:
1) Direct answer (yes/no or core fact).
2) Optional one-line context.
3) Blank line.
4) Numbered steps when the user asks HOW TO do something in the bot.

If NOT in BOT KNOWLEDGE below — reply ONLY: UNCERTAIN: <reason>. Never guess.

When customer asks «what does /command mean» — explain THAT command only.
/info is admin-only — say so; regular users should use /status and /help.

STYLE: ~120 words max. Same language as customer. No Premium push unless asked.

{bot_knowledge_text()}

{command_cheatsheet_for_llm()}

UNCERTAIN example (enterprise API):
UNCERTAIN: no public enterprise API in product FAQ
'''

HEADER = f"""# Auto-generated — edit bot_knowledge.py, then: python3 scripts/generate_modelfile.py
# Создание модели: bash scripts/setup_ollama_support_model.sh

FROM {BASE}

PARAMETER temperature 0.12
PARAMETER top_p 0.9
PARAMETER num_predict 450

SYSTEM \"\"\"
"""

FOOTER = '\n\"\"\"\n'


def main() -> None:
    content = HEADER + SYSTEM.replace('"""', '\\"\\"\\"') + FOOTER
    OUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
