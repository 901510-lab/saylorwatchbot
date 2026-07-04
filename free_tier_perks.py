"""Бонусы Free-тарифа: лимит Strategy PNG-карточек в неделю."""

from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
from typing import Any

from json_store import json_rw_lock, read_json_file
from subscription_plans import PlanId

logger = logging.getLogger(__name__)

FREE_WEEKLY_STRATEGY_CARDS = max(
    0, int(os.environ.get("FREE_WEEKLY_STRATEGY_CARDS", "1"))
)
FREE_CARD_LARGE_BTC = max(
    0.0, float(os.environ.get("FREE_CARD_LARGE_BTC", "100"))
)
PERKS_FILE = Path(os.environ.get("FREE_TIER_PERKS_FILE", "free_tier_perks.json"))


def _default_state() -> dict[str, Any]:
    return {"users": {}}


def _week_key(moment: datetime.datetime | None = None) -> str:
    dt = moment or datetime.datetime.now(datetime.UTC)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _user_bucket(state: dict[str, Any], user_id: int) -> dict[str, Any]:
    users = state.setdefault("users", {})
    key = str(user_id)
    bucket = users.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        users[key] = bucket
    return bucket


def free_strategy_card_allowed(
    user_id: int,
    *,
    entity_id: str,
    abs_delta_btc: float,
    plan: PlanId,
) -> bool:
    """Free: 1 PNG/нед на Strategy или всегда при крупной сделке (>= FREE_CARD_LARGE_BTC)."""
    if plan != PlanId.FREE:
        return False
    if entity_id.strip().lower() != "strategy":
        return False
    if FREE_WEEKLY_STRATEGY_CARDS <= 0 and FREE_CARD_LARGE_BTC <= 0:
        return False
    if FREE_CARD_LARGE_BTC > 0 and abs_delta_btc >= FREE_CARD_LARGE_BTC:
        return True
    if FREE_WEEKLY_STRATEGY_CARDS <= 0:
        return False
    week = _week_key()
    with json_rw_lock(PERKS_FILE, default=_default_state()) as state:
        bucket = _user_bucket(state, user_id)
        if bucket.get("week") != week:
            return True
        used = int(bucket.get("cards_used") or 0)
        return used < FREE_WEEKLY_STRATEGY_CARDS


def record_free_strategy_card(
    user_id: int,
    *,
    abs_delta_btc: float,
) -> None:
    """Учесть отправку free-карточки (крупные сделки не тратят недельный лимит)."""
    large = FREE_CARD_LARGE_BTC > 0 and abs_delta_btc >= FREE_CARD_LARGE_BTC
    if large:
        return
    week = _week_key()
    with json_rw_lock(PERKS_FILE, default=_default_state()) as state:
        bucket = _user_bucket(state, user_id)
        if bucket.get("week") != week:
            bucket["week"] = week
            bucket["cards_used"] = 0
        bucket["cards_used"] = int(bucket.get("cards_used") or 0) + 1
        bucket["last_card_at"] = datetime.datetime.now(datetime.UTC).isoformat()


def perks_summary_for_admin() -> str:
    try:
        data = read_json_file(PERKS_FILE, default=_default_state())
        users = data.get("users") if isinstance(data, dict) else {}
        n = len(users) if isinstance(users, dict) else 0
    except Exception:
        n = 0
    return (
        f"free cards/week={FREE_WEEKLY_STRATEGY_CARDS} "
        f"large>={FREE_CARD_LARGE_BTC} BTC tracked_users={n}"
    )


__all__ = [
    "FREE_WEEKLY_STRATEGY_CARDS",
    "FREE_CARD_LARGE_BTC",
    "PERKS_FILE",
    "free_strategy_card_allowed",
    "record_free_strategy_card",
    "perks_summary_for_admin",
]
