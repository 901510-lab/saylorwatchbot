"""Мини-вики команд — обёртка для main.py (импорт из scripts/bot_knowledge)."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from bot_knowledge import (  # noqa: E402
    format_help_wiki,
    help_wiki_email_appendix,
    should_append_email_help_wiki,
)

__all__ = [
    "format_help_wiki",
    "help_wiki_email_appendix",
    "should_append_email_help_wiki",
]
