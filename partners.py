"""Партнёрские ссылки (Day 26): Binance, Bybit, Ledger — из env."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Partner:
    id: str
    url: str
    btn_key: str
    desc_key: str


_PARTNER_ENV: tuple[tuple[str, str, str, str], ...] = (
    ("binance", "PARTNER_BINANCE_URL", "partner_btn_binance", "partner_desc_binance"),
    ("bybit", "PARTNER_BYBIT_URL", "partner_btn_bybit", "partner_desc_bybit"),
    ("ledger", "PARTNER_LEDGER_URL", "partner_btn_ledger", "partner_desc_ledger"),
)


def _env_url(key: str) -> str | None:
    value = os.environ.get(key, "").strip()
    return value if value.startswith(("http://", "https://")) else None


def configured_partners() -> list[Partner]:
    partners: list[Partner] = []
    for partner_id, env_key, btn_key, desc_key in _PARTNER_ENV:
        url = _env_url(env_key)
        if url:
            partners.append(Partner(partner_id, url, btn_key, desc_key))
    return partners


def partners_configured() -> bool:
    return bool(configured_partners())
