"""Реестр отслеживаемых сущностей (китов) из entities.json.

День 9 плана: единый список китов с их источниками и индивидуальными
порогами алертов. Источник истины — файл entities.json; этот модуль читает
его в типизированные `EntityConfig` с безопасными значениями по умолчанию.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from models import EntityType

logger = logging.getLogger(__name__)

ENTITIES_FILE = Path(os.environ.get("ENTITIES_FILE", "entities.json"))
DEFAULT_MIN_BTC_CHANGE = 1.0

# Резервный реестр, если entities.json отсутствует/битый — чтобы бот не падал
# и продолжал следить хотя бы за Strategy (текущее поведение MVP).
_FALLBACK = {
    "default_min_btc_change": DEFAULT_MIN_BTC_CHANGE,
    "entities": [
        {
            "id": "strategy",
            "name": "Strategy",
            "type": "company",
            "ticker": "MSTR",
            "source": "strategy",
            "min_btc_change": 1,
            "enabled": True,
        }
    ],
}


@dataclass(frozen=True)
class EntityConfig:
    """Конфиг одной отслеживаемой сущности."""

    id: str
    name: str
    type: EntityType
    source: str
    min_btc_change: float = DEFAULT_MIN_BTC_CHANGE
    ticker: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_threshold: float) -> "EntityConfig":
        name = str(data.get("name") or data.get("id") or "Entity")
        entity_id = str(data.get("id") or name).strip().lower()
        raw_threshold = data.get("min_btc_change", default_threshold)
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError):
            threshold = default_threshold
        return cls(
            id=entity_id,
            name=name,
            type=EntityType.from_str(data.get("type")),
            source=str(data.get("source") or ""),
            min_btc_change=threshold if threshold > 0 else default_threshold,
            ticker=(str(data["ticker"]) if data.get("ticker") else None),
            enabled=bool(data.get("enabled", True)),
        )


def _load_raw(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("entities"), list):
            raise ValueError("ожидался объект с полем 'entities' (список)")
        return data
    except FileNotFoundError:
        logger.warning("entities.json не найден (%s) — использую резервный реестр", path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка чтения %s: %s — использую резервный реестр", path, exc)
    return _FALLBACK


def load_entities(path: Path | str | None = None) -> list[EntityConfig]:
    """Загрузить все сущности из реестра (включая отключённые)."""
    data = _load_raw(Path(path) if path else ENTITIES_FILE)
    try:
        default_threshold = float(data.get("default_min_btc_change", DEFAULT_MIN_BTC_CHANGE))
    except (TypeError, ValueError):
        default_threshold = DEFAULT_MIN_BTC_CHANGE

    result: list[EntityConfig] = []
    seen: set[str] = set()
    for item in data.get("entities", []):
        if not isinstance(item, dict):
            continue
        cfg = EntityConfig.from_dict(item, default_threshold)
        if cfg.id in seen:
            logger.warning("Дубликат id сущности: %s — пропускаю", cfg.id)
            continue
        seen.add(cfg.id)
        result.append(cfg)
    return result


def enabled_entities(path: Path | str | None = None) -> list[EntityConfig]:
    """Только включённые сущности (для мониторинга)."""
    return [e for e in load_entities(path) if e.enabled]


def get_entity(entity_id: str, path: Path | str | None = None) -> EntityConfig | None:
    eid = entity_id.strip().lower()
    for e in load_entities(path):
        if e.id == eid:
            return e
    return None


def find_entity_by_name(name: str, path: Path | str | None = None) -> EntityConfig | None:
    """Найти сущность по отображаемому имени (для алертов/карточек)."""
    needle = name.strip().lower()
    for e in load_entities(path):
        if e.name.lower() == needle:
            return e
    return None


__all__ = [
    "EntityConfig",
    "load_entities",
    "enabled_entities",
    "get_entity",
    "find_entity_by_name",
    "ENTITIES_FILE",
    "DEFAULT_MIN_BTC_CHANGE",
]
