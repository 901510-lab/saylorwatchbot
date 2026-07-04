"""Weekly Digest v1/v2 — Premium PNG-сводка (День 19+).

v1: snapshot diff, ETF flows, BTC week change.
v2: transactions.json — buy/sell BTC и ср. цены за неделю по компаниям.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from entities import enabled_entities
from i18n import t
from models import EntityType
from sources.coingecko_treasury import CoinGeckoTreasurySource, SOURCE_KEY as CG_SOURCE
from sources.farside_etf import SOURCE_KEY as FARSIDE_SOURCE, fetch_etf_flow_table_rows
from sources.http import fetch_json
from subscribers import list_subscribers
from json_store import atomic_write_json, json_rw_lock
from user_lang_prefs import get_user_lang
from transactions import TradeSummary, largest_trade_in_period, list_transactions, summarize_trades

logger = logging.getLogger(__name__)

WEEKLY_DIGEST_ENABLED = os.environ.get("WEEKLY_DIGEST_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEEKLY_DIGEST_TIMEZONE = os.environ.get("WEEKLY_DIGEST_TIMEZONE", "America/New_York")
WEEKLY_DIGEST_WEEKDAY = int(os.environ.get("WEEKLY_DIGEST_WEEKDAY", "6"))  # 0=Mon … 6=Sun
WEEKLY_DIGEST_HOUR = int(os.environ.get("WEEKLY_DIGEST_HOUR", "12"))
WEEKLY_DIGEST_MINUTE = int(os.environ.get("WEEKLY_DIGEST_MINUTE", "0"))
FREE_WEEKLY_DIGEST_ENABLED = os.environ.get("FREE_WEEKLY_DIGEST_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEEKLY_DIGEST_EN_SUMMARY_ENABLED = os.environ.get(
    "WEEKLY_DIGEST_EN_SUMMARY_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}
SNAPSHOT_FILE = Path(os.environ.get("WEEKLY_DIGEST_SNAPSHOT_FILE", "weekly_digest_snapshot.json"))
STATE_FILE = Path(os.environ.get("WEEKLY_DIGEST_STATE_FILE", "weekly_digest_state.json"))
COINGECKO_CHART_URL = (
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=7"
)


@dataclass
class CompanyDigestRow:
    entity_id: str
    name: str
    ticker: str | None
    buy_btc_week: float
    sell_btc_week: float
    buy_avg_price_week: float | None
    sell_avg_price_week: float | None
    net_btc_week: float | None
    holdings_btc: float
    avg_price: float | None
    pnl: float | None
    sell_price_estimated: bool = False
    has_trades: bool = False
    net_source: Literal["trades", "holdings", "none"] = "none"


@dataclass
class EtfDigestRow:
    entity_id: str
    name: str
    ticker: str
    net_flow_btc: float
    net_flow_usd: float
    best_day_btc: float
    worst_day_btc: float
    best_day_date: str
    worst_day_date: str
    has_data: bool = True


@dataclass
class WeeklyDigestData:
    period_start: datetime.date
    period_end: datetime.date
    period_label: str
    companies: list[CompanyDigestRow] = field(default_factory=list)
    etfs: list[EtfDigestRow] = field(default_factory=list)
    btc_price_now: float | None = None
    btc_price_week_ago: float | None = None
    btc_week_change_pct: float | None = None
    total_tracked_btc: float = 0.0
    whale_name: str | None = None
    whale_net_btc: float | None = None
    etf_flow_days: int = 0


def digest_enabled() -> bool:
    return WEEKLY_DIGEST_ENABLED


def _digest_tz() -> ZoneInfo:
    try:
        return ZoneInfo(WEEKLY_DIGEST_TIMEZONE)
    except Exception:
        logger.warning("Invalid WEEKLY_DIGEST_TIMEZONE=%s, using UTC", WEEKLY_DIGEST_TIMEZONE)
        return ZoneInfo("UTC")


def period_key_for_moment(moment: datetime.datetime | None = None) -> str:
    tz = _digest_tz()
    dt = (moment or datetime.datetime.now(tz)).astimezone(tz)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _format_period_label(start: datetime.date, end: datetime.date) -> str:
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.strftime('%b %d')} – {end.day}, {end.year}"
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("%s read error: %s", path, exc)
        return {}


def load_snapshot() -> dict[str, Any]:
    return _load_json(SNAPSHOT_FILE)


def load_state() -> dict[str, Any]:
    return _load_json(STATE_FILE)


def save_snapshot(data: WeeklyDigestData) -> None:
    entities: dict[str, dict[str, float | None]] = {}
    for row in data.companies:
        entities[row.entity_id] = {
            "btc": row.holdings_btc,
            "avg_price": row.avg_price,
            "pnl": row.pnl,
            "net_btc_week": row.net_btc_week,
        }
    etfs: dict[str, dict[str, float]] = {}
    for row in data.etfs:
        etfs[row.entity_id] = {
            "ticker": row.ticker,
            "net_flow_btc": row.net_flow_btc,
        }
    payload = {
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "period_key": period_key_for_moment(),
        "period_end": data.period_end.isoformat(),
        "btc_price": data.btc_price_now,
        "total_tracked_btc": data.total_tracked_btc,
        "entities": entities,
        "etfs": etfs,
    }
    atomic_write_json(SNAPSHOT_FILE, payload)


def mark_scheduled_sent(period_key: str) -> None:
    with json_rw_lock(STATE_FILE, default={}) as payload:
        payload["last_sent_period"] = period_key
        payload["last_sent_at"] = datetime.datetime.now(datetime.UTC).isoformat()


def scheduled_already_sent() -> bool:
    state = load_state()
    return state.get("last_sent_period") == period_key_for_moment()


def free_weekly_digest_enabled() -> bool:
    return digest_enabled() and FREE_WEEKLY_DIGEST_ENABLED


def free_weekly_already_sent() -> bool:
    state = load_state()
    return state.get("last_free_sent_period") == period_key_for_moment()


def weekly_period_complete() -> bool:
    """Premium (если есть получатели) и free text digest за текущую неделю."""
    if not digest_enabled():
        return True
    premium_ok = scheduled_already_sent()
    if not premium_ok:
        try:
            import main as app

            admin_id = app.alert_chat_id()
        except Exception:
            admin_id = None
        if not premium_recipient_ids(include_admin_id=admin_id):
            premium_ok = True
    free_ok = True
    if free_weekly_digest_enabled():
        free_ok = free_weekly_already_sent()
        if not free_ok and not free_weekly_recipient_ids():
            free_ok = True
    return premium_ok and free_ok


def mark_free_weekly_sent(period_key: str) -> None:
    with json_rw_lock(STATE_FILE, default={}) as payload:
        payload["last_free_sent_period"] = period_key
        payload["last_free_sent_at"] = datetime.datetime.now(datetime.UTC).isoformat()


def seconds_until_next_run(*, now: datetime.datetime | None = None) -> float:
    tz = _digest_tz()
    moment = (now or datetime.datetime.now(tz)).astimezone(tz)
    try:
        target = moment.replace(
            hour=WEEKLY_DIGEST_HOUR,
            minute=WEEKLY_DIGEST_MINUTE,
            second=0,
            microsecond=0,
        )
    except ValueError:
        logger.error(
            "Invalid WEEKLY_DIGEST_HOUR/MINUTE: %s:%s",
            WEEKLY_DIGEST_HOUR,
            WEEKLY_DIGEST_MINUTE,
        )
        return 3600.0

    days_ahead = (WEEKLY_DIGEST_WEEKDAY - target.weekday()) % 7
    if days_ahead == 0 and moment >= target:
        if not weekly_period_complete():
            return 1.0
        days_ahead = 7
    target = target + datetime.timedelta(days=days_ahead)
    return max(1.0, (target - moment).total_seconds())


async def fetch_btc_week_prices() -> tuple[float | None, float | None]:
    try:
        data = await fetch_json(COINGECKO_CHART_URL, timeout_seconds=15)
        prices = data.get("prices") if isinstance(data, dict) else None
        if not isinstance(prices, list) or len(prices) < 2:
            return None, None
        week_ago = float(prices[0][1])
        now = float(prices[-1][1])
        return now, week_ago
    except Exception as exc:
        logger.warning("BTC week prices fetch failed: %s", exc)
        return None, None


async def _aggregate_etf_flows(
    period_start: datetime.date,
    period_end: datetime.date,
    btc_price: float | None,
) -> tuple[list[EtfDigestRow], int]:
    etf_entities = [
        e
        for e in enabled_entities()
        if e.source == FARSIDE_SOURCE and e.type == EntityType.ETF and (e.ticker or "").upper()
    ]

    def _empty_row(entity) -> EtfDigestRow:
        return EtfDigestRow(
            entity_id=entity.id,
            name=entity.name,
            ticker=(entity.ticker or "").upper(),
            net_flow_btc=0.0,
            net_flow_usd=0.0,
            best_day_btc=0.0,
            worst_day_btc=0.0,
            best_day_date="",
            worst_day_date="",
            has_data=False,
        )

    table = await fetch_etf_flow_table_rows(period_start, period_end)
    if not table:
        return [_empty_row(e) for e in etf_entities], 0

    unique_days = {entry.get("date_iso") for entry in table if entry.get("date_iso")}
    flow_days = len(unique_days)

    price = btc_price or 0.0
    start_iso = period_start.isoformat()
    end_iso = period_end.isoformat()
    rows: list[EtfDigestRow] = []

    for entity in etf_entities:
        ticker = (entity.ticker or "").upper()

        daily: list[tuple[str, float, float]] = []
        for entry in table:
            day = entry.get("date_iso", "")
            if not day or day < start_iso or day > end_iso:
                continue
            flows = entry.get("flows") if isinstance(entry.get("flows"), dict) else {}
            usd_m = float(flows.get(ticker) or 0.0)
            if usd_m and not price:
                flow_btc = 0.0
            else:
                flow_btc = (usd_m * 1_000_000 / price) if price and usd_m else 0.0
            daily.append((day, flow_btc, usd_m * 1_000_000))

        if not daily:
            rows.append(_empty_row(entity))
            continue

        net_btc = sum(d[1] for d in daily)
        net_usd = sum(d[2] for d in daily)
        best = max(daily, key=lambda d: d[1])
        worst = min(daily, key=lambda d: d[1])
        rows.append(
            EtfDigestRow(
                entity_id=entity.id,
                name=entity.name,
                ticker=ticker,
                net_flow_btc=net_btc,
                net_flow_usd=net_usd,
                best_day_btc=best[1],
                worst_day_btc=worst[1],
                best_day_date=best[0],
                worst_day_date=worst[0],
                has_data=True,
            )
        )

    return rows, flow_days


async def collect_weekly_digest() -> WeeklyDigestData | None:
    import main as app
    from whales import collect_whale_rankings

    tz = _digest_tz()
    period_end = datetime.datetime.now(tz).date()
    period_start = period_end - datetime.timedelta(days=6)
    prev = load_snapshot()
    prev_entities = prev.get("entities") if isinstance(prev.get("entities"), dict) else {}
    trade_summary = summarize_trades(period_start, period_end)

    stats_task = app.build_treasury_stats()
    companies_task = CoinGeckoTreasurySource().fetch()
    prices_task = fetch_btc_week_prices()
    whales_task = collect_whale_rankings()

    stats, companies, prices, whale_pack = await asyncio.gather(
        stats_task,
        companies_task,
        prices_task,
        whales_task,
        return_exceptions=True,
    )

    if isinstance(stats, Exception):
        logger.warning("Weekly digest: Strategy stats failed: %s", stats)
        stats = None
    if isinstance(companies, Exception):
        logger.warning("Weekly digest: CoinGecko failed: %s", companies)
        companies = []
    if isinstance(prices, Exception):
        logger.warning("Weekly digest: BTC prices failed: %s", prices)
        prices = (None, None)
    if isinstance(whale_pack, Exception):
        logger.warning("Weekly digest: whales failed: %s", whale_pack)
        whale_pack = ([], [])

    companies = companies if isinstance(companies, list) else []
    btc_now, btc_week_ago = prices if isinstance(prices, tuple) else (None, None)
    entries, _notes = whale_pack if isinstance(whale_pack, tuple) else ([], [])
    total_tracked = sum(e.btc for e in entries)

    by_company_id: dict[str, Any] = {}
    for h in companies:
        eid = h.meta.get("entity_id") if h.meta else None
        if eid:
            by_company_id[str(eid).lower()] = h

    company_rows: list[CompanyDigestRow] = []
    whale_candidates: list[tuple[str, float]] = []
    period_start_iso = period_start.isoformat()
    period_end_iso = period_end.isoformat()
    tx_in_period = [
        tx for tx in list_transactions()
        if tx.date and period_start_iso <= tx.date <= period_end_iso
    ]

    for entity in enabled_entities():
        if entity.type != EntityType.COMPANY:
            continue
        if entity.source == "strategy":
            if not stats or not isinstance(stats, dict):
                continue
            btc = float(stats.get("btc") or 0)
            avg_price = stats.get("avg_price")
            pnl = stats.get("pnl")
        elif entity.source == CG_SOURCE:
            holding = by_company_id.get(entity.id)
            if holding is None:
                continue
            btc = float(holding.btc or 0)
            avg_price = holding.avg_price
            pnl = holding.pnl
        else:
            continue

        prev_row = prev_entities.get(entity.id) if isinstance(prev_entities.get(entity.id), dict) else None
        prev_btc = float(prev_row["btc"]) if prev_row and prev_row.get("btc") is not None else None
        trades = trade_summary.get(entity.id, TradeSummary())
        has_trades = bool(trades.buy_trades or trades.sell_trades)
        net_from_trades = trades.net_btc if has_trades else None
        net_from_snapshot = (btc - prev_btc) if prev_btc is not None else None

        net_source: Literal["trades", "holdings", "none"] = "none"
        if has_trades:
            if (
                net_from_snapshot is not None
                and net_from_trades is not None
                and abs(net_from_trades - net_from_snapshot) > 0.5
            ):
                net = net_from_snapshot
                net_source = "holdings"
            else:
                net = net_from_trades
                net_source = "trades"
        elif net_from_snapshot is not None and abs(net_from_snapshot) >= 0.01:
            net = net_from_snapshot
            net_source = "holdings"
        elif net_from_snapshot is not None:
            net = 0.0
            net_source = "none"
        else:
            net = None
            net_source = "none"

        if net is not None and abs(net) >= 0.01:
            whale_candidates.append((entity.name, net))
        if trades.buy_btc >= 0.01:
            whale_candidates.append((entity.name, trades.buy_btc))
        if trades.sell_btc >= 0.01:
            whale_candidates.append((entity.name, -trades.sell_btc))

        sell_estimated = any(
            tx.entity_id == entity.id and tx.side == "sell" and tx.price_estimated
            for tx in tx_in_period
        )

        company_rows.append(
            CompanyDigestRow(
                entity_id=entity.id,
                name=entity.name,
                ticker=entity.ticker,
                buy_btc_week=trades.buy_btc,
                sell_btc_week=trades.sell_btc,
                buy_avg_price_week=trades.buy_avg_price,
                sell_avg_price_week=trades.sell_avg_price,
                net_btc_week=net,
                holdings_btc=btc,
                avg_price=float(avg_price) if avg_price else None,
                pnl=float(pnl) if pnl else None,
                sell_price_estimated=sell_estimated,
                has_trades=has_trades,
                net_source=net_source,
            )
        )

    etfs, etf_flow_days = await _aggregate_etf_flows(period_start, period_end, btc_now)
    for etf in etfs:
        if abs(etf.net_flow_btc) >= 0.01:
            whale_candidates.append((etf.ticker, etf.net_flow_btc))

    whale_name: str | None = None
    whale_net: float | None = None
    largest = largest_trade_in_period(period_start, period_end)
    if largest:
        wname, wbtc, wside = largest
        whale_name = f"{wname} ({wside})"
        whale_net = wbtc if wside == "buy" else -wbtc
    elif whale_candidates:
        whale_name, whale_net = max(whale_candidates, key=lambda x: abs(x[1]))

    btc_chg = None
    if btc_now and btc_week_ago and btc_week_ago > 0:
        btc_chg = (btc_now - btc_week_ago) / btc_week_ago * 100.0

    if not company_rows and not etfs:
        return None

    return WeeklyDigestData(
        period_start=period_start,
        period_end=period_end,
        period_label=_format_period_label(period_start, period_end),
        companies=company_rows,
        etfs=etfs,
        btc_price_now=btc_now,
        btc_price_week_ago=btc_week_ago,
        btc_week_change_pct=btc_chg,
        total_tracked_btc=total_tracked,
        whale_name=whale_name,
        whale_net_btc=whale_net,
        etf_flow_days=etf_flow_days,
    )


def _fmt_btc(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):,.1f}".rstrip("0").rstrip(".")


def _fmt_usd_compact(value: float | None) -> str:
    if value is None:
        return "—"
    abs_v = abs(value)
    sign = "+" if value > 0 else "−" if value < 0 else ""
    if abs_v >= 1e9:
        return f"{sign}${abs_v / 1e9:.1f}B"
    if abs_v >= 1e6:
        return f"{sign}${abs_v / 1e6:.1f}M"
    if abs_v >= 1e3:
        return f"{sign}${abs_v / 1e3:.1f}K"
    return f"{sign}${abs_v:,.0f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_btc_qty(value: float) -> str:
    if value <= 0:
        return "—"
    return _fmt_btc(value).lstrip("+")


def _fmt_btc_abs(value: float | None) -> str:
    """Абсолютный баланс BTC без знака +/-."""
    if value is None:
        return "—"
    return f"{abs(value):,.1f}".rstrip("0").rstrip(".")


def _fmt_usd_level(value: float | None) -> str:
    """Спот/уровень цены USD без знака +/-."""
    if value is None:
        return "—"
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"${abs_v / 1e9:.1f}B"
    if abs_v >= 1e6:
        return f"${abs_v / 1e6:.1f}M"
    if abs_v >= 1e3:
        return f"${abs_v / 1e3:.1f}K"
    return f"${abs_v:,.0f}"


def _corp_ticker_label(row: CompanyDigestRow) -> str:
    if row.ticker:
        return f"{row.name} ({row.ticker})"
    return row.name


def _resolve_whale_label(data: WeeklyDigestData) -> str | None:
    if not data.whale_name:
        return None
    name_part = data.whale_name
    side_suffix = ""
    if " (" in data.whale_name and data.whale_name.endswith(")"):
        idx = data.whale_name.rfind(" (")
        name_part = data.whale_name[:idx]
        side_suffix = data.whale_name[idx:]
    for row in data.companies:
        if row.name == name_part or row.ticker == name_part:
            return f"{row.name} ({row.ticker}){side_suffix}"
    for row in data.etfs:
        if row.ticker == name_part:
            return row.ticker
    return data.whale_name


def _whale_already_in_wow(data: WeeklyDigestData, prev_entities: dict[str, Any]) -> bool:
    """Крупнейшая сделка уже отражена в WoW по holdings — не дублировать Top mover."""
    if not data.whale_name:
        return False
    name_part = data.whale_name.split(" (")[0] if " (" in data.whale_name else data.whale_name
    for row in data.companies:
        if row.name != name_part and row.ticker != name_part:
            continue
        prev_row = prev_entities.get(row.entity_id)
        if not isinstance(prev_row, dict) or prev_row.get("btc") is None:
            return False
        try:
            prev_btc = float(prev_row["btc"])
        except (TypeError, ValueError):
            return False
        return abs(row.holdings_btc - prev_btc) >= 0.01
    return False


def _fmt_net_cell(row: CompanyDigestRow) -> str:
    """NET: trades, holdings Δ (†), или idle (нет сделок и нет изменения HOLD)."""
    if row.net_source == "holdings" and row.net_btc_week is not None:
        formatted = _fmt_btc(row.net_btc_week)
        return f"{formatted}†" if formatted != "—" else formatted
    if row.net_source == "trades":
        return _fmt_btc(row.net_btc_week)
    if row.has_trades:
        return _fmt_btc(row.net_btc_week)
    return "idle"


def build_card_data(data: WeeklyDigestData) -> "WeeklyDigestCardData":
    from cards import WeeklyDigestCardData

    company_lines = []
    for row in data.companies:
        ticker = f" ({row.ticker})" if row.ticker else ""
        sell_avg = _fmt_usd_compact(row.sell_avg_price_week)
        if row.sell_price_estimated and row.sell_avg_price_week:
            sell_avg = f"{sell_avg}*"
        company_lines.append(
            (
                f"{row.name}{ticker}",
                _fmt_btc_qty(row.buy_btc_week),
                _fmt_usd_compact(row.buy_avg_price_week),
                _fmt_btc_qty(row.sell_btc_week),
                sell_avg,
                _fmt_net_cell(row),
                _fmt_btc(row.holdings_btc),
            )
        )

    etf_lines = []
    for row in data.etfs:
        if row.has_data:
            etf_lines.append(
                (
                    row.ticker,
                    _fmt_btc(row.net_flow_btc),
                    _fmt_usd_compact(row.net_flow_usd),
                    f"{_fmt_btc(row.best_day_btc)} ({row.best_day_date[5:]})",
                    f"{_fmt_btc(row.worst_day_btc)} ({row.worst_day_date[5:]})",
                )
            )
        else:
            etf_lines.append((row.ticker, "—", "—", "—", "—"))

    etf_suffix = ""
    if data.etf_flow_days and data.etf_flow_days < 7:
        etf_suffix = f" ({data.etf_flow_days}/7 days)"

    whale_line = "—"
    if data.whale_name and data.whale_net_btc is not None:
        whale_line = f"{data.whale_name}: {_fmt_btc(data.whale_net_btc)} BTC"

    market_line = (
        f"BTC {_fmt_pct(data.btc_week_change_pct)} · "
        f"Tracked {_fmt_btc(data.total_tracked_btc)} BTC"
    )
    if data.btc_price_now:
        market_line += f" · Spot {_fmt_usd_level(data.btc_price_now)}"

    return WeeklyDigestCardData(
        period_label=data.period_label,
        whale_line=whale_line,
        company_rows=company_lines,
        etf_rows=etf_lines,
        market_line=market_line,
        subtitle="PREMIUM WEEKLY · V2 TRADES",
        etf_section_suffix=etf_suffix,
    )


def format_caption(data: WeeklyDigestData, lang: str) -> str:
    caption = t(
        lang,
        "weekly_caption",
        period=data.period_label,
        whale=build_card_data(data).whale_line,
    )
    if data.etf_flow_days and data.etf_flow_days < 7:
        caption += f"\n⚠️ ETF flows: {data.etf_flow_days}/7 days (partial data)"
    return caption


def format_text_weekly_digest(data: WeeklyDigestData, lang: str) -> str:
    """Текстовая сводка для Free (без PNG)."""
    lines = [t(lang, "free_weekly_title", period=data.period_label)]

    strategy_row = next((r for r in data.companies if r.entity_id == "strategy"), None)
    if strategy_row and strategy_row.holdings_btc:
        lines.append(
            t(
                lang,
                "free_weekly_strategy",
                btc=_fmt_btc(strategy_row.holdings_btc),
                net=_fmt_net_cell(strategy_row),
            )
        )

    if data.whale_name and data.whale_net_btc is not None:
        lines.append(
            t(
                lang,
                "free_weekly_whale",
                name=data.whale_name,
                btc=_fmt_btc(data.whale_net_btc),
            )
        )

    etf_parts: list[str] = []
    for row in data.etfs[:4]:
        if abs(row.net_flow_btc) >= 0.01:
            etf_parts.append(f"{row.ticker} {_fmt_btc(row.net_flow_btc)}")
    if etf_parts:
        lines.append(t(lang, "free_weekly_etf", flows=", ".join(etf_parts)))

    if data.btc_week_change_pct is not None:
        lines.append(
            t(
                lang,
                "free_weekly_btc",
                pct=_fmt_pct(data.btc_week_change_pct),
                spot=_fmt_usd_level(data.btc_price_now) if data.btc_price_now else "—",
            )
        )

    lines.append("")
    lines.append(t(lang, "free_weekly_premium_hint"))
    if weekly_en_summary_enabled():
        summary = format_weekly_ticker_summary_en(data)
        if summary:
            lines.extend(["", summary])
    return "\n".join(lines)


def weekly_en_summary_enabled() -> bool:
    return WEEKLY_DIGEST_EN_SUMMARY_ENABLED


def _wow_holdings_line(label: str, delta: float | None, *, holdings: float) -> str:
    hold_txt = _fmt_btc_abs(holdings)
    if delta is None:
        return f"• {label}: no prior week baseline · holdings {hold_txt} BTC"
    if abs(delta) < 0.01:
        return f"• {label}: unchanged vs previous week · holdings {hold_txt} BTC"
    flow = "inflow" if delta > 0 else "outflow"
    return (
        f"• {label}: {flow} {_fmt_btc(abs(delta))} BTC vs previous week "
        f"· holdings {hold_txt} BTC"
    )


def _wow_etf_line(tick: str, current: float, previous: float | None, *, has_data: bool) -> str:
    if not has_data:
        return f"• {tick}: no ETF flow data this week"
    if previous is None:
        return f"• {tick}: {_fmt_btc(current)} BTC net this week (first ETF baseline)"
    delta = current - previous
    if abs(delta) < 0.01 and abs(current) < 0.01:
        return f"• {tick}: unchanged vs previous week (0 BTC net flows)"
    prev_txt = _fmt_btc(previous)
    curr_txt = _fmt_btc(current)
    if abs(delta) < 0.01:
        return f"• {tick}: {curr_txt} BTC net (same as previous week {prev_txt})"
    chg = _fmt_btc(delta)
    direction = "higher" if delta > 0 else "lower"
    return f"• {tick}: {curr_txt} BTC net this week vs {prev_txt} prior week (Δ {chg}, {direction})"


def format_weekly_ticker_summary_en(
    data: WeeklyDigestData,
    *,
    prev: dict[str, Any] | None = None,
) -> str:
    """Короткое EN-саммари: состояние тикеров + сравнение с прошлой неделей."""
    prev = prev if prev is not None else load_snapshot()
    prev_entities = prev.get("entities") if isinstance(prev.get("entities"), dict) else {}
    prev_etfs = prev.get("etfs") if isinstance(prev.get("etfs"), dict) else {}
    has_prior = bool(prev_entities or prev_etfs)

    lines = [f"📌 Weekly snapshot (EN) · {data.period_label}", ""]

    if data.btc_week_change_pct is not None:
        spot = _fmt_usd_level(data.btc_price_now) if data.btc_price_now else "—"
        lines.append(f"• BTC spot: {_fmt_pct(data.btc_week_change_pct)} over 7d · {spot}")

    prev_btc_price = prev.get("btc_price")
    if (
        has_prior
        and isinstance(prev_btc_price, (int, float))
        and data.btc_price_now
        and prev_btc_price > 0
    ):
        wow_pct = (data.btc_price_now - float(prev_btc_price)) / float(prev_btc_price) * 100.0
        lines.append(
            f"• BTC vs prior digest: {_fmt_pct(wow_pct)} "
            f"({_fmt_usd_level(float(prev_btc_price))} → {_fmt_usd_level(data.btc_price_now)})"
        )

    lines.append("")
    if has_prior:
        lines.append("📊 Week-over-week (vs previous digest):")
    else:
        lines.append("📊 Week-over-week: first digest baseline (no prior week yet):")

    for row in data.companies:
        label = _corp_ticker_label(row)
        prev_row = prev_entities.get(row.entity_id)
        prev_btc = None
        if isinstance(prev_row, dict) and prev_row.get("btc") is not None:
            try:
                prev_btc = float(prev_row["btc"])
            except (TypeError, ValueError):
                prev_btc = None
        delta = (row.holdings_btc - prev_btc) if prev_btc is not None else None
        lines.append(_wow_holdings_line(label, delta, holdings=row.holdings_btc))

    if data.etfs:
        lines.append("")
        lines.append("🏦 ETF weekly net flows:")
        for row in data.etfs:
            prev_row = prev_etfs.get(row.entity_id)
            prev_flow = None
            if isinstance(prev_row, dict) and prev_row.get("net_flow_btc") is not None:
                try:
                    prev_flow = float(prev_row["net_flow_btc"])
                except (TypeError, ValueError):
                    prev_flow = None
            lines.append(
                _wow_etf_line(
                    row.ticker,
                    row.net_flow_btc,
                    prev_flow,
                    has_data=row.has_data,
                )
            )

    prev_tracked = prev.get("total_tracked_btc")
    if has_prior and isinstance(prev_tracked, (int, float)) and data.total_tracked_btc > 0:
        tracked_delta = data.total_tracked_btc - float(prev_tracked)
        if abs(tracked_delta) < 0.01:
            lines.append(
                f"• All tracked treasuries: unchanged vs previous week "
                f"({_fmt_btc_abs(data.total_tracked_btc)} BTC)"
            )
        else:
            flow = "inflow" if tracked_delta > 0 else "outflow"
            lines.append(
                f"• All tracked treasuries: {flow} {_fmt_btc(abs(tracked_delta))} BTC WoW "
                f"· total {_fmt_btc_abs(data.total_tracked_btc)} BTC"
            )
    elif (
        data.whale_name
        and data.whale_net_btc is not None
        and not _whale_already_in_wow(data, prev_entities)
    ):
        whale_label = _resolve_whale_label(data) or data.whale_name
        lines.append(f"• Top mover this week: {whale_label} · {_fmt_btc(data.whale_net_btc)} BTC")

    lines.append("")
    lines.append("Public data only · not investment advice.")
    return "\n".join(lines)


async def _send_weekly_en_summary(bot, user_id: int, data: WeeklyDigestData) -> None:
    if not weekly_en_summary_enabled():
        return
    text = format_weekly_ticker_summary_en(data)
    if not text:
        return
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as exc:
        logger.warning("Weekly EN summary send failed user=%s: %s", user_id, exc)


async def deliver_weekly_digest(
    bot,
    user_ids: list[int],
    *,
    update_snapshot: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[int, WeeklyDigestData | None]:
    """Сгенерировать и отправить digest указанным user_id."""
    from cards import generate_weekly_digest_card

    data = await collect_weekly_digest()
    if data is None:
        if log_fn:
            log_fn("⚠️ Weekly digest: no data to send")
        return 0, None

    card_input = build_card_data(data)
    photo = generate_weekly_digest_card(card_input)
    sent = 0

    for uid in user_ids:
        lang = get_user_lang(uid)
        caption = format_caption(data, lang)
        try:
            if photo is not None:
                if hasattr(photo, "seek"):
                    photo.seek(0)
                await bot.send_photo(chat_id=uid, photo=photo, caption=caption)
            else:
                await bot.send_message(chat_id=uid, text=caption + "\n\n" + card_input.market_line)
            if weekly_en_summary_enabled():
                await _send_weekly_en_summary(bot, uid, data)
            sent += 1
        except Exception as exc:
            logger.warning("Weekly digest send failed user=%s: %s", uid, exc)

    if update_snapshot and data is not None and sent > 0:
        save_snapshot(data)

    if log_fn:
        log_fn(f"📊 Weekly digest sent to {sent}/{len(user_ids)} users ({data.period_label})")

    return sent, data


def premium_recipient_ids(*, include_admin_id: int | None) -> list[int]:
    ids: set[int] = set()
    if include_admin_id is not None:
        ids.add(include_admin_id)
    for sub in list_subscribers(active_premium_only=True):
        ids.add(sub.user_id)
    return sorted(ids)


def free_weekly_recipient_ids(*, include_admin_id: int | None = None) -> list[int]:
    from alert_delivery import list_known_user_ids
    from subscribers import effective_plan
    from subscription_plans import PlanId

    ids: set[int] = set()
    for uid in list_known_user_ids():
        if include_admin_id is not None and uid == include_admin_id:
            continue
        if effective_plan(uid) != PlanId.PREMIUM:
            ids.add(uid)
    return sorted(ids)


async def deliver_free_weekly_text_digest(
    bot,
    user_ids: list[int],
    *,
    data: WeeklyDigestData | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> tuple[int, WeeklyDigestData | None]:
    digest = data if data is not None else await collect_weekly_digest()
    if digest is None:
        if log_fn:
            log_fn("⚠️ Free weekly digest: no data")
        return 0, None

    sent = 0
    for uid in user_ids:
        lang = get_user_lang(uid)
        body = format_text_weekly_digest(digest, lang)
        try:
            await bot.send_message(chat_id=uid, text=body)
            sent += 1
        except Exception as exc:
            logger.warning("Free weekly digest send failed user=%s: %s", uid, exc)

    if log_fn:
        log_fn(
            f"📋 Free weekly text digest sent to {sent}/{len(user_ids)} "
            f"({digest.period_label})"
        )
    return sent, digest


async def run_scheduled_free_weekly_digest(
    bot, log_fn: Callable[[str], None] | None = None
) -> None:
    if not free_weekly_digest_enabled():
        return
    if free_weekly_already_sent():
        logger.info("Free weekly digest already sent for %s", period_key_for_moment())
        return

    period_key = period_key_for_moment()
    user_ids = free_weekly_recipient_ids()
    if not user_ids:
        if log_fn:
            log_fn("📋 Free weekly digest: no free recipients")
        return

    sent, _data = await deliver_free_weekly_text_digest(bot, user_ids, log_fn=log_fn)
    if sent > 0:
        mark_free_weekly_sent(period_key)


async def run_scheduled_weekly_digest(bot, log_fn: Callable[[str], None] | None = None) -> None:
    if not digest_enabled():
        return

    period_key = period_key_for_moment()
    premium_pending = not scheduled_already_sent()
    free_pending = free_weekly_digest_enabled() and not free_weekly_already_sent()
    if not premium_pending and not free_pending:
        logger.info("Weekly digest already sent for %s", period_key)
        return

    admin_id = None
    try:
        import main as app

        admin_id = app.alert_chat_id()
    except Exception:
        pass

    data: WeeklyDigestData | None = None
    if premium_pending:
        user_ids = premium_recipient_ids(include_admin_id=admin_id)
        if not user_ids:
            if log_fn:
                log_fn("📊 Weekly digest: no premium recipients")
        else:
            sent, data = await deliver_weekly_digest(
                bot, user_ids, update_snapshot=True, log_fn=log_fn
            )
            if sent > 0:
                mark_scheduled_sent(period_key)
            elif data is None and log_fn:
                log_fn("⚠️ Weekly digest: no data to send")

    if free_pending:
        free_ids = free_weekly_recipient_ids(include_admin_id=admin_id)
        if free_ids:
            fsent, digest = await deliver_free_weekly_text_digest(
                bot, free_ids, data=data, log_fn=log_fn
            )
            if fsent > 0:
                mark_free_weekly_sent(period_key)
            if data is None:
                data = digest
        elif log_fn:
            log_fn("📋 Free weekly digest: no free recipients")


async def weekly_digest_scheduler(bot, log_fn: Callable[[str], None] | None = None) -> None:
    """Фоновый цикл: каждое вс 12:00 NY → DM active Premium."""
    while True:
        if not digest_enabled():
            await asyncio.sleep(3600)
            continue
        delay = seconds_until_next_run()
        logger.info("Weekly digest next run in %.0f s", delay)
        await asyncio.sleep(delay)
        period = period_key_for_moment()
        for attempt in range(1, 4):
            try:
                await run_scheduled_weekly_digest(bot, log_fn=log_fn)
                if weekly_period_complete() or not digest_enabled():
                    break
                logger.warning(
                    "Weekly digest attempt %s failed for %s, retry in 5 min",
                    attempt,
                    period,
                )
                if log_fn:
                    log_fn(f"⚠️ Weekly digest retry {attempt}/3 for {period}")
                await asyncio.sleep(300)
            except Exception as exc:
                logger.exception("Weekly digest scheduler error")
                if log_fn:
                    log_fn(f"⚠️ Weekly digest scheduler error: {exc}")
                if attempt >= 3:
                    break
                await asyncio.sleep(300)
        if not weekly_period_complete():
            logger.warning("Weekly digest: giving up for %s after retries (will retry next week)", period)
            if log_fn:
                log_fn(f"⚠️ Weekly digest: giving up for {period} (send failed, not marked sent)")
        await asyncio.sleep(60)


__all__ = [
    "WEEKLY_DIGEST_HOUR",
    "WEEKLY_DIGEST_MINUTE",
    "WEEKLY_DIGEST_TIMEZONE",
    "CompanyDigestRow",
    "EtfDigestRow",
    "WeeklyDigestData",
    "collect_weekly_digest",
    "deliver_weekly_digest",
    "deliver_free_weekly_text_digest",
    "digest_enabled",
    "free_weekly_digest_enabled",
    "format_caption",
    "format_text_weekly_digest",
    "format_weekly_ticker_summary_en",
    "weekly_en_summary_enabled",
    "period_key_for_moment",
    "run_scheduled_weekly_digest",
    "run_scheduled_free_weekly_digest",
    "scheduled_already_sent",
    "free_weekly_already_sent",
    "seconds_until_next_run",
    "weekly_digest_scheduler",
]
