"""Хранение статуса подписки пользователей — День 17.

Файл subscribers.json: user_id → plan, expires_at, updated_at.
Гейтинг алертов — День 19.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from json_store import atomic_write_json, file_lock, json_rw_lock, read_json_file
from subscription_plans import PlanId

logger = logging.getLogger(__name__)

_SUBSCRIBERS_DEFAULT = {"subscribers": {}}

SUBSCRIBERS_FILE = Path(os.environ.get("SUBSCRIBERS_FILE", "subscribers.json"))


@dataclass
class Subscriber:
    user_id: int
    plan: PlanId
    expires_at: str | None = None  # ISO UTC; None = free без срока / бессрочно premium
    updated_at: str | None = None

    def is_active_premium(self, *, now: datetime.datetime | None = None) -> bool:
        if self.plan != PlanId.PREMIUM:
            return False
        if not self.expires_at:
            return True
        try:
            exp = datetime.datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.UTC)
        moment = now or datetime.datetime.now(datetime.UTC)
        return exp > moment


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _normalize_subscribers_blob(data: object) -> dict[str, dict]:
    if isinstance(data, dict) and isinstance(data.get("subscribers"), dict):
        return {str(k): v for k, v in data["subscribers"].items() if isinstance(v, dict)}
    if isinstance(data, dict):
        return {str(k): v for k, v in data.items() if isinstance(v, dict) and k != "subscribers"}
    return {}


def _load_raw() -> dict[str, dict]:
    if not SUBSCRIBERS_FILE.exists():
        return {}
    try:
        data = read_json_file(SUBSCRIBERS_FILE, default=_SUBSCRIBERS_DEFAULT)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("subscribers.json read error: %s", exc)
        return {}
    return _normalize_subscribers_blob(data)


def _save_raw(subscribers: dict[str, dict]) -> None:
    atomic_write_json(SUBSCRIBERS_FILE, {"subscribers": subscribers})


def _parse_subscriber(user_id: str, raw: dict) -> Subscriber | None:
    try:
        plan = PlanId(str(raw.get("plan", PlanId.FREE.value)).strip().lower())
    except ValueError:
        plan = PlanId.FREE
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    return Subscriber(
        user_id=uid,
        plan=plan,
        expires_at=raw.get("expires_at"),
        updated_at=raw.get("updated_at"),
    )


def get_subscriber(user_id: int) -> Subscriber | None:
    raw = _load_raw().get(str(user_id))
    if not raw:
        return None
    return _parse_subscriber(str(user_id), raw)


def list_subscribers(*, active_premium_only: bool = False) -> list[Subscriber]:
    result: list[Subscriber] = []
    for uid, raw in _load_raw().items():
        sub = _parse_subscriber(uid, raw)
        if sub is None:
            continue
        if active_premium_only and not sub.is_active_premium():
            continue
        result.append(sub)
    result.sort(key=lambda s: s.user_id)
    return result


def effective_plan(user_id: int | None) -> PlanId:
    """Актуальный тариф с учётом expires_at."""
    if user_id is None:
        return PlanId.FREE
    sub = get_subscriber(user_id)
    if sub and sub.is_active_premium():
        return PlanId.PREMIUM
    return PlanId.FREE


def set_subscription(
    user_id: int,
    plan: PlanId | str,
    *,
    expires_at: datetime.datetime | str | None = None,
) -> Subscriber:
    """Записать или обновить подписку пользователя."""
    if isinstance(plan, PlanId):
        pid = plan
    else:
        try:
            pid = PlanId(str(plan).strip().lower())
        except ValueError:
            pid = PlanId.FREE

    exp_iso: str | None
    if pid == PlanId.FREE:
        exp_iso = None
    elif expires_at is None:
        raise ValueError("Premium subscription requires expires_at")
    elif isinstance(expires_at, datetime.datetime):
        exp_iso = expires_at.astimezone(datetime.UTC).isoformat()
    else:
        exp_iso = str(expires_at)

    sub = Subscriber(
        user_id=user_id,
        plan=pid,
        expires_at=exp_iso,
        updated_at=_utc_now_iso(),
    )
    with json_rw_lock(SUBSCRIBERS_FILE, default=_SUBSCRIBERS_DEFAULT) as blob:
        data = _normalize_subscribers_blob(blob)
        data[str(user_id)] = {
            "plan": sub.plan.value,
            "expires_at": sub.expires_at,
            "updated_at": sub.updated_at,
        }
        blob.clear()
        blob.update({"subscribers": data})
    return sub


def grant_premium_days(user_id: int, days: int) -> Subscriber:
    """Premium на N дней от now (или продление от текущего expires_at)."""
    days = max(1, int(days))
    now = datetime.datetime.now(datetime.UTC)
    existing = get_subscriber(user_id)
    base = now
    if existing and existing.expires_at and existing.is_active_premium(now=now):
        try:
            current_exp = datetime.datetime.fromisoformat(
                existing.expires_at.replace("Z", "+00:00")
            )
            if current_exp.tzinfo is None:
                current_exp = current_exp.replace(tzinfo=datetime.UTC)
            if current_exp > base:
                base = current_exp
        except ValueError:
            pass
    expires = base + datetime.timedelta(days=days)
    return set_subscription(user_id, PlanId.PREMIUM, expires_at=expires)


def revoke_subscription(user_id: int) -> None:
    """Сбросить premium → free (удалить запись)."""
    with json_rw_lock(SUBSCRIBERS_FILE, default=_SUBSCRIBERS_DEFAULT) as blob:
        data = _normalize_subscribers_blob(blob)
        data.pop(str(user_id), None)
        blob.clear()
        blob.update({"subscribers": data})


def days_remaining(sub: Subscriber | None) -> int | None:
    if sub is None or not sub.expires_at or not sub.is_active_premium():
        return None
    try:
        exp = datetime.datetime.fromisoformat(sub.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=datetime.UTC)
    delta = exp - datetime.datetime.now(datetime.UTC)
    return max(0, int((delta.total_seconds() + 86399) // 86400))


def calendar_days_until_expiry(
    sub: Subscriber | None,
    *,
    now: datetime.datetime | None = None,
) -> int | None:
    """Календарные дни до expires_at (UTC). 1 = завтра, 0 = сегодня."""
    if sub is None or not sub.expires_at or not sub.is_active_premium(now=now):
        return None
    try:
        exp = datetime.datetime.fromisoformat(sub.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=datetime.UTC)
    moment = now or datetime.datetime.now(datetime.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.UTC)
    return (exp.astimezone(datetime.UTC).date() - moment.astimezone(datetime.UTC).date()).days


def expiry_date_label(sub: Subscriber | None) -> str | None:
    if sub is None or not sub.expires_at:
        return None
    try:
        exp = datetime.datetime.fromisoformat(sub.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=datetime.UTC)
    return exp.astimezone(datetime.UTC).date().isoformat()


__all__ = [
    "SUBSCRIBERS_FILE",
    "Subscriber",
    "get_subscriber",
    "list_subscribers",
    "effective_plan",
    "set_subscription",
    "grant_premium_days",
    "revoke_subscription",
    "days_remaining",
    "calendar_days_until_expiry",
    "expiry_date_label",
]
