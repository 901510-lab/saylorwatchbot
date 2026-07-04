"""Рейтинг топ держателей BTC — День 15 (/whales)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from entities import EntityConfig, enabled_entities
from i18n import t
from models import EntityType
from sources.coingecko_treasury import CoinGeckoTreasurySource
from sources.sosovalue_etf import SOSOVALUE_API_KEY, fetch_sosovalue_etf_aum

logger = logging.getLogger(__name__)

WHALES_TOP_N = 10


@dataclass
class WhaleEntry:
    name: str
    btc: float
    entity_type: EntityType
    ticker: str | None = None
    is_treasury: bool = False


async def collect_whale_rankings() -> tuple[list[WhaleEntry], list[str]]:
    """Собрать holdings enabled-сущностей. Возвращает (entries, footnotes)."""
    import main as app

    notes: list[str] = []
    btc_price = await app.fetch_btc_spot_price()

    stats_task = app.build_treasury_stats()
    companies_task = CoinGeckoTreasurySource().fetch()
    etf_aum_task = fetch_sosovalue_etf_aum(btc_price)

    stats, companies, etf_aum = await asyncio.gather(
        stats_task, companies_task, etf_aum_task, return_exceptions=True
    )

    if isinstance(stats, Exception):
        logger.warning("Whales: Strategy stats failed: %s", stats)
        stats = None
    if isinstance(companies, Exception):
        logger.warning("Whales: CoinGecko failed: %s", companies)
        companies = []
    if isinstance(etf_aum, Exception):
        logger.warning("Whales: SoSoValue AUM failed: %s", etf_aum)
        etf_aum = {}

    companies = companies if isinstance(companies, list) else []
    etf_aum = etf_aum if isinstance(etf_aum, dict) else {}

    by_company_id: dict[str, Any] = {}
    for h in companies:
        eid = h.meta.get("entity_id") if h.meta else None
        if eid:
            by_company_id[str(eid).lower()] = h

    etf_enabled = any(
        e.enabled and e.type == EntityType.ETF and e.source == "farside"
        for e in enabled_entities()
    )
    if etf_enabled and not etf_aum:
        if SOSOVALUE_API_KEY:
            notes.append("etf_aum_unavailable")
        else:
            notes.append("etf_skipped_no_key")

    entries: list[WhaleEntry] = []

    for entity in enabled_entities():
        row = _entry_for_entity(
            entity,
            stats=stats if isinstance(stats, dict) else None,
            company=by_company_id.get(entity.id),
            etf_aum=etf_aum,
        )
        if row:
            entries.append(row)

    entries.sort(key=lambda e: e.btc, reverse=True)
    return entries, notes


def _entry_for_entity(
    entity: EntityConfig,
    *,
    stats: dict[str, Any] | None,
    company: Any | None,
    etf_aum: dict[str, float],
) -> WhaleEntry | None:
    if entity.source == "strategy":
        if not stats:
            return None
        btc = float(stats.get("btc") or 0)
        if btc <= 0:
            return None
        return WhaleEntry(
            name=entity.name,
            btc=btc,
            entity_type=entity.type,
            ticker=entity.ticker,
            is_treasury=True,
        )

    if entity.source == "coingecko_treasury":
        if company is None:
            return None
        btc = float(company.btc or 0)
        if btc <= 0:
            return None
        return WhaleEntry(
            name=entity.name,
            btc=btc,
            entity_type=entity.type,
            ticker=entity.ticker or company.ticker,
        )

    if entity.source == "farside" and entity.type == EntityType.ETF:
        ticker = (entity.ticker or "").upper()
        btc = etf_aum.get(ticker, 0.0) if ticker else 0.0
        if btc <= 0:
            return None
        return WhaleEntry(
            name=entity.name,
            btc=btc,
            entity_type=EntityType.ETF,
            ticker=entity.ticker,
        )

    return None


def _type_label(entry: WhaleEntry, lang: str) -> str:
    if entry.is_treasury:
        return t(lang, "whale_type_treasury")
    if entry.entity_type == EntityType.ETF:
        return t(lang, "whale_type_etf")
    return t(lang, "whale_type_company")


def format_whales_message(
    entries: list[WhaleEntry],
    lang: str,
    *,
    format_btc: Callable[[float], str],
    notes: list[str] | None = None,
    top_n: int | None = None,
) -> str:
    if not entries:
        return t(lang, "whales_empty")

    limit = top_n if top_n is not None else WHALES_TOP_N
    lines = [t(lang, "whales_title"), ""]
    for rank, entry in enumerate(entries[:limit], start=1):
        ticker = f" ({entry.ticker})" if entry.ticker else ""
        lines.append(
            t(
                lang,
                "whales_row",
                rank=rank,
                name=entry.name,
                ticker=ticker,
                btc=format_btc(entry.btc),
                kind=_type_label(entry, lang),
            )
        )

    shown = entries[:limit]
    total_btc = sum(e.btc for e in entries)
    lines.append("")
    lines.append(
        t(
            lang,
            "whales_footer",
            btc=format_btc(total_btc),
            count=len(entries),
            top=len(shown),
        )
    )

    for note in notes or []:
        key = f"whales_note_{note}"
        lines.append(t(lang, key))

    return "\n".join(lines)
