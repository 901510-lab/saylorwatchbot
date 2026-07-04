"""Per-entity baseline storage for multi-whale monitoring.

День 10 плана: отдельный baseline на каждую сущность (файл baselines/{id}.json),
а не один общий last_holdings.json.

Формат файла одной сущности:
    {
        "entity_id": "strategy",
        "name": "Strategy",
        "btc": 843738.0,
        "usd": 88150000000.0,
        "source": "strategy.com",
        "updated_at": "2026-06-07T12:00:00+00:00"
    }
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from json_store import atomic_write_json, file_lock, read_json_file

logger = logging.getLogger(__name__)

BASELINES_DIR = Path(os.environ.get("BASELINES_DIR", "baselines"))
# Старый одиночный файл MVP — используется только для миграции в baselines/strategy.json
LEGACY_HOLDINGS_FILE = Path(os.environ.get("HOLDINGS_STATE_FILE", "last_holdings.json"))


@dataclass
class Baseline:
    entity_id: str
    btc: float
    name: str | None = None
    usd: float | None = None
    source: str | None = None
    updated_at: str | None = None
    flow_date: str | None = None  # для ETF: дата последнего обработанного потока (YYYY-MM-DD)

    def to_dict(self) -> dict[str, Any]:
        """Совместим с форматом, который ожидает main.py (load_holdings_state)."""
        return {
            "entity_id": self.entity_id,
            "name": self.name or self.entity_id,
            "btc": self.btc,
            "usd": self.usd or 0.0,
            "source": self.source or "",
            "updated_at": self.updated_at or "",
        }


def _baseline_path(entity_id: str) -> Path:
    safe = entity_id.strip().lower().replace("/", "_")
    return BASELINES_DIR / f"{safe}.json"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def load_baseline(entity_id: str) -> Baseline | None:
    """Загрузить baseline одной сущности или None, если ещё не задан."""
    path = _baseline_path(entity_id)
    if not path.exists():
        return None
    try:
        data = read_json_file(path, default={})
        if not isinstance(data, dict):
            raise ValueError("ожидался объект JSON")
        return Baseline(
            entity_id=str(data.get("entity_id") or entity_id).lower(),
            btc=float(data.get("btc", 0)),
            name=data.get("name"),
            usd=float(data["usd"]) if data.get("usd") is not None else None,
            source=data.get("source"),
            updated_at=data.get("updated_at"),
            flow_date=data.get("flow_date"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Invalid baseline file %s: %s — baseline NOT reset", path, exc)
        return None


def save_baseline(
    entity_id: str,
    *,
    btc: float,
    name: str | None = None,
    usd: float | None = None,
    source: str | None = None,
    flow_date: str | None = None,
) -> Baseline:
    """Сохранить baseline сущности. Создаёт каталог baselines/ при необходимости."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    bl = Baseline(
        entity_id=entity_id.strip().lower(),
        btc=btc,
        name=name,
        usd=usd,
        source=source,
        updated_at=_utc_now_iso(),
        flow_date=flow_date,
    )
    path = _baseline_path(entity_id)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with file_lock(lock_path):
        atomic_write_json(path, asdict(bl))
    return bl


def delete_baseline(entity_id: str) -> bool:
    path = _baseline_path(entity_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def list_baselines() -> dict[str, Baseline]:
    """Все сохранённые baseline (entity_id -> Baseline)."""
    if not BASELINES_DIR.exists():
        return {}
    result: dict[str, Baseline] = {}
    for path in sorted(BASELINES_DIR.glob("*.json")):
        entity_id = path.stem
        bl = load_baseline(entity_id)
        if bl:
            result[bl.entity_id] = bl
    return result


def save_baseline_from_holdings(entity_id: str, holdings: dict[str, Any]) -> Baseline:
    """Удобная обёртка: сохранить baseline из dict holdings (как в main.py)."""
    return save_baseline(
        entity_id,
        btc=float(holdings.get("btc", 0)),
        name=str(holdings.get("name") or entity_id),
        usd=float(holdings["usd"]) if holdings.get("usd") is not None else None,
        source=str(holdings.get("source") or ""),
    )


def migrate_legacy_baseline(
    entity_id: str = "strategy",
    legacy_path: Path | str | None = None,
) -> bool:
    """Перенести старый last_holdings.json в baselines/{entity_id}.json (один раз).

    Возвращает True, если миграция выполнена или baseline уже существует.
    """
    if load_baseline(entity_id):
        return True

    path = Path(legacy_path) if legacy_path else LEGACY_HOLDINGS_FILE
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "btc" not in data:
            return False
        save_baseline_from_holdings(entity_id, data)
        logger.info("Migrated legacy baseline %s -> %s", path, _baseline_path(entity_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Legacy baseline migration failed (%s): %s", path, exc)
        return False


__all__ = [
    "Baseline",
    "BASELINES_DIR",
    "LEGACY_HOLDINGS_FILE",
    "load_baseline",
    "save_baseline",
    "save_baseline_from_holdings",
    "delete_baseline",
    "list_baselines",
    "migrate_legacy_baseline",
]
