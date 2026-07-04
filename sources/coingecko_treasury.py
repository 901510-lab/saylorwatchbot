"""CoinGecko public_treasury — мульти-источник для публичных компаний.

День 11 плана: один запрос к CoinGecko → снимки Holdings для топ-компаний
(Tesla, Block, MARA, Riot, Metaplanet), привязанных к entities.json.

API: https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from entities import EntityConfig, load_entities
from models import EntityType, Holdings
from sources.base import MultiSource, register
from sources.http import fetch_json

logger = logging.getLogger(__name__)

COINGECKO_TREASURY_URL = (
    "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
)
SOURCE_KEY = "coingecko_treasury"


def _parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", "").replace("$", "")
    if not cleaned:
        return 0.0
    return float(cleaned)


def _symbol_matches(cg_symbol: str | None, ticker: str | None) -> bool:
    """Сопоставление тикера из entities.json с полем symbol CoinGecko (напр. MARA.US)."""
    if not cg_symbol or not ticker:
        return False
    base = ticker.upper().split(".")[0]
    sym = cg_symbol.upper()
    return sym == base or sym.startswith(f"{base}.")


def _name_matches(company_name: str, entity: EntityConfig) -> bool:
    """Резервное сопоставление по имени, если тикер не совпал."""
    name = company_name.lower()
    eid = entity.id.lower()
    display = entity.name.lower()

    # Спец-случаи: CoinGecko vs наш id/имя
    aliases: dict[str, tuple[str, ...]] = {
        "marathon": ("mara holdings", "marathon digital", "marathon"),
        "block": ("block", "square"),
        "riot": ("riot platforms", "riot"),
        "tesla": ("tesla",),
        "metaplanet": ("metaplanet",),
    }
    for alias in aliases.get(eid, (eid, display)):
        if alias in name:
            return True
    return eid in name or display in name


def _match_company(company: dict[str, Any], entity: EntityConfig) -> bool:
    cg_name = str(company.get("name", ""))
    cg_symbol = company.get("symbol")
    if _symbol_matches(str(cg_symbol) if cg_symbol else None, entity.ticker):
        return True
    return _name_matches(cg_name, entity)


def _company_to_holdings(company: dict[str, Any], entity: EntityConfig) -> Holdings | None:
    try:
        btc = _parse_number(company.get("total_holdings", 0))
        if btc <= 0:
            return None
        market_value = _parse_number(company.get("total_current_value_usd", 0))
        cost_basis = _parse_number(company.get("total_entry_value_usd", 0))
        price = market_value / btc if market_value else None
        return Holdings(
            entity=entity.name,
            type=EntityType.COMPANY,
            btc=btc,
            source=SOURCE_KEY,
            date=datetime.date.today().isoformat(),
            price=price if price else None,
            usd_value=market_value if market_value else None,
            avg_price=(cost_basis / btc if cost_basis and btc else None),
            cost_basis=cost_basis if cost_basis else None,
            pnl=(market_value - cost_basis if cost_basis and market_value else None),
            ticker=entity.ticker,
            meta={
                "entity_id": entity.id,
                "coingecko_name": company.get("name"),
                "coingecko_symbol": company.get("symbol"),
                "country": company.get("country"),
            },
        ).enrich_valuation()
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Invalid CoinGecko row for %s (%s): %s",
            entity.id,
            company.get("name"),
            exc,
        )
        return None


class CoinGeckoTreasurySource(MultiSource):
    """MultiSource: public_treasury CoinGecko для компаний из entities.json."""

    key = SOURCE_KEY
    type = EntityType.COMPANY

    def __init__(
        self,
        *,
        entity_ids: list[str] | None = None,
        include_disabled: bool = False,
    ) -> None:
        """entity_ids — явный список id; иначе все с source=coingecko_treasury."""
        self._entity_ids = [e.strip().lower() for e in entity_ids] if entity_ids else None
        self._include_disabled = include_disabled

    def _tracked_entities(self) -> list[EntityConfig]:
        entities = load_entities()
        tracked = [
            e
            for e in entities
            if e.source == SOURCE_KEY and (self._include_disabled or e.enabled)
        ]
        if self._entity_ids is not None:
            wanted = set(self._entity_ids)
            tracked = [e for e in tracked if e.id in wanted]
        return tracked

    async def fetch(self) -> list[Holdings]:
        entities = self._tracked_entities()
        if not entities:
            return []

        data = await fetch_json(COINGECKO_TREASURY_URL, timeout_seconds=15)
        if not isinstance(data, dict):
            return []

        companies = data.get("companies") or []
        if not isinstance(companies, list):
            return []

        result: list[Holdings] = []
        matched_ids: set[str] = set()

        for entity in entities:
            for company in companies:
                if not isinstance(company, dict):
                    continue
                if not _match_company(company, entity):
                    continue
                holdings = _company_to_holdings(company, entity)
                if holdings:
                    result.append(holdings)
                    matched_ids.add(entity.id)
                break  # следующая сущность

        missing = {e.id for e in entities} - matched_ids
        for eid in sorted(missing):
            logger.warning("CoinGecko treasury: no match for entity %s", eid)

        return result


def register_coingecko_treasury(**kwargs: Any) -> CoinGeckoTreasurySource:
    """Зарегистрировать источник в глобальном реестре sources."""
    return register(CoinGeckoTreasurySource(**kwargs))


__all__ = [
    "COINGECKO_TREASURY_URL",
    "SOURCE_KEY",
    "CoinGeckoTreasurySource",
    "register_coingecko_treasury",
    "_match_company",
]
