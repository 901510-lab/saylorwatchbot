"""Акция: первым N пользователям — Premium на M дней бесплатно."""

from __future__ import annotations

import datetime
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from json_store import atomic_write_json
from subscribers import Subscriber, effective_plan, get_subscriber, grant_premium_days
from subscription_plans import PlanId

logger = logging.getLogger(__name__)

FOUNDING_PROMO_ENABLED = os.environ.get("FOUNDING_PROMO_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FOUNDING_PROMO_MAX = max(1, int(os.environ.get("FOUNDING_PROMO_MAX", "100")))
FOUNDING_PROMO_DAYS = max(1, int(os.environ.get("FOUNDING_PROMO_DAYS", "365")))
FOUNDING_PROMO_FILE = Path(os.environ.get("FOUNDING_PROMO_FILE", "founding_promo.json"))

FOUNDING_PROMO_CALLBACK = "subscribe:founding"
FOUNDING_PROMO_CONFIRM_CALLBACK = "subscribe:founding:confirm"
FOUNDING_PROMO_CANCEL_CALLBACK = "subscribe:founding:cancel"


@dataclass(frozen=True)
class FoundingPromoStatus:
    enabled: bool
    max_slots: int
    claimed: int
    remaining: int
    promo_days: int


@dataclass(frozen=True)
class FoundingClaimResult:
    status: str  # ok | disabled | exhausted | already_claimed | already_premium
    sub: Subscriber | None = None
    slot: int | None = None


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _parse_claims_file(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("founding_promo.json parse error: %s", exc)
        return []
    if not isinstance(data, dict):
        return []
    claims = data.get("claims")
    if not isinstance(claims, list):
        return []
    return [c for c in claims if isinstance(c, dict)]


def _load() -> dict[str, Any]:
    if not FOUNDING_PROMO_FILE.exists():
        return {"claims": []}
    try:
        return {"claims": _parse_claims_file(FOUNDING_PROMO_FILE.read_text(encoding="utf-8"))}
    except OSError as exc:
        logger.warning("founding_promo.json read error: %s", exc)
        return {"claims": []}


def _save(data: dict[str, Any]) -> None:
    atomic_write_json(FOUNDING_PROMO_FILE, data)


def _save_locked(handle, data: dict[str, Any]) -> None:
    """Deprecated — используйте _save (atomic_write_json)."""
    _save(data)


@contextmanager
def _promo_file_lock() -> Iterator[Any]:
    """Эксклюзивная блокировка founding_promo.json (fcntl на Linux)."""
    FOUNDING_PROMO_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FOUNDING_PROMO_FILE.exists():
        _save({"claims": []})
    handle = open(FOUNDING_PROMO_FILE, "r+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, AttributeError, OSError):
            pass
        yield handle
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, AttributeError, OSError):
            pass
        handle.close()


def promo_status() -> FoundingPromoStatus:
    claims = _load()["claims"]
    claimed = len(claims)
    remaining = max(0, FOUNDING_PROMO_MAX - claimed)
    return FoundingPromoStatus(
        enabled=FOUNDING_PROMO_ENABLED,
        max_slots=FOUNDING_PROMO_MAX,
        claimed=claimed,
        remaining=remaining,
        promo_days=FOUNDING_PROMO_DAYS,
    )


def promo_active() -> bool:
    st = promo_status()
    return st.enabled and st.remaining > 0


def user_claim_slot(user_id: int) -> int | None:
    for idx, raw in enumerate(_load()["claims"], start=1):
        if int(raw.get("user_id", 0)) == user_id:
            return idx
    return None


def user_claimed_founding(user_id: int) -> bool:
    return user_claim_slot(user_id) is not None


def eligible_for_founding(user_id: int) -> bool:
    if not promo_active():
        return False
    if user_claimed_founding(user_id):
        return False
    if effective_plan(user_id) == PlanId.PREMIUM:
        return False
    return True


def try_claim_founding_premium(user_id: int) -> FoundingClaimResult:
    if not FOUNDING_PROMO_ENABLED:
        return FoundingClaimResult("disabled")

    with _promo_file_lock() as handle:
        handle.seek(0)
        claims = _parse_claims_file(handle.read())

        for idx, raw in enumerate(claims, start=1):
            if int(raw.get("user_id", 0)) == user_id:
                sub = get_subscriber(user_id)
                return FoundingClaimResult("already_claimed", sub=sub, slot=idx)

        if effective_plan(user_id) == PlanId.PREMIUM:
            return FoundingClaimResult("already_premium", sub=get_subscriber(user_id))

        if len(claims) >= FOUNDING_PROMO_MAX:
            return FoundingClaimResult("exhausted")

        sub = grant_premium_days(user_id, FOUNDING_PROMO_DAYS)
        slot = len(claims) + 1
        claims.append(
            {
                "user_id": user_id,
                "slot": slot,
                "days": FOUNDING_PROMO_DAYS,
                "claimed_at": _utc_now_iso(),
            }
        )
        _save({"claims": claims})

    logger.info(
        "founding promo claimed user=%s slot=%s/%s days=%s",
        user_id,
        slot,
        FOUNDING_PROMO_MAX,
        FOUNDING_PROMO_DAYS,
    )
    return FoundingClaimResult("ok", sub=sub, slot=slot)


__all__ = [
    "FOUNDING_PROMO_CALLBACK",
    "FOUNDING_PROMO_CONFIRM_CALLBACK",
    "FOUNDING_PROMO_CANCEL_CALLBACK",
    "FOUNDING_PROMO_DAYS",
    "FOUNDING_PROMO_FILE",
    "FOUNDING_PROMO_MAX",
    "FoundingClaimResult",
    "FoundingPromoStatus",
    "eligible_for_founding",
    "promo_active",
    "promo_status",
    "try_claim_founding_premium",
    "user_claim_slot",
    "user_claimed_founding",
]
