"""Напоминания об окончании Premium — за 3, 2 и 1 день до expires_at."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from json_store import atomic_write_json, json_rw_lock, read_json_file
from founding_promo import user_claimed_founding, user_claim_slot
from i18n import DEFAULT_LANG, SUPPORTED_LANGS, t
from subscribers import (
    calendar_days_until_expiry,
    expiry_date_label,
    list_subscribers,
)

logger = logging.getLogger(__name__)

REMINDERS_ENABLED = os.environ.get("PREMIUM_EXPIRY_REMINDER_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
REMINDER_TIMEZONE = os.environ.get("PREMIUM_EXPIRY_REMINDER_TIMEZONE", "America/New_York")
REMINDER_HOUR = int(os.environ.get("PREMIUM_EXPIRY_REMINDER_HOUR", "10"))
REMINDER_MINUTE = int(os.environ.get("PREMIUM_EXPIRY_REMINDER_MINUTE", "0"))
REMINDER_DAYS_BEFORE = tuple(
    sorted(
        {
            max(0, int(part.strip()))
            for part in os.environ.get("PREMIUM_EXPIRY_REMINDER_DAYS", "3,2,1,0").split(",")
            if part.strip()
        },
        reverse=True,
    )
)
STATE_FILE = Path(os.environ.get("PREMIUM_EXPIRY_REMINDER_STATE_FILE", "subscription_expiry_reminders.json"))
_REMINDER_STATE_DEFAULT = {"sent": {}, "last_run_date": None}
ADMIN_CHAT_ID = os.getenv("X_CHAT_ID", "").strip()


def reminders_enabled() -> bool:
    return REMINDERS_ENABLED and bool(REMINDER_DAYS_BEFORE)


def _reminder_tz() -> ZoneInfo:
    try:
        return ZoneInfo(REMINDER_TIMEZONE)
    except Exception:
        logger.warning("Invalid PREMIUM_EXPIRY_REMINDER_TIMEZONE=%s, using UTC", REMINDER_TIMEZONE)
        return ZoneInfo("UTC")


def run_date_key(moment: datetime.datetime | None = None) -> str:
    tz = _reminder_tz()
    return (moment or datetime.datetime.now(tz)).astimezone(tz).date().isoformat()


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"sent": {}, "last_run_date": None}
    try:
        data = read_json_file(STATE_FILE, default=_REMINDER_STATE_DEFAULT)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("%s read error: %s", STATE_FILE, exc)
        return {"sent": {}, "last_run_date": None}
    if not isinstance(data, dict):
        return {"sent": {}, "last_run_date": None}
    sent = data.get("sent")
    if not isinstance(sent, dict):
        sent = {}
    return {"sent": sent, "last_run_date": data.get("last_run_date")}


def _save_state(state: dict) -> None:
    atomic_write_json(STATE_FILE, state)


def daily_run_already_done(*, moment: datetime.datetime | None = None) -> bool:
    state = _load_state()
    return state.get("last_run_date") == run_date_key(moment)


def _reminder_sent(user_id: int, expires_on: str, days_left: int) -> bool:
    key = f"{user_id}:{expires_on}:{days_left}"
    return key in _load_state()["sent"]


def _mark_reminder_sent(user_id: int, expires_on: str, days_left: int) -> None:
    state = _load_state()
    key = f"{user_id}:{expires_on}:{days_left}"
    state["sent"][key] = datetime.datetime.now(datetime.UTC).isoformat()
    _save_state(state)


def _user_lang(user_id: int) -> str:
    lang_file = Path(os.environ.get("USER_LANG_FILE", "user_languages.json"))
    if lang_file.exists():
        try:
            data = json.loads(lang_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                code = str(data.get(str(user_id), DEFAULT_LANG)).strip().lower()
                if code in SUPPORTED_LANGS:
                    return code
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_LANG


def _is_admin_user(user_id: int) -> bool:
    return bool(ADMIN_CHAT_ID) and str(user_id) == ADMIN_CHAT_ID


def seconds_until_next_run(*, now: datetime.datetime | None = None) -> float:
    tz = _reminder_tz()
    moment = (now or datetime.datetime.now(tz)).astimezone(tz)
    try:
        target = moment.replace(
            hour=REMINDER_HOUR,
            minute=REMINDER_MINUTE,
            second=0,
            microsecond=0,
        )
    except ValueError:
        logger.error(
            "Invalid PREMIUM_EXPIRY_REMINDER_HOUR/MINUTE: %s:%s",
            REMINDER_HOUR,
            REMINDER_MINUTE,
        )
        return 3600.0

    if moment >= target and not daily_run_already_done(moment=moment):
        return 1.0
    if moment >= target:
        target += datetime.timedelta(days=1)
    return max(1.0, (target - moment).total_seconds())


def _format_reminder_text(lang: str, *, days_left: int, expires_on: str, user_id: int) -> str:
    from subscription_plans import PLANS, PlanId

    free = PLANS[PlanId.FREE]
    founding_line = ""
    if user_claimed_founding(user_id):
        slot = user_claim_slot(user_id) or 0
        founding_line = t(lang, "premium_expiry_reminder_founding", slot=slot) + "\n"
    return founding_line + t(
        lang,
        "premium_expiry_reminder",
        days=days_left,
        date=expires_on,
        delay=free.strategy_alert_delay_minutes,
        free_top=free.whales_top_n,
    )


def _days_until_expiry_local(sub, *, now: datetime.datetime) -> int | None:
    """Календарные дни до expires_at в REMINDER_TIMEZONE."""
    if sub is None or not sub.expires_at or not sub.is_active_premium(now=now.astimezone(datetime.UTC)):
        return None
    try:
        exp = datetime.datetime.fromisoformat(sub.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=datetime.UTC)
    tz = _reminder_tz()
    local_now = now.astimezone(tz).date()
    local_exp = exp.astimezone(tz).date()
    return (local_exp - local_now).days


async def run_subscription_expiry_reminders(
    bot,
    log_fn: Callable[[str], None] | None = None,
) -> int:
    """Отправить напоминания за N дней до окончания Premium. Возвращает число отправок."""
    if not reminders_enabled():
        return 0

    tz = _reminder_tz()
    now = datetime.datetime.now(tz)
    if daily_run_already_done(moment=now):
        logger.info("Premium expiry reminders already sent for %s", run_date_key(now))
        return 0

    sent_count = 0
    due_found = False
    thresholds = set(REMINDER_DAYS_BEFORE)

    with json_rw_lock(STATE_FILE, default=_REMINDER_STATE_DEFAULT) as state:
        sent_map: dict = state.setdefault("sent", {})

        for sub in list_subscribers(active_premium_only=True):
            if _is_admin_user(sub.user_id):
                continue
            if not sub.expires_at:
                continue

            days_left = _days_until_expiry_local(sub, now=now)
            if days_left is None or days_left not in thresholds:
                continue

            expires_on = expiry_date_label(sub)
            if not expires_on:
                continue

            key = f"{sub.user_id}:{expires_on}:{days_left}"
            if key in sent_map:
                continue

            due_found = True
            lang = _user_lang(sub.user_id)
            text = _format_reminder_text(
                lang,
                days_left=days_left,
                expires_on=expires_on,
                user_id=sub.user_id,
            )
            try:
                await bot.send_message(
                    chat_id=sub.user_id,
                    text=text,
                    parse_mode="Markdown",
                )
                sent_map[key] = datetime.datetime.now(datetime.UTC).isoformat()
                sent_count += 1
            except Exception as exc:
                logger.warning(
                    "Premium expiry reminder failed user=%s days_left=%s: %s",
                    sub.user_id,
                    days_left,
                    exc,
                )

        if sent_count > 0 or not due_found:
            state["last_run_date"] = run_date_key(now)

    if due_found and sent_count == 0:
        logger.warning(
            "Premium expiry reminders: %s due but all sends failed — will retry",
            run_date_key(now),
        )

    if log_fn:
        log_fn(f"⏳ Premium expiry reminders sent: {sent_count}")
    logger.info("Premium expiry reminders sent=%s date=%s", sent_count, run_date_key(now))
    return sent_count


async def subscription_reminder_scheduler(
    bot,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Ежедневный цикл напоминаний об окончании Premium."""
    while True:
        if not reminders_enabled():
            await asyncio.sleep(3600)
            continue
        delay = seconds_until_next_run()
        logger.info("Premium expiry reminders next run in %.0f s", delay)
        await asyncio.sleep(delay)
        try:
            await run_subscription_expiry_reminders(bot, log_fn=log_fn)
        except Exception as exc:
            logger.exception("Premium expiry reminder scheduler error")
            if log_fn:
                log_fn(f"⚠️ Premium expiry reminder error: {exc}")
        await asyncio.sleep(60)


__all__ = [
    "REMINDER_DAYS_BEFORE",
    "REMINDER_HOUR",
    "REMINDER_MINUTE",
    "REMINDER_TIMEZONE",
    "daily_run_already_done",
    "reminders_enabled",
    "run_subscription_expiry_reminders",
    "seconds_until_next_run",
    "subscription_reminder_scheduler",
]
