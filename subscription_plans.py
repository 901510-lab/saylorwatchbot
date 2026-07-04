"""Тарифные планы SaylorWatchBot — День 16.

Источник истины для гейтинга (День 19) и /subscribe (День 20).
Сейчас multi-user доставка — `alert_delivery.py` (День 19).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from entities import get_entity
from models import EntityType


class PlanId(str, Enum):
    FREE = "free"
    PREMIUM = "premium"


# Рекомендуемая цена premium (фактическая — в env / Telegram Payments, День 18).
PREMIUM_PRICE_USD_MIN = 5
PREMIUM_PRICE_USD_MAX = 10
PREMIUM_PRICE_USD_DEFAULT = int(os.environ.get("PREMIUM_PRICE_USD", "7"))

# Задержка алертов для free (минуты). Premium = 0.
FREE_ALERT_DELAY_MINUTES = int(os.environ.get("FREE_ALERT_DELAY_MINUTES", "15"))


@dataclass(frozen=True)
class PlanFeatures:
    """Что включено в тариф."""

    strategy_alerts: bool
    strategy_alert_delay_minutes: int
    company_alerts: bool
    etf_alerts: bool
    image_cards: bool
    whales_command: bool
    whales_top_n: int
    site_monitor_alerts: bool  # strategy.com press / purchases


PLANS: dict[PlanId, PlanFeatures] = {
    PlanId.FREE: PlanFeatures(
        strategy_alerts=True,
        strategy_alert_delay_minutes=FREE_ALERT_DELAY_MINUTES,
        company_alerts=False,
        etf_alerts=False,
        image_cards=False,
        whales_command=True,
        whales_top_n=7,
        site_monitor_alerts=False,
    ),
    PlanId.PREMIUM: PlanFeatures(
        strategy_alerts=True,
        strategy_alert_delay_minutes=0,
        company_alerts=True,
        etf_alerts=True,
        image_cards=True,
        whales_command=True,
        whales_top_n=10,
        site_monitor_alerts=True,
    ),
}


def get_plan_features(plan: PlanId | str) -> PlanFeatures:
    if isinstance(plan, PlanId):
        pid = plan
    else:
        try:
            pid = PlanId(str(plan).strip().lower())
        except ValueError:
            pid = PlanId.FREE
    return PLANS[pid]


def entity_requires_premium(entity_id: str) -> bool:
    """True, если алерт по сущности только для premium."""
    entity = get_entity(entity_id)
    if entity is None:
        return True
    if entity.id == "strategy":
        return False
    if entity.type == EntityType.ETF:
        return True
    if entity.source == "coingecko_treasury":
        return True
    return entity.id != "strategy"


def alert_allowed_for_plan(entity_id: str, plan: PlanId | str) -> bool:
    """Можно ли слать алерт по entity_id на данном тарифе."""
    feats = get_plan_features(plan)
    eid = entity_id.strip().lower()
    if eid == "strategy":
        return feats.strategy_alerts
    entity = get_entity(eid)
    if entity and entity.type == EntityType.ETF:
        return feats.etf_alerts
    if entity and entity.source == "coingecko_treasury":
        return feats.company_alerts
    return feats.company_alerts


def card_allowed_for_plan(plan: PlanId | str) -> bool:
    return get_plan_features(plan).image_cards


def whales_top_n_for_plan(plan: PlanId | str) -> int:
    return get_plan_features(plan).whales_top_n


__all__ = [
    "PlanId",
    "PlanFeatures",
    "PLANS",
    "PREMIUM_PRICE_USD_MIN",
    "PREMIUM_PRICE_USD_MAX",
    "PREMIUM_PRICE_USD_DEFAULT",
    "FREE_ALERT_DELAY_MINUTES",
    "get_plan_features",
    "entity_requires_premium",
    "alert_allowed_for_plan",
    "card_allowed_for_plan",
    "whales_top_n_for_plan",
]
