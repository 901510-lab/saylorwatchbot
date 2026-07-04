"""Очередь отложенных free-алертов — переживает рестарт бота."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from json_store import json_rw_lock, read_json_file

logger = logging.getLogger(__name__)

QUEUE_FILE = Path(os.environ.get("FREE_ALERT_QUEUE_FILE", "free_alert_queue.json"))
CARD_CACHE_DIR = Path(os.environ.get("FREE_ALERT_CARD_CACHE_DIR", "free_alert_card_cache"))
MAX_QUEUE_ITEMS = max(100, int(os.environ.get("FREE_ALERT_QUEUE_MAX_ITEMS", "5000")))


def _default_queue() -> dict[str, Any]:
    return {"items": []}


def _parse_send_at(raw: str) -> datetime.datetime | None:
    try:
        dt = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or "")


def _split_due_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = datetime.datetime.now(datetime.UTC)
    due: list[dict[str, Any]] = []
    keep: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("in_flight"):
            keep.append(item)
            continue
        send_at = _parse_send_at(str(item.get("send_at") or ""))
        if send_at is None:
            continue
        if send_at <= now:
            item["in_flight"] = True
            due.append(item)
            keep.append(item)
        else:
            keep.append(item)
    return due, keep


def _store_card_photo(photo) -> str | None:
    if photo is None:
        return None
    CARD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CARD_CACHE_DIR / f"{uuid.uuid4().hex}.png"
    if hasattr(photo, "read"):
        data = photo.read()
        if hasattr(photo, "seek"):
            photo.seek(0)
    elif isinstance(photo, (bytes, bytearray)):
        data = bytes(photo)
    else:
        return None
    if not data:
        return None
    path.write_bytes(data)
    return str(path)


def _remove_card_file(path_str: str | None) -> None:
    if not path_str:
        return
    try:
        Path(path_str).unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("card cache unlink %s: %s", path_str, exc)


def _apply_post_delivery_hooks(item: dict[str, Any]) -> None:
    """Journal / free perks — только после успешной отправки."""
    uid = int(item["user_id"])
    abs_btc = float(item.get("abs_delta_btc") or 0.0)
    if item.get("include_card"):
        from free_tier_perks import record_free_strategy_card

        record_free_strategy_card(uid, abs_delta_btc=abs_btc)
    journal = item.get("trade_journal")
    if isinstance(journal, dict) and journal:
        try:
            from transactions import record_trade_alert

            record_trade_alert(
                entity_id=str(journal["entity_id"]),
                entity_name=str(journal["entity_name"]),
                increased=bool(journal["increased"]),
                delta_btc=float(journal["delta_btc"]),
                delta_usd=float(journal["delta_usd"]),
                date=str(journal["date"]),
                buy_price=float(journal.get("buy_price") or 0.0),
                source=str(journal.get("source") or ""),
                price_estimated=journal.get("price_estimated"),
            )
        except Exception as exc:
            logger.warning("free queue trade journal failed: %s", exc)


def _trim_queue_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ограничить размер очереди; удалить PNG у отброшенных элементов."""
    if len(items) <= MAX_QUEUE_ITEMS:
        return items
    dropped = items[: len(items) - MAX_QUEUE_ITEMS]
    for item in dropped:
        _remove_card_file(str(item.get("card_path") or "") or None)
    logger.warning(
        "free alert queue trimmed %d oldest item(s) (max=%d)",
        len(dropped),
        MAX_QUEUE_ITEMS,
    )
    return items[-MAX_QUEUE_ITEMS:]


def enqueue_delayed_alert(
    *,
    user_id: int,
    text: str,
    delay_seconds: int,
    entity_id: str,
    photo=None,
    include_card: bool = False,
    abs_delta_btc: float = 0.0,
    trade_journal: dict[str, Any] | None = None,
) -> None:
    send_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=max(0, delay_seconds))
    card_path = _store_card_photo(photo) if include_card else None
    item: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "text": text,
        "entity_id": entity_id,
        "send_at": send_at.isoformat(),
        "include_card": bool(include_card and card_path),
        "card_path": card_path,
        "abs_delta_btc": abs(float(abs_delta_btc or 0.0)),
    }
    if trade_journal:
        item["trade_journal"] = trade_journal
    with json_rw_lock(QUEUE_FILE, default=_default_queue()) as data:
        items = data.setdefault("items", [])
        items.append(item)
        data["items"] = _trim_queue_items(items)


async def flush_due_alerts(bot) -> int:
    """Отправить алерты, у которых наступило время. Возвращает число отправок."""
    to_send: list[dict[str, Any]] = []
    with json_rw_lock(QUEUE_FILE, default=_default_queue()) as data:
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        due, keep = _split_due_items(items)
        data["items"] = keep
        to_send = list(due)

    sent = 0
    succeeded_ids: set[str] = set()
    failed_ids: set[str] = set()
    for item in to_send:
        uid = int(item["user_id"])
        text = str(item.get("text") or "")
        card_path = item.get("card_path")
        use_card = bool(item.get("include_card")) and card_path
        item_id = _item_id(item)
        delivered = False
        try:
            if use_card:
                path = Path(str(card_path))
                if path.is_file():
                    with path.open("rb") as fh:
                        await bot.send_photo(chat_id=uid, photo=fh, caption=text)
                else:
                    await bot.send_message(chat_id=uid, text=text)
            else:
                await bot.send_message(chat_id=uid, text=text)
            _apply_post_delivery_hooks(item)
            delivered = True
            sent += 1
            if item_id:
                succeeded_ids.add(item_id)
            logger.info(
                "free alert queue delivered user=%s entity=%s card=%s",
                uid,
                item.get("entity_id"),
                use_card,
            )
        except Exception as exc:
            logger.warning("free alert queue failed user=%s: %s", uid, exc)
            if item_id:
                failed_ids.add(item_id)
        finally:
            if delivered:
                _remove_card_file(str(card_path) if card_path else None)

    with json_rw_lock(QUEUE_FILE, default=_default_queue()) as data:
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        updated: list[dict[str, Any]] = []
        for item in items:
            iid = _item_id(item)
            if iid and iid in succeeded_ids:
                continue
            if iid and iid in failed_ids:
                item.pop("in_flight", None)
            updated.append(item)
        data["items"] = _trim_queue_items(updated)

    return sent


async def free_alert_queue_scheduler(bot, log_fn=None) -> None:
    while True:
        try:
            n = await flush_due_alerts(bot)
            if n and log_fn:
                log_fn(f"📬 Free alert queue delivered: {n}")
        except Exception as exc:
            logger.exception("free alert queue error: %s", exc)
        await asyncio.sleep(60)


__all__ = [
    "QUEUE_FILE",
    "CARD_CACHE_DIR",
    "enqueue_delayed_alert",
    "flush_due_alerts",
    "free_alert_queue_scheduler",
]
