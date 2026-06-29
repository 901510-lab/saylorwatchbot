"""Источник Strategy (Michael Saylor) в едином формате `Holdings`.

День 8 плана: оборачиваем существующий парсер (strategy.com + CoinGecko +
legacy JSON) в источник `Source`, не дублируя логику получения данных.

Подход: внедряем `stats_provider` — асинхронную функцию, возвращающую тот же
dict, что и `main.build_treasury_stats()`. Источник лишь приводит его к модели
`Holdings`. Так нет циклического импорта и дублирования парсинга, а main.py
остаётся рабочим без изменений.
"""

from __future__ import annotations

import datetime
from typing import Any, Awaitable, Callable

from models import EntityType, Holdings
from sources.base import Source

#: Тип провайдера статистики: async () -> dict | None (формат build_treasury_stats).
StatsProvider = Callable[[], Awaitable[dict[str, Any] | None]]


def _pos(value: Any) -> float | None:
    """float > 0 или None (в боте 0.0 означает «нет данных»)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def holdings_from_stats(
    stats: dict[str, Any],
    *,
    entity: str | None = None,
    change: float = 0.0,
    date: str | None = None,
) -> Holdings:
    """Преобразует dict из build_treasury_stats() в единую модель Holdings."""
    label_key = str(stats.get("source_label_key", ""))
    source = "strategy.com" if "strategy" in label_key else "coingecko"

    last_acq = stats.get("last_acquisition") if isinstance(stats.get("last_acquisition"), dict) else None
    meta: dict[str, Any] = {}
    if last_acq:
        meta["last_acquisition"] = last_acq

    return Holdings(
        entity=entity or str(stats.get("name") or "Strategy"),
        type=EntityType.COMPANY,
        btc=float(stats.get("btc") or 0.0),
        source=source,
        date=date or datetime.date.today().isoformat(),
        change=change,
        price=_pos(stats.get("btc_price")),
        usd_value=_pos(stats.get("market_value")),
        avg_price=_pos(stats.get("avg_price")),
        cost_basis=_pos(stats.get("cost_basis")),
        pnl=(float(stats["pnl"]) if stats.get("pnl") else None),
        ticker="MSTR",
        meta=meta,
    )


class StrategySource(Source):
    """Источник одной сущности — Strategy.

    Пример подключения в main.py (без циклов импорта):

        from sources.base import register
        from sources.strategy import StrategySource
        register(StrategySource(build_treasury_stats))
    """

    key = "strategy"
    type = EntityType.COMPANY

    def __init__(self, stats_provider: StatsProvider, *, entity: str = "Strategy") -> None:
        self._stats_provider = stats_provider
        self._entity = entity

    async def fetch(self) -> Holdings | None:
        stats = await self._stats_provider()
        if not stats:
            return None
        return holdings_from_stats(stats, entity=self._entity)


__all__ = ["StrategySource", "holdings_from_stats", "StatsProvider"]
