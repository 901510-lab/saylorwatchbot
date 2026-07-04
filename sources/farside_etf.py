"""Farside Investors — источник дневных ETF-потоков (IBIT, FBTC, GBTC, ARKB).

День 13 плана: парсинг таблицы с https://farside.co.uk/btc/ (USD millions).
Farside может отдавать HTTP 403 с IP датацентров — тогда используется
SoSoValue OpenAPI (SOSOVALUE_API_KEY).

Поток конвертируется в BTC-эквивалент по спотовой цене CoinGecko для порогов/карточек.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import time
from html import unescape
from typing import Any

from entities import EntityConfig, load_entities
from models import EntityType, Holdings
from sources.base import MultiSource, register
from sources.http import fetch_json, fetch_text
from sources.sosovalue_etf import SOURCE_KEY as SOSO_KEY
from sources.sosovalue_etf import fetch_sosovalue_flow_row, fetch_sosovalue_table_rows

logger = logging.getLogger(__name__)

SOURCE_KEY = "farside"
_DEFAULT_FARSIDE_URLS = (
    "https://farside.co.uk/btc/",
    "https://farside.co.uk/bitcoin-etf-flow-all-data/",
)
FARSIDE_BTC_URL = os.environ.get("FARSIDE_ETF_URL", _DEFAULT_FARSIDE_URLS[0])
FARSIDE_BTC_URLS = [
    u.strip()
    for u in os.environ.get("FARSIDE_ETF_URLS", ",".join(_DEFAULT_FARSIDE_URLS)).split(",")
    if u.strip()
]
COINGECKO_PRICE_URL = (
    "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
)
_BROWSER_UA = os.environ.get(
    "FARSIDE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
FARSIDE_HTTP_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://farside.co.uk/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

_DATE_RE = re.compile(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$")

# JustRunMy / датацентры: Farside часто недоступен — не долбим каждые 5 мин
_FARSIDE_COOLDOWN_UNTIL: float = 0.0
_FARSIDE_FALLBACK_LOGGED = False
FARSIDE_RETRY_COOLDOWN_SEC = max(
    300, int(os.environ.get("FARSIDE_RETRY_COOLDOWN_SEC", "21600"))
)


def _sosovalue_configured() -> bool:
    return bool(os.environ.get("SOSOVALUE_API_KEY", "").strip())


def _farside_on_cooldown() -> bool:
    return time.time() < _FARSIDE_COOLDOWN_UNTIL


def _mark_farside_unreachable() -> None:
    global _FARSIDE_COOLDOWN_UNTIL, _FARSIDE_FALLBACK_LOGGED
    _FARSIDE_COOLDOWN_UNTIL = time.time() + FARSIDE_RETRY_COOLDOWN_SEC
    if _sosovalue_configured():
        if not _FARSIDE_FALLBACK_LOGGED:
            logger.info(
                "Farside ETF unreachable from this host — using SoSoValue for ~%dh "
                "(set FARSIDE_RETRY_COOLDOWN_SEC to retry sooner)",
                FARSIDE_RETRY_COOLDOWN_SEC // 3600,
            )
            _FARSIDE_FALLBACK_LOGGED = True
    else:
        logger.warning(
            "Farside ETF unreachable and SOSOVALUE_API_KEY not set — ETF flows disabled "
            "until retry in %ds",
            FARSIDE_RETRY_COOLDOWN_SEC,
        )


def _reset_farside_cooldown() -> None:
    global _FARSIDE_COOLDOWN_UNTIL, _FARSIDE_FALLBACK_LOGGED
    _FARSIDE_COOLDOWN_UNTIL = 0.0
    _FARSIDE_FALLBACK_LOGGED = False


def _parse_flow_cell(raw: str) -> float | None:
    """USD millions из ячейки Farside: 250.5, (95.1), -, —."""
    text = unescape(raw).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "n/a"}:
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except ValueError:
        return None


def _date_to_iso(date_str: str) -> str:
    """'10 Jun 2026' -> '2026-06-10'."""
    dt = datetime.datetime.strptime(date_str.strip(), "%d %b %Y")
    return dt.date().isoformat()


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def parse_farside_table(html: str) -> list[dict[str, Any]]:
    """Разбор HTML-таблицы Farside → [{date, date_iso, flows: {ticker: usd_m}}]."""
    if not html or "Just a moment" in html or "cf_chl" in html:
        return []

    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells = [
            _strip_tags(c)
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
        ]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)

    if not rows:
        return []

    header_idx = None
    tickers: list[str] = []
    for i, row in enumerate(rows):
        upper = [c.upper() for c in row]
        if "IBIT" in upper and ("FBTC" in upper or "GBTC" in upper):
            header_idx = i
            tickers = upper
            break

    if header_idx is None:
        return []

    col_by_ticker = {t: idx for idx, t in enumerate(tickers)}
    date_col = 0
    if tickers[0] not in {"DATE", "IBIT"} and _DATE_RE.match(rows[header_idx][0]):
        date_col = 0
    elif "DATE" in col_by_ticker:
        date_col = col_by_ticker["DATE"]

    parsed: list[dict[str, Any]] = []
    for row in rows[header_idx + 1 :]:
        if date_col >= len(row):
            continue
        date_raw = row[date_col].strip()
        if not _DATE_RE.match(date_raw):
            continue
        flows: dict[str, float] = {}
        for ticker, idx in col_by_ticker.items():
            if ticker in {"DATE", "TOTAL", "BTC"}:
                continue
            if idx >= len(row):
                continue
            val = _parse_flow_cell(row[idx])
            if val is not None:
                flows[ticker] = val
        if flows:
            parsed.append(
                {
                    "date": date_raw,
                    "date_iso": _date_to_iso(date_raw),
                    "flows": flows,
                }
            )

    parsed.sort(key=lambda r: r["date_iso"])
    return parsed


async def _fetch_btc_price_usd() -> float | None:
    try:
        data = await fetch_json(COINGECKO_PRICE_URL, timeout_seconds=10)
        price = float(data["bitcoin"]["usd"])
        return price if price > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _flow_row_to_holdings(
    entity: EntityConfig,
    *,
    flow_usd_m: float,
    flow_date_iso: str,
    btc_price: float | None,
    source: str = SOURCE_KEY,
) -> Holdings | None:
    flow_usd = flow_usd_m * 1_000_000
    if flow_usd_m and not btc_price:
        logger.warning(
            "ETF flow: BTC price unavailable, skip BTC conversion for %s on %s",
            entity.id,
            flow_date_iso,
        )
        return None
    flow_btc = (flow_usd / btc_price) if btc_price and flow_usd_m else 0.0
    if flow_usd_m == 0:
        flow_btc = 0.0

    return Holdings(
        entity=entity.name,
        type=EntityType.ETF,
        btc=abs(flow_btc),
        source=source,
        date=flow_date_iso,
        change=flow_btc,
        price=btc_price,
        usd_value=abs(flow_usd),
        ticker=entity.ticker,
        meta={
            "entity_id": entity.id,
            "flow_usd_m": flow_usd_m,
            "flow_usd": flow_usd,
            "farside_ticker": entity.ticker,
            "is_etf_flow": True,
        },
    )


class FarsideEtfSource(MultiSource):
    """MultiSource: дневные net flows US spot BTC ETF с Farside."""

    key = SOURCE_KEY
    type = EntityType.ETF

    def __init__(
        self,
        *,
        entity_ids: list[str] | None = None,
        include_disabled: bool = False,
        url: str | None = None,
        urls: list[str] | None = None,
    ) -> None:
        self._entity_ids = [e.strip().lower() for e in entity_ids] if entity_ids else None
        self._include_disabled = include_disabled
        if urls:
            self._urls = urls
        elif url:
            self._urls = [url]
        else:
            self._urls = FARSIDE_BTC_URLS

    def _tracked_entities(self) -> list[EntityConfig]:
        entities = [
            e
            for e in load_entities()
            if e.source == SOURCE_KEY and (self._include_disabled or e.enabled)
        ]
        if self._entity_ids is not None:
            wanted = set(self._entity_ids)
            entities = [e for e in entities if e.id in wanted]
        return entities

    async def _fetch_farside_row(self) -> dict[str, Any] | None:
        rows = await fetch_farside_table_rows(urls=self._urls)
        if rows:
            return rows[-1]
        return None

    async def _fetch_flow_row(self) -> tuple[dict[str, Any] | None, str]:
        if not _farside_on_cooldown():
            row = await self._fetch_farside_row()
            if row:
                _reset_farside_cooldown()
                return row, SOURCE_KEY
        row = await fetch_sosovalue_flow_row()
        if row:
            if not _farside_on_cooldown():
                logger.info("Farside ETF: using SoSoValue fallback (%s)", row.get("date_iso"))
            return row, SOSO_KEY
        if not _farside_on_cooldown():
            _mark_farside_unreachable()
        return None, SOURCE_KEY

    async def fetch(self) -> list[Holdings]:
        entities = self._tracked_entities()
        if not entities:
            return []

        latest, data_source = await self._fetch_flow_row()
        if not latest:
            logger.warning(
                "ETF flows: Farside blocked and SoSoValue unavailable "
                "(set SOSOVALUE_API_KEY from openapi.sosovalue.com)"
            )
            return []

        btc_price = await _fetch_btc_price_usd()
        result: list[Holdings] = []

        for entity in entities:
            ticker = (entity.ticker or "").upper()
            flow_m = latest["flows"].get(ticker)
            if flow_m is None:
                logger.warning("ETF flows: no column for %s (%s)", entity.id, ticker)
                continue
            h = _flow_row_to_holdings(
                entity,
                flow_usd_m=flow_m,
                flow_date_iso=latest["date_iso"],
                btc_price=btc_price,
                source=data_source,
            )
            if h:
                result.append(h)

        return result


async def fetch_entity_etf_flow_series(
    entity: EntityConfig,
    *,
    since_date_exclusive: str,
    until_date_inclusive: str,
) -> list[Holdings]:
    """Дневные потоки одного ETF между датами (для catch-up после простоя)."""
    rows = await fetch_farside_table_rows()
    if not rows:
        try:
            start = datetime.date.fromisoformat(since_date_exclusive) + datetime.timedelta(days=1)
            end = datetime.date.fromisoformat(until_date_inclusive)
            rows = await fetch_sosovalue_table_rows(start, end)
            if rows:
                logger.info(
                    "ETF catch-up: SoSoValue fallback (%d days, %s..%s)",
                    len(rows),
                    start.isoformat(),
                    end.isoformat(),
                )
        except ValueError:
            rows = []
    if not rows:
        return []
    btc_price = await _fetch_btc_price_usd()
    ticker = (entity.ticker or "").upper()
    result: list[Holdings] = []
    for row in rows:
        day = row.get("date_iso") or ""
        if not day or day <= since_date_exclusive or day > until_date_inclusive:
            continue
        flow_m = row.get("flows", {}).get(ticker)
        if flow_m is None:
            continue
        h = _flow_row_to_holdings(
            entity,
            flow_usd_m=flow_m,
            flow_date_iso=day,
            btc_price=btc_price,
            source=SOURCE_KEY,
        )
        if h:
            result.append(h)
    result.sort(key=lambda h: h.date or "")
    return result


async def fetch_farside_table_rows(*, urls: list[str] | None = None) -> list[dict[str, Any]]:
    """Полная таблица Farside для недельной агрегации ETF-потоков."""
    if _farside_on_cooldown():
        return []

    targets = urls or FARSIDE_BTC_URLS
    quiet = _sosovalue_configured()
    for url in targets:
        html = await fetch_text(url, timeout_seconds=25, headers=FARSIDE_HTTP_HEADERS)
        if not html:
            if quiet:
                logger.debug("Farside ETF: no response from %s", url)
            else:
                logger.warning("Farside ETF: no response from %s", url)
            continue
        rows = parse_farside_table(html)
        if rows:
            _reset_farside_cooldown()
            logger.info("Farside ETF: parsed %d rows from %s", len(rows), url)
            return rows
        if quiet:
            logger.debug("Farside ETF: table not parsed from %s", url)
        else:
            logger.warning("Farside ETF: table not parsed from %s", url)

    if quiet:
        _mark_farside_unreachable()
    return []


async def fetch_etf_flow_table_rows(
    period_start: datetime.date | None = None,
    period_end: datetime.date | None = None,
    *,
    urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Таблица ETF-потоков: Farside HTML → SoSoValue history → последний день SoSoValue."""
    rows = await fetch_farside_table_rows(urls=urls)
    if rows:
        return rows

    if period_start is not None and period_end is not None:
        rows = await fetch_sosovalue_table_rows(period_start, period_end)
        if rows:
            logger.info(
                "ETF flows: SoSoValue weekly fallback (%d days, %s..%s)",
                len(rows),
                period_start.isoformat(),
                period_end.isoformat(),
            )
            return rows

    row = await fetch_sosovalue_flow_row()
    if row:
        logger.info("ETF flows: SoSoValue single-day fallback (%s)", row.get("date_iso"))
        return [row]

    logger.warning(
        "ETF flows: Farside blocked and SoSoValue unavailable "
        "(set SOSOVALUE_API_KEY from openapi.sosovalue.com)"
    )
    return []


def register_farside_etf(**kwargs: Any) -> FarsideEtfSource:
    return register(FarsideEtfSource(**kwargs))


__all__ = [
    "FARSIDE_BTC_URL",
    "FARSIDE_BTC_URLS",
    "SOURCE_KEY",
    "FarsideEtfSource",
    "parse_farside_table",
    "fetch_farside_table_rows",
    "fetch_entity_etf_flow_series",
    "fetch_etf_flow_table_rows",
    "register_farside_etf",
]
