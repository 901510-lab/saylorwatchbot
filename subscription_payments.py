"""Telegram Stars — оплата Premium (День 18).

Цифровые товары только в XTR: send_invoice без provider_token.
После successful_payment → grant_premium_days() в subscribers.py.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from telegram import Bot, LabeledPrice, Update
from telegram.ext import ContextTypes

from json_store import atomic_write_json, file_lock, json_rw_lock, read_json_file
from subscribers import get_subscriber, grant_premium_days

logger = logging.getLogger(__name__)

_PAYMENTS_DEFAULT = {"payments": {}}

STARS_CURRENCY = "XTR"
SUBSCRIBE_PAY_CALLBACK = "subscribe:pay"
PREMIUM_STARS_PRICE = max(1, int(os.environ.get("PREMIUM_STARS", "350")))
PREMIUM_BILLING_DAYS = max(1, int(os.environ.get("PREMIUM_BILLING_DAYS", "30")))
ENABLE_STARS_PAYMENTS = os.environ.get("ENABLE_STARS_PAYMENTS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PAYMENTS_FILE = Path(os.environ.get("PAYMENTS_FILE", "payments.json"))

_PAYLOAD_RE = re.compile(r"^sw:premium:(?P<days>\d+):(?P<user_id>\d+)$")


def build_invoice_payload(user_id: int, days: int | None = None) -> str:
    billing_days = days if days is not None else PREMIUM_BILLING_DAYS
    return f"sw:premium:{billing_days}:{user_id}"


def parse_invoice_payload(payload: str) -> tuple[int, int] | None:
    match = _PAYLOAD_RE.match((payload or "").strip())
    if not match:
        return None
    return int(match.group("user_id")), int(match.group("days"))


def stars_payments_enabled() -> bool:
    return ENABLE_STARS_PAYMENTS


def _normalize_payments(data: object) -> dict[str, dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("payments"), dict):
        return {str(k): v for k, v in data["payments"].items() if isinstance(v, dict)}
    return {}


def _load_payments() -> dict[str, dict[str, Any]]:
    if not PAYMENTS_FILE.exists():
        return {}
    try:
        data = read_json_file(PAYMENTS_FILE, default=_PAYMENTS_DEFAULT)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("payments.json read error: %s", exc)
        return {}
    return _normalize_payments(data)


def _save_payments(payments: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(PAYMENTS_FILE, {"payments": payments})


def payment_already_processed(charge_id: str) -> bool:
    return charge_id in _load_payments()


def record_payment(
    charge_id: str,
    *,
    user_id: int,
    days: int,
    stars: int,
    payload: str,
    _skip_lock: bool = False,
) -> None:
    def _write(payments: dict[str, dict[str, Any]]) -> None:
        payments[charge_id] = {
            "user_id": user_id,
            "days": days,
            "stars": stars,
            "payload": payload,
            "processed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        _save_payments(payments)

    if _skip_lock:
        _write(_load_payments())
        return

    with json_rw_lock(PAYMENTS_FILE, default=_PAYMENTS_DEFAULT) as blob:
        payments = _normalize_payments(blob)
        payments[charge_id] = {
            "user_id": user_id,
            "days": days,
            "stars": stars,
            "payload": payload,
            "processed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        blob.clear()
        blob.update({"payments": payments})


def payment_summary() -> tuple[int, int]:
    """Число успешных оплат и сумма Stars."""
    payments = _load_payments()
    stars = sum(int(p.get("stars", 0)) for p in payments.values())
    return len(payments), stars


def validate_pre_checkout(
    *,
    payload: str,
    currency: str,
    total_amount: int,
    buyer_user_id: int,
) -> tuple[bool, str | None]:
    if currency != STARS_CURRENCY:
        return False, "invalid_currency"
    if total_amount != PREMIUM_STARS_PRICE:
        return False, "invalid_amount"
    parsed = parse_invoice_payload(payload)
    if parsed is None:
        return False, "invalid_payload"
    user_id, days = parsed
    if user_id != buyer_user_id:
        return False, "user_mismatch"
    if days != PREMIUM_BILLING_DAYS:
        return False, "invalid_days"
    return True, None


async def send_premium_invoice(
    bot: Bot,
    chat_id: int,
    user_id: int,
    *,
    title: str,
    description: str,
    price_label: str,
):
    payload = build_invoice_payload(user_id)
    prices = [LabeledPrice(price_label, PREMIUM_STARS_PRICE)]
    logger.info(
        "send_invoice request chat=%s user=%s stars=%s payload=%s",
        chat_id,
        user_id,
        PREMIUM_STARS_PRICE,
        payload,
    )
    # ptb 20.6: provider_token обязателен в сигнатуре; для XTR — пустая строка.
    message = await bot.send_invoice(
        chat_id,
        title,
        description,
        payload,
        "",
        STARS_CURRENCY,
        prices,
    )
    logger.info("send_invoice ok chat=%s message_id=%s", chat_id, message.message_id)
    return message


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query is None:
        return

    ok, reason = validate_pre_checkout(
        payload=query.invoice_payload,
        currency=query.currency,
        total_amount=query.total_amount,
        buyer_user_id=query.from_user.id,
    )
    if not ok:
        logger.warning(
            "pre_checkout rejected user=%s reason=%s payload=%s",
            query.from_user.id,
            reason,
            query.invoice_payload,
        )
        await query.answer(ok=False, error_message="Payment could not be verified.")
        return

    await query.answer(ok=True)


def fulfill_premium_payment(payment, buyer_user_id: int):
    """Проверить платёж и выдать premium. None — если уже обработан или невалиден."""
    charge_id = payment.telegram_payment_charge_id

    parsed = parse_invoice_payload(payment.invoice_payload)
    if parsed is None:
        logger.error("successful_payment with bad payload: %s", payment.invoice_payload)
        return None

    user_id, days = parsed
    if buyer_user_id != user_id:
        logger.error("payment user mismatch: payer=%s payload=%s", buyer_user_id, user_id)
        return None

    ok, reason = validate_pre_checkout(
        payload=payment.invoice_payload,
        currency=payment.currency,
        total_amount=payment.total_amount,
        buyer_user_id=user_id,
    )
    if not ok:
        logger.error("successful_payment failed validation: %s", reason)
        return None

    with file_lock(PAYMENTS_FILE):
        if payment_already_processed(charge_id):
            logger.info("duplicate payment ignored: %s", charge_id)
            return get_subscriber(buyer_user_id)
        record_payment(
            charge_id,
            user_id=user_id,
            days=days,
            stars=payment.total_amount,
            payload=payment.invoice_payload,
            _skip_lock=True,
        )
        sub = grant_premium_days(user_id, days)
    logger.info(
        "premium granted user=%s days=%s stars=%s charge=%s",
        user_id,
        days,
        payment.total_amount,
        charge_id,
    )
    return sub


__all__ = [
    "STARS_CURRENCY",
    "SUBSCRIBE_PAY_CALLBACK",
    "PREMIUM_STARS_PRICE",
    "PREMIUM_BILLING_DAYS",
    "ENABLE_STARS_PAYMENTS",
    "PAYMENTS_FILE",
    "build_invoice_payload",
    "parse_invoice_payload",
    "stars_payments_enabled",
    "payment_already_processed",
    "record_payment",
    "payment_summary",
    "validate_pre_checkout",
    "send_premium_invoice",
    "pre_checkout_handler",
    "fulfill_premium_payment",
]
