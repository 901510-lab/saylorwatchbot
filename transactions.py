"""Журнал сделок buy/sell — Weekly Digest v2.

Запись при алертах компаний (Strategy + CoinGecko treasury).
ETF-потоки остаются в Farside-агрегации, не в этом журнале.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from json_store import atomic_write_json, json_rw_lock, read_json_file

logger = logging.getLogger(__name__)

_TRANSACTIONS_DEFAULT = {"transactions": []}

TRANSACTIONS_FILE = Path(os.environ.get("TRANSACTIONS_FILE", "transactions.json"))
TRANSACTIONS_RETAIN_DAYS = int(os.environ.get("TRANSACTIONS_RETAIN_DAYS", "90"))
TRANSACTIONS_MAX_ENTRIES = int(os.environ.get("TRANSACTIONS_MAX_ENTRIES", "2000"))

TradeSide = Literal["buy", "sell"]


@dataclass
class Transaction:
    id: str
    entity_id: str
    entity_name: str
    side: TradeSide
    btc: float
    price_usd: float
    usd_value: float
    date: str  # YYYY-MM-DD
    recorded_at: str
    source: str
    price_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradeSummary:
    buy_btc: float = 0.0
    sell_btc: float = 0.0
    buy_avg_price: float | None = None
    sell_avg_price: float | None = None
    buy_trades: int = 0
    sell_trades: int = 0

    @property
    def net_btc(self) -> float:
        return self.buy_btc - self.sell_btc


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _load_raw() -> list[dict[str, Any]]:
    if not TRANSACTIONS_FILE.exists():
        return []
    try:
        data = read_json_file(TRANSACTIONS_FILE, default=_TRANSACTIONS_DEFAULT)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("transactions.json read error: %s", exc)
        return []
    if isinstance(data, dict) and isinstance(data.get("transactions"), list):
        return [x for x in data["transactions"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _save_raw(rows: list[dict[str, Any]]) -> None:
    atomic_write_json(TRANSACTIONS_FILE, {"transactions": rows})


def _parse_tx(raw: dict[str, Any]) -> Transaction | None:
    try:
        side = str(raw.get("side", "")).lower()
        if side not in {"buy", "sell"}:
            return None
        btc = float(raw.get("btc", 0))
        if btc <= 0:
            return None
        return Transaction(
            id=str(raw.get("id") or uuid.uuid4().hex),
            entity_id=str(raw.get("entity_id", "")).lower(),
            entity_name=str(raw.get("entity_name") or raw.get("entity_id") or ""),
            side=side,  # type: ignore[arg-type]
            btc=btc,
            price_usd=float(raw.get("price_usd") or 0),
            usd_value=float(raw.get("usd_value") or 0),
            date=str(raw.get("date") or "")[:10],
            recorded_at=str(raw.get("recorded_at") or _utc_now_iso()),
            source=str(raw.get("source") or ""),
            price_estimated=bool(raw.get("price_estimated", False)),
        )
    except (TypeError, ValueError):
        return None


def list_transactions() -> list[Transaction]:
    result: list[Transaction] = []
    for raw in _load_raw():
        tx = _parse_tx(raw)
        if tx:
            result.append(tx)
    return result


def _dedupe_key(entity_id: str, side: str, btc: float, date: str) -> str:
    return f"{entity_id}:{side}:{date}:{btc:.4f}"


def _prune(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=TRANSACTIONS_RETAIN_DAYS)
    ).isoformat()
    kept = [r for r in rows if str(r.get("recorded_at", "")) >= cutoff]
    if len(kept) > TRANSACTIONS_MAX_ENTRIES:
        kept = kept[-TRANSACTIONS_MAX_ENTRIES:]
    return kept


def record_trade(
    *,
    entity_id: str,
    entity_name: str,
    side: TradeSide,
    btc: float,
    price_usd: float,
    date: str,
    source: str,
    price_estimated: bool = False,
) -> Transaction | None:
    """Добавить сделку в журнал (идемпотентно по entity+side+date+btc)."""
    btc = abs(float(btc))
    if btc <= 0:
        return None

    price = max(0.0, float(price_usd))
    usd_value = btc * price if price else 0.0
    day = (date or datetime.date.today().isoformat())[:10]
    eid = entity_id.strip().lower()

    with json_rw_lock(TRANSACTIONS_FILE, default=_TRANSACTIONS_DEFAULT) as blob:
        rows = blob.get("transactions") if isinstance(blob.get("transactions"), list) else []
        rows = [x for x in rows if isinstance(x, dict)]
        key = _dedupe_key(eid, side, btc, day)
        for raw in rows:
            existing = _parse_tx(raw)
            if existing and _dedupe_key(existing.entity_id, existing.side, existing.btc, existing.date) == key:
                return existing

        tx = Transaction(
            id=uuid.uuid4().hex[:12],
            entity_id=eid,
            entity_name=entity_name,
            side=side,
            btc=btc,
            price_usd=price,
            usd_value=usd_value,
            date=day,
            recorded_at=_utc_now_iso(),
            source=source,
            price_estimated=price_estimated,
        )
        rows.append(tx.to_dict())
        blob["transactions"] = _prune(rows)
    logger.info(
        "trade recorded entity=%s side=%s btc=%s price=%s estimated=%s",
        eid,
        side,
        btc,
        price,
        price_estimated,
    )
    return tx


def record_trade_alert(
    *,
    entity_id: str,
    entity_name: str,
    increased: bool,
    delta_btc: float,
    delta_usd: float,
    date: str,
    buy_price: float = 0.0,
    source: str = "alert",
    price_estimated: bool | None = None,
) -> Transaction | None:
    """Запись из send_alert_with_card (компании, не ETF)."""
    btc = abs(float(delta_btc))
    if btc <= 0:
        return None

    if increased:
        price = float(buy_price) if buy_price else (
            abs(delta_usd) / btc if delta_usd else 0.0
        )
        estimated = price_estimated if price_estimated is not None else (buy_price <= 0)
        return record_trade(
            entity_id=entity_id,
            entity_name=entity_name,
            side="buy",
            btc=btc,
            price_usd=price,
            date=date,
            source=source,
            price_estimated=estimated,
        )

    price = abs(delta_usd) / btc if delta_usd else 0.0
    estimated = price_estimated if price_estimated is not None else True
    return record_trade(
        entity_id=entity_id,
        entity_name=entity_name,
        side="sell",
        btc=btc,
        price_usd=price,
        date=date,
        source=source,
        price_estimated=estimated,
    )


def summarize_trades(
    period_start: datetime.date,
    period_end: datetime.date,
) -> dict[str, TradeSummary]:
    """Агрегация buy/sell за период по entity_id."""
    start = period_start.isoformat()
    end = period_end.isoformat()
    by_entity: dict[str, TradeSummary] = {}
    buy_weight: dict[str, float] = {}
    buy_usd: dict[str, float] = {}
    sell_weight: dict[str, float] = {}
    sell_usd: dict[str, float] = {}

    for tx in list_transactions():
        if not tx.date or tx.date < start or tx.date > end:
            continue
        summary = by_entity.setdefault(tx.entity_id, TradeSummary())
        if tx.side == "buy":
            summary.buy_btc += tx.btc
            summary.buy_trades += 1
            buy_weight[tx.entity_id] = buy_weight.get(tx.entity_id, 0.0) + tx.btc
            buy_usd[tx.entity_id] = buy_usd.get(tx.entity_id, 0.0) + tx.btc * tx.price_usd
        else:
            summary.sell_btc += tx.btc
            summary.sell_trades += 1
            sell_weight[tx.entity_id] = sell_weight.get(tx.entity_id, 0.0) + tx.btc
            sell_usd[tx.entity_id] = sell_usd.get(tx.entity_id, 0.0) + tx.btc * tx.price_usd

    for eid, summary in by_entity.items():
        if buy_weight.get(eid, 0) > 0:
            summary.buy_avg_price = buy_usd[eid] / buy_weight[eid]
        if sell_weight.get(eid, 0) > 0:
            summary.sell_avg_price = sell_usd[eid] / sell_weight[eid]

    return by_entity


def largest_trade_in_period(
    period_start: datetime.date,
    period_end: datetime.date,
) -> tuple[str, float, TradeSide] | None:
    """Крупнейшая сделка недели (по BTC) для whale of the week."""
    start = period_start.isoformat()
    end = period_end.isoformat()
    best: Transaction | None = None
    for tx in list_transactions():
        if not tx.date or tx.date < start or tx.date > end:
            continue
        if best is None or tx.btc > best.btc:
            best = tx
    if best is None:
        return None
    return best.entity_name, best.btc, best.side


__all__ = [
    "TRANSACTIONS_FILE",
    "Transaction",
    "TradeSummary",
    "TradeSide",
    "list_transactions",
    "record_trade",
    "record_trade_alert",
    "summarize_trades",
    "largest_trade_in_period",
]
