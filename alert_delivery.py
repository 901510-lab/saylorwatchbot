"""Доставка алертов по тарифу — День 19.

Admin (X_CHAT_ID) — всё сразу + карточки.
Premium — instant + карточки (если разрешено для entity).
Free — только Strategy (и без site-only); текст без карточки; задержка FREE_ALERT_DELAY_MINUTES.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from subscribers import effective_plan, list_subscribers
from subscription_plans import (
    FREE_ALERT_DELAY_MINUTES,
    PlanId,
    alert_allowed_for_plan,
    card_allowed_for_plan,
    get_plan_features,
)
from user_lang_prefs import get_user_lang

logger = logging.getLogger(__name__)

ENABLE_SUBSCRIPTION_GATING = os.environ.get("ENABLE_SUBSCRIPTION_GATING", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@dataclass(frozen=True)
class AlertRecipient:
    user_id: int
    plan: PlanId
    delay_seconds: int
    include_card: bool


def gating_enabled() -> bool:
    return ENABLE_SUBSCRIPTION_GATING


def list_known_user_ids() -> list[int]:
    """User id из bot_stats и user_languages (нажимали /start или выбирали язык)."""
    ids: set[int] = set()
    try:
        from bot_analytics import _load_stats

        for key in _load_stats().get("users", {}):
            try:
                ids.add(int(key))
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        logger.debug("list_known_user_ids bot_stats: %s", exc)

    try:
        from user_lang_prefs import USER_LANG_FILE

        if USER_LANG_FILE.exists():
            import json

            data = json.loads(USER_LANG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in data:
                    try:
                        ids.add(int(key))
                    except (TypeError, ValueError):
                        continue
    except Exception as exc:
        logger.debug("list_known_user_ids user_languages: %s", exc)

    try:
        for sub in list_subscribers():
            ids.add(sub.user_id)
    except Exception as exc:
        logger.debug("list_known_user_ids subscribers: %s", exc)

    return sorted(ids)


def _allowed_for_plan(entity_id: str, plan: PlanId, *, site_monitor: bool) -> bool:
    if site_monitor:
        return get_plan_features(plan).site_monitor_alerts
    return alert_allowed_for_plan(entity_id, plan)


def resolve_recipients(
    entity_id: str,
    admin_user_id: int,
    *,
    site_monitor: bool = False,
    abs_delta_btc: float = 0.0,
) -> list[AlertRecipient]:
    """Кому слать алерт по entity_id."""
    from free_tier_perks import free_strategy_card_allowed

    recipients: list[AlertRecipient] = []
    seen: set[int] = set()

    def add(uid: int, plan: PlanId, delay_seconds: int, include_card: bool) -> None:
        if uid in seen:
            return
        seen.add(uid)
        recipients.append(
            AlertRecipient(
                user_id=uid,
                plan=plan,
                delay_seconds=delay_seconds,
                include_card=include_card,
            )
        )

    add(admin_user_id, PlanId.PREMIUM, 0, True)

    for sub in list_subscribers(active_premium_only=True):
        if sub.user_id == admin_user_id:
            continue
        if not _allowed_for_plan(entity_id, PlanId.PREMIUM, site_monitor=site_monitor):
            continue
        add(sub.user_id, PlanId.PREMIUM, 0, card_allowed_for_plan(PlanId.PREMIUM))

    if site_monitor:
        return recipients

    if not alert_allowed_for_plan(entity_id, PlanId.FREE):
        return recipients

    delay = max(0, int(FREE_ALERT_DELAY_MINUTES)) * 60
    abs_btc = abs(float(abs_delta_btc or 0.0))
    for uid in list_known_user_ids():
        if uid in seen:
            continue
        if effective_plan(uid) == PlanId.PREMIUM:
            continue
        include_card = free_strategy_card_allowed(
            uid,
            entity_id=entity_id,
            abs_delta_btc=abs_btc,
            plan=PlanId.FREE,
        )
        add(uid, PlanId.FREE, delay, include_card)

    return recipients


async def _send_text(bot, chat_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text)


async def _send_photo(bot, chat_id: int, photo, caption: str) -> None:
    if hasattr(photo, "seek"):
        photo.seek(0)
    await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)


async def dispatch_alert(
    bot,
    admin_user_id: int,
    *,
    entity_id: str,
    site_monitor: bool = False,
    text_for_lang: Callable[[str], str],
    photo,
    admin_lang: str,
    donate_footer_for_lang: Callable[[str], str],
    abs_delta_btc: float = 0.0,
    trade_journal: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Разослать алерт. Возвращает (instant_delivered, queued)."""
    if not gating_enabled():
        caption = text_for_lang(admin_lang) + donate_footer_for_lang(admin_lang)
        try:
            if photo is not None:
                try:
                    await _send_photo(bot, admin_user_id, photo, caption)
                    return 1, 0
                except Exception as exc:
                    logger.warning("legacy card send failed: %s", exc)
            await _send_text(bot, admin_user_id, caption)
            return 1, 0
        except Exception as exc:
            logger.warning("legacy alert send failed: %s", exc)
            return 0, 0

    recipients = resolve_recipients(
        entity_id,
        admin_user_id,
        site_monitor=site_monitor,
        abs_delta_btc=abs_delta_btc,
    )
    if not recipients:
        return 0, 0

    instant = 0
    queued = 0
    journal_attached = False
    abs_btc = abs(float(abs_delta_btc or 0.0))

    for recipient in recipients:
        lang = admin_lang if recipient.user_id == admin_user_id else get_user_lang(recipient.user_id)
        body = text_for_lang(lang)
        footer = donate_footer_for_lang(lang)
        caption = body + footer
        text_only = body + footer

        if recipient.delay_seconds > 0:
            from free_alert_queue import enqueue_delayed_alert

            queue_journal = None
            if trade_journal and not journal_attached:
                queue_journal = trade_journal
                journal_attached = True
            enqueue_delayed_alert(
                user_id=recipient.user_id,
                text=text_only,
                delay_seconds=recipient.delay_seconds,
                entity_id=entity_id,
                photo=photo,
                include_card=recipient.include_card and photo is not None,
                abs_delta_btc=abs_btc,
                trade_journal=queue_journal,
            )
            queued += 1
            logger.info(
                "alert queued user=%s plan=%s delay=%ss entity=%s",
                recipient.user_id,
                recipient.plan.value,
                recipient.delay_seconds,
                entity_id,
            )
            continue

        try:
            if recipient.include_card and photo is not None:
                try:
                    await _send_photo(bot, recipient.user_id, photo, caption)
                except Exception as photo_exc:
                    logger.warning(
                        "alert card failed user=%s, fallback text: %s",
                        recipient.user_id,
                        photo_exc,
                    )
                    await _send_text(bot, recipient.user_id, text_only)
                else:
                    from free_tier_perks import record_free_strategy_card

                    record_free_strategy_card(
                        recipient.user_id,
                        abs_delta_btc=abs_btc,
                    )
            else:
                await _send_text(bot, recipient.user_id, text_only)
            instant += 1
            logger.info(
                "alert sent user=%s plan=%s card=%s entity=%s",
                recipient.user_id,
                recipient.plan.value,
                recipient.include_card and photo is not None,
                entity_id,
            )
        except Exception as exc:
            logger.warning(
                "alert delivery failed user=%s: %s",
                recipient.user_id,
                exc,
            )

    return instant, queued


__all__ = [
    "ENABLE_SUBSCRIPTION_GATING",
    "AlertRecipient",
    "gating_enabled",
    "list_known_user_ids",
    "resolve_recipients",
    "dispatch_alert",
]
