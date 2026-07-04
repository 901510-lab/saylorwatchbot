"""Счётчики посещений и подписок — локальная аналитика бота.

bot_stats.json — уникальные user_id, число /start, first/last seen.
Premium и оплаты — из subscribers.json и payments.json.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from json_store import atomic_write_json, json_rw_lock, read_json_file
from subscribers import list_subscribers
from subscription_payments import payment_summary

logger = logging.getLogger(__name__)

BOT_STATS_FILE = Path(os.environ.get("BOT_STATS_FILE", "bot_stats.json"))


@dataclass(frozen=True)
class BotAnalytics:
    unique_users: int
    total_starts: int
    active_premium: int
    total_premium_ever: int
    paid_subscriptions: int
    stars_earned: int
    last_visit: str | None


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


_BOT_STATS_DEFAULT = {"users": {}, "meta": {"total_starts": 0}}


def _load_stats() -> dict[str, Any]:
    if not BOT_STATS_FILE.exists():
        return {"users": {}, "meta": {"total_starts": 0}}
    try:
        data = read_json_file(BOT_STATS_FILE, default=_BOT_STATS_DEFAULT)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("bot_stats.json read error: %s", exc)
        return {"users": {}, "meta": {"total_starts": 0}}
    if not isinstance(data, dict):
        return {"users": {}, "meta": {"total_starts": 0}}
    users = data.get("users") if isinstance(data.get("users"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return {"users": users, "meta": meta}


def _save_stats(data: dict[str, Any]) -> None:
    atomic_write_json(BOT_STATS_FILE, data)


def _mutate_stats(mutator) -> None:
    with json_rw_lock(BOT_STATS_FILE, default=_BOT_STATS_DEFAULT) as blob:
        users = blob.get("users") if isinstance(blob.get("users"), dict) else {}
        meta = blob.get("meta") if isinstance(blob.get("meta"), dict) else {}
        data = {"users": users, "meta": meta}
        mutator(data)
        blob.clear()
        blob.update(data)


def record_start(user_id: int) -> None:
    """Учесть /start: уникальный пользователь +1 к total_starts."""
    if user_id <= 0:
        return

    def _mut(data: dict[str, Any]) -> None:
        users: dict[str, dict] = data["users"]
        meta: dict[str, Any] = data["meta"]
        key = str(user_id)
        now = _utc_now_iso()
        entry = users.get(key, {})
        if not entry:
            entry = {"first_seen": now, "start_count": 0}
        entry["last_seen"] = now
        entry["start_count"] = int(entry.get("start_count", 0)) + 1
        users[key] = entry
        meta["total_starts"] = int(meta.get("total_starts", 0)) + 1

    _mutate_stats(_mut)


def record_activity(user_id: int) -> None:
    """Обновить last_seen без увеличения start_count (любая команда)."""
    if user_id <= 0:
        return

    def _mut(data: dict[str, Any]) -> None:
        users: dict[str, dict] = data["users"]
        key = str(user_id)
        if key not in users:
            return
        users[key]["last_seen"] = _utc_now_iso()

    _mutate_stats(_mut)


def _last_visit_iso(users: dict[str, dict]) -> str | None:
    latest: datetime.datetime | None = None
    for raw in users.values():
        seen = raw.get("last_seen")
        if not seen:
            continue
        try:
            moment = datetime.datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.UTC)
        if latest is None or moment > latest:
            latest = moment
    return latest.isoformat() if latest else None


def _admin_user_id() -> int | None:
    raw = os.environ.get("X_CHAT_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _total_starts_excluding_admin(users: dict[str, dict]) -> int:
    admin_id = _admin_user_id()
    total = 0
    for uid, raw in users.items():
        if admin_id is not None and uid == str(admin_id):
            continue
        try:
            total += int(raw.get("start_count", 0))
        except (TypeError, ValueError):
            continue
    return total


def get_analytics() -> BotAnalytics:
    data = _load_stats()
    users = data["users"]
    all_subs = list_subscribers()
    active = list_subscribers(active_premium_only=True)
    paid_count, stars = payment_summary()
    return BotAnalytics(
        unique_users=len(users),
        # В отчёте /info и /botstats не считаем admin (/X_CHAT_ID) в Total /start.
        total_starts=_total_starts_excluding_admin(users),
        active_premium=len(active),
        total_premium_ever=len(all_subs),
        paid_subscriptions=paid_count,
        stars_earned=stars,
        last_visit=_last_visit_iso(users),
    )


__all__ = [
    "BOT_STATS_FILE",
    "BotAnalytics",
    "record_start",
    "record_activity",
    "get_analytics",
]
