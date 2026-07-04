"""SoSoValue OpenAPI — fallback для ETF-потоков, когда Farside блокирует IP (403).

Требует бесплатный ключ: https://openapi.sosovalue.com → SOSOVALUE_API_KEY в env.
Эндпоинт: POST /openapi/v2/etf/currentEtfDataMetrics (type=us-btc-spot).
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any
from urllib.parse import quote

from sources.http import fetch_json, fetch_json_post

logger = logging.getLogger(__name__)

SOURCE_KEY = "sosovalue"
SOSOVALUE_API_KEY = os.environ.get("SOSOVALUE_API_KEY", "").strip()
SOSOVALUE_METRICS_URL = os.environ.get(
    "SOSOVALUE_ETF_METRICS_URL",
    "https://openapi.sosovalue.com/openapi/v2/etf/currentEtfDataMetrics",
)
SOSOVALUE_BTC_ETF_TYPE = os.environ.get("SOSOVALUE_BTC_ETF_TYPE", "us-btc-spot")
SOSOVALUE_API_V1_BASE = os.environ.get(
    "SOSOVALUE_API_V1_BASE",
    "https://openapi.sosovalue.com/openapi/v1",
).rstrip("/")
_DEFAULT_ETF_TICKERS = ("IBIT", "FBTC", "GBTC", "ARKB")


def _api_headers() -> dict[str, str]:
    return {
        "x-soso-api-key": SOSOVALUE_API_KEY,
        "Accept": "application/json",
    }


def _inflow_usd_m(item: dict[str, Any]) -> tuple[float | None, str | None]:
    """dailyNetInflow → (USD millions, YYYY-MM-DD)."""
    block = item.get("dailyNetInflow")
    if not isinstance(block, dict):
        return None, None
    raw_val = block.get("value")
    if raw_val is None:
        return None, block.get("lastUpdateDate")
    try:
        val = float(raw_val)
    except (TypeError, ValueError):
        return None, block.get("lastUpdateDate")
    # SoSoValue отдаёт USD millions (как Farside).
    if abs(val) >= 1_000_000:
        val /= 1_000_000
    return val, block.get("lastUpdateDate")


def _net_assets_usd(item: dict[str, Any]) -> float | None:
    """netAssets → USD (полная сумма)."""
    block = item.get("netAssets")
    if not isinstance(block, dict):
        return None
    raw = block.get("value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def _fetch_sosovalue_metrics_items() -> list[dict[str, Any]] | None:
    if not SOSOVALUE_API_KEY:
        return None

    payload = await fetch_json_post(
        SOSOVALUE_METRICS_URL,
        {"type": SOSOVALUE_BTC_ETF_TYPE},
        timeout_seconds=20,
        headers={
            **_api_headers(),
            "Content-Type": "application/json",
        },
    )
    if not payload:
        logger.warning("SoSoValue ETF: empty HTTP response")
        return None
    if payload.get("code", 0) != 0:
        logger.warning("SoSoValue ETF API error: %s", payload.get("msg", payload))
        return None

    data = payload.get("data") or {}
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        logger.warning("SoSoValue ETF: no list in response")
        return None
    return items


async def fetch_sosovalue_etf_aum(btc_price_usd: float | None) -> dict[str, float]:
    """AUM spot BTC ETF по тикеру → BTC (оценка по netAssets USD / цена BTC)."""
    items = await _fetch_sosovalue_metrics_items()
    if not items or not btc_price_usd or btc_price_usd <= 0:
        return {}

    result: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper()
        usd = _net_assets_usd(item)
        if ticker and usd and usd > 0:
            result[ticker] = usd / btc_price_usd
    return result


async def fetch_sosovalue_flow_row() -> dict[str, Any] | None:
    """Последний день потоков по тикерам → {date_iso, flows: {IBIT: usd_m}}."""
    items = await _fetch_sosovalue_metrics_items()
    if not items:
        return None

    flows: dict[str, float] = {}
    flow_date: str | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if not ticker:
            continue
        usd_m, date_iso = _inflow_usd_m(item)
        if usd_m is not None:
            flows[ticker] = usd_m
        if date_iso and (flow_date is None or date_iso > flow_date):
            flow_date = str(date_iso)

    if not flows or not flow_date:
        logger.warning("SoSoValue ETF: parsed empty flows")
        return None

    return {"date_iso": flow_date, "flows": flows}


def _date_to_farside_label(iso_day: str) -> str:
    dt = datetime.date.fromisoformat(iso_day)
    return dt.strftime("%d %b %Y")


async def fetch_sosovalue_table_rows(
    period_start: datetime.date,
    period_end: datetime.date,
    *,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Недельная таблица ETF-потоков из SoSoValue v1 /etfs/{ticker}/history.

    Формат совместим с Farside: [{date_iso, date, flows: {IBIT: usd_m}}].
    """
    if not SOSOVALUE_API_KEY:
        return []

    start = period_start.isoformat()
    end = period_end.isoformat()
    wanted = [t.strip().upper() for t in (tickers or _DEFAULT_ETF_TICKERS) if t.strip()]
    by_date: dict[str, dict[str, float]] = {}

    for ticker in wanted:
        url = (
            f"{SOSOVALUE_API_V1_BASE}/etfs/{quote(ticker)}/history"
            f"?start_date={start}&end_date={end}&limit=50"
        )
        payload = await fetch_json(url, timeout_seconds=20, headers=_api_headers())
        if not isinstance(payload, list):
            logger.warning("SoSoValue ETF history: no data for %s", ticker)
            continue
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            day = str(entry.get("date") or "")[:10]
            if not day or day < start or day > end:
                continue
            raw = entry.get("net_inflow")
            if raw is None:
                continue
            try:
                usd = float(raw)
            except (TypeError, ValueError):
                continue
            # Farside хранит USD millions; SoSoValue history — полные USD.
            by_date.setdefault(day, {})[ticker] = usd / 1_000_000

    if not by_date:
        logger.warning("SoSoValue ETF history: empty table %s..%s", start, end)
        return []

    rows = [
        {
            "date": _date_to_farside_label(day),
            "date_iso": day,
            "flows": flows,
        }
        for day, flows in sorted(by_date.items())
    ]
    logger.info(
        "SoSoValue ETF history: %d days, tickers=%s (%s..%s)",
        len(rows),
        ",".join(wanted),
        start,
        end,
    )
    return rows


__all__ = [
    "SOURCE_KEY",
    "SOSOVALUE_API_KEY",
    "SOSOVALUE_API_V1_BASE",
    "fetch_sosovalue_flow_row",
    "fetch_sosovalue_table_rows",
    "fetch_sosovalue_etf_aum",
]
