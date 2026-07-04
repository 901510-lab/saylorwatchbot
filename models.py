"""Единая модель данных для мульти-мониторинга биткоин-китов.

Это канонический формат, к которому приводят все источники (`sources/`).
Базовые поля плана: {entity, type, btc, change, price, source, date}.
Остальные поля — опциональное обогащение (стоимость, средняя цена, PnL).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    """Категории держателей BTC (см. PRESENTATION.md → категории китов)."""

    COMPANY = "company"          # публичные компании: Strategy, Tesla, MARA...
    ETF = "etf"                  # ETF-фонды: IBIT, FBTC, GBTC, ARK
    INSTITUTION = "institution"  # фонды/институционалы: Galaxy, хедж-фонды
    GOVERNMENT = "government"    # государства: США, Сальвадор, Бутан
    ONCHAIN = "onchain"          # крупные on-chain адреса (explorer/Arkham)

    @classmethod
    def from_str(cls, value: str | None) -> "EntityType":
        if not value:
            return cls.COMPANY
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.COMPANY


def _slugify(name: str) -> str:
    """Превращает имя сущности в безопасный id (для файлов baseline и т.п.)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "entity"


@dataclass
class Holdings:
    """Снимок резервов одной сущности в единый момент времени.

    Обязательные (ядро модели):
        entity  — отображаемое имя ("Strategy", "BlackRock IBIT")
        type    — категория (EntityType)
        btc     — текущий объём BTC
        source  — источник данных (URL или идентификатор источника)
        date    — дата снимка в формате YYYY-MM-DD

    Расчётные/опциональные:
        change      — изменение BTC относительно прошлого baseline (+ покупка / − продажа)
        price       — спотовая цена BTC (USD) на момент снимка
        usd_value   — рыночная стоимость позиции (btc * price)
        avg_price   — средняя цена покупки (если известна)
        cost_basis  — суммарные затраты на покупку
        pnl         — нереализованный PnL (usd_value − cost_basis)
        ticker      — биржевой тикер (MSTR, IBIT, FBTC...)
        meta        — произвольные доп. данные источника
    """

    entity: str
    type: EntityType
    btc: float
    source: str
    date: str

    change: float = 0.0
    price: float | None = None

    usd_value: float | None = None
    avg_price: float | None = None
    cost_basis: float | None = None
    pnl: float | None = None
    ticker: str | None = None

    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Допускаем создание с type=строкой — нормализуем в Enum.
        if not isinstance(self.type, EntityType):
            self.type = EntityType.from_str(str(self.type))
        if not self.date:
            self.date = datetime.date.today().isoformat()

    @property
    def entity_id(self) -> str:
        """Стабильный идентификатор сущности (для baseline-файлов, реестра)."""
        return _slugify(self.entity)

    @property
    def is_buy(self) -> bool:
        return self.change > 0

    @property
    def is_sale(self) -> bool:
        return self.change < 0

    def with_change(self, previous_btc: float | None) -> "Holdings":
        """Возвращает копию с проставленным change относительно прошлого объёма."""
        if previous_btc is not None:
            self.change = self.btc - previous_btc
        return self

    def enrich_valuation(self) -> "Holdings":
        """Досчитывает usd_value и pnl, если хватает данных."""
        if self.usd_value is None and self.price is not None:
            self.usd_value = self.btc * self.price
        if self.pnl is None and self.usd_value is not None and self.cost_basis is not None:
            self.pnl = self.usd_value - self.cost_basis
        if self.avg_price is None and self.cost_basis and self.btc:
            self.avg_price = self.cost_basis / self.btc
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Holdings":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["type"] = EntityType.from_str(data.get("type"))
        return cls(**kwargs)


__all__ = ["EntityType", "Holdings"]
