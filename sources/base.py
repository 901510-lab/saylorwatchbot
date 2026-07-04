"""Базовый интерфейс источников данных для мульти-мониторинга.

Контракт (План, День 7): источник умеет `fetch()` и отдаёт данные в едином
формате `Holdings` (см. models.py).

Иерархия:
    BaseSource   — общий предок, метод `collect() -> list[Holdings]`
    Source       — источник ОДНОЙ сущности: `fetch() -> Holdings | None`
    MultiSource  — источник НЕСКОЛЬКИХ сущностей (один эндпоинт = много китов):
                   `fetch() -> list[Holdings]`

Монитор работает с любым источником единообразно через `collect()`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from models import EntityType, Holdings

logger = logging.getLogger(__name__)


class BaseSource(ABC):
    """Общий предок источников. Идентифицируется по `key`."""

    #: Уникальный ключ источника (для логов/конфига), напр. "strategy_site".
    key: str = "base"
    #: Тип сущностей, которые отдаёт источник.
    type: EntityType = EntityType.COMPANY
    #: Можно отключить источник, не удаляя его из реестра.
    enabled: bool = True

    @abstractmethod
    async def collect(self) -> list[Holdings]:
        """Вернуть список снимков `Holdings` (может быть пустым при ошибке)."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover — для логов
        return f"<{self.__class__.__name__} key={self.key!r} type={self.type.value}>"


class Source(BaseSource):
    """Источник одной сущности (напр. Strategy)."""

    @abstractmethod
    async def fetch(self) -> Holdings | None:
        """Получить текущий снимок резервов сущности или None при ошибке."""
        raise NotImplementedError

    async def collect(self) -> list[Holdings]:
        try:
            holdings = await self.fetch()
        except Exception as exc:  # noqa: BLE001 — изоляция сбоя источника
            logger.warning("Source %s failed: %s: %s", self.key, type(exc).__name__, exc)
            return []
        return [holdings] if holdings else []


class MultiSource(BaseSource):
    """Источник нескольких сущностей (напр. CoinGecko public_treasury)."""

    @abstractmethod
    async def fetch(self) -> list[Holdings]:
        """Получить снимки сразу по нескольким сущностям."""
        raise NotImplementedError

    async def collect(self) -> list[Holdings]:
        try:
            items = await self.fetch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MultiSource %s failed: %s: %s", self.key, type(exc).__name__, exc)
            return []
        return [h for h in (items or []) if h]


# === Реестр источников ===
_REGISTRY: dict[str, BaseSource] = {}


def register(source: BaseSource) -> BaseSource:
    """Зарегистрировать источник (идемпотентно по `key`)."""
    if not getattr(source, "key", None) or source.key == "base":
        raise ValueError(f"Источнику нужен уникальный key: {source!r}")
    _REGISTRY[source.key] = source
    return source


def unregister(key: str) -> None:
    _REGISTRY.pop(key, None)


def all_sources(include_disabled: bool = False) -> list[BaseSource]:
    """Все зарегистрированные источники (по умолчанию только включённые)."""
    return [s for s in _REGISTRY.values() if include_disabled or s.enabled]


async def collect_all(include_disabled: bool = False) -> list[Holdings]:
    """Опросить все источники и собрать единый список `Holdings`.

    Сбой одного источника не роняет остальные (изоляция в collect()).
    """
    result: list[Holdings] = []
    for source in all_sources(include_disabled=include_disabled):
        result.extend(await source.collect())
    return result


__all__ = [
    "BaseSource",
    "Source",
    "MultiSource",
    "register",
    "unregister",
    "all_sources",
    "collect_all",
]
