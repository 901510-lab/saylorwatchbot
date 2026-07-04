"""Предпочтения языка UI — единый lock-aware модуль."""

from __future__ import annotations

import os
from pathlib import Path

from i18n import DEFAULT_LANG, SUPPORTED_LANGS
from json_store import json_rw_lock

USER_LANG_FILE = Path(os.environ.get("USER_LANG_FILE", "user_languages.json"))


def get_user_lang(user_id: int | None) -> str:
    if user_id is None:
        return DEFAULT_LANG
    with json_rw_lock(USER_LANG_FILE, default={}) as data:
        code = data.get(str(user_id), DEFAULT_LANG)
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def set_user_lang(telegram_id: int, lang: str) -> None:
    code = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    with json_rw_lock(USER_LANG_FILE, default={}) as data:
        data[str(telegram_id)] = code


__all__ = ["USER_LANG_FILE", "get_user_lang", "set_user_lang"]
