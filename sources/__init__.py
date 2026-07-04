"""Пакет источников данных для мульти-мониторинга биткоин-китов.

Все источники приводят данные к единой модели `models.Holdings`.

Пример своего источника одной сущности:

    from models import EntityType, Holdings
    from sources.base import Source, register
    from sources.http import fetch_json

    class MyWhaleSource(Source):
        key = "my_whale"
        type = EntityType.COMPANY

        async def fetch(self) -> Holdings | None:
            data = await fetch_json("https://api.example.com/whale")
            if not data:
                return None
            return Holdings(
                entity="My Whale",
                type=self.type,
                btc=float(data["btc"]),
                source="api.example.com",
                date=data["date"],
            )

    register(MyWhaleSource())

Затем монитор вызывает `await collect_all()` и получает список снимков.
"""

from __future__ import annotations

from sources.base import (
    BaseSource,
    MultiSource,
    Source,
    all_sources,
    collect_all,
    register,
    unregister,
)
from sources.coingecko_treasury import (
    COINGECKO_TREASURY_URL,
    CoinGeckoTreasurySource,
    register_coingecko_treasury,
)
from sources.farside_etf import (
    FARSIDE_BTC_URL,
    FarsideEtfSource,
    fetch_etf_flow_table_rows,
    register_farside_etf,
)
from sources.sosovalue_etf import (
    SOSOVALUE_API_KEY,
    fetch_sosovalue_etf_aum,
    fetch_sosovalue_flow_row,
    fetch_sosovalue_table_rows,
)
from sources.http import fetch_json, fetch_text

__all__ = [
    "BaseSource",
    "Source",
    "MultiSource",
    "register",
    "unregister",
    "all_sources",
    "collect_all",
    "fetch_json",
    "fetch_text",
    "COINGECKO_TREASURY_URL",
    "CoinGeckoTreasurySource",
    "register_coingecko_treasury",
    "FARSIDE_BTC_URL",
    "FarsideEtfSource",
    "fetch_etf_flow_table_rows",
    "register_farside_etf",
    "SOSOVALUE_API_KEY",
    "fetch_sosovalue_flow_row",
    "fetch_sosovalue_table_rows",
    "fetch_sosovalue_etf_aum",
]
