"""Мониторинг публичных компаний (CoinGecko treasury) — День 12."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from baseline import load_baseline, save_baseline
from entities import EntityConfig, enabled_entities
from i18n import t
from models import Holdings
from sources.coingecko_treasury import CoinGeckoTreasurySource, SOURCE_KEY

logger = logging.getLogger(__name__)


def _entity_id(holdings: Holdings) -> str:
    eid = holdings.meta.get("entity_id")
    if eid:
        return str(eid).lower()
    return holdings.entity_id


def _stats_from_holdings(h: Holdings) -> dict[str, Any]:
    return {
        "btc": h.btc,
        "avg_price": h.avg_price,
        "pnl": h.pnl,
        "market_value": h.usd_value,
    }


async def run_companies_check(
    bot,
    lang: str | None = None,
    *,
    send_alerts: bool = True,
) -> list[str]:
    """Проверить enabled-компании CoinGecko. Возвращает строки-отчёты."""
    # Lazy import — избегаем цикла при загрузке main.py
    import main as app

    msg_lang = lang or app.alert_lang()
    tracked = [e for e in enabled_entities() if e.source == SOURCE_KEY]
    if not tracked:
        return []

    snapshots = await CoinGeckoTreasurySource().fetch()
    if not snapshots:
        return [t(msg_lang, "check_companies_fetch_error")]

    by_id = {_entity_id(h): h for h in snapshots}
    summaries: list[str] = []

    for entity in tracked:
        line = await _check_one_entity(
            bot,
            entity,
            by_id.get(entity.id),
            lang=msg_lang,
            send_alerts=send_alerts,
            app=app,
        )
        if line:
            summaries.append(line)

    return summaries


async def _check_one_entity(
    bot,
    entity: EntityConfig,
    holdings: Holdings | None,
    *,
    lang: str,
    send_alerts: bool,
    app: Any,
) -> str | None:
    if holdings is None:
        app.write_log(f"⚠️ [{entity.id}] no CoinGecko data")
        return t(lang, "check_entity_missing", entity=entity.name)

    previous = load_baseline(entity.id)
    previous_btc = previous.btc if previous else None
    current_btc = holdings.btc
    threshold = entity.min_btc_change

    if previous_btc is None:
        save_baseline(
            entity.id,
            btc=current_btc,
            name=entity.name,
            usd=holdings.usd_value,
            source=holdings.source,
        )
        app.write_log(f"📊 Baseline saved [{entity.id}]: {app.format_btc(current_btc)} BTC")
        return t(lang, "check_entity_baseline_saved", entity=entity.name, btc=app.format_btc(current_btc))

    delta = current_btc - previous_btc
    if abs(delta) < threshold:
        app.write_log(f"ℹ️ [{entity.id}] no significant change.")
        return t(
            lang,
            "check_entity_no_change",
            entity=entity.name,
            current=app.format_btc(current_btc),
            baseline=app.format_btc(previous_btc),
            threshold=threshold,
        )

    if not send_alerts:
        sign = "+" if delta > 0 else ""
        return t(
            lang,
            "check_entity_would_alert",
            entity=entity.name,
            delta=f"{sign}{app.format_btc(delta)}",
        )

    increased = delta > 0
    btc_price = holdings.price or (
        holdings.usd_value / current_btc if holdings.usd_value and current_btc else 0.0
    )
    delta_usd = abs(delta) * btc_price if btc_price else 0.0
    date = datetime.date.today().isoformat()

    alert_text = app.format_premium_alert(
        delta_btc=delta,
        delta_usd=delta_usd,
        total_btc=current_btc,
        buy_price=btc_price if increased else 0.0,
        date=date,
        stats=_stats_from_holdings(holdings),
        increased=increased,
        lang=lang,
        entity=entity.name,
    )
    delivered = await app.send_alert_with_card(
        bot,
        text=alert_text,
        delta_btc=delta,
        delta_usd=delta_usd,
        total_btc=current_btc,
        date=date,
        increased=increased,
        entity=entity.name,
        entity_id=entity.id,
        stats=_stats_from_holdings(holdings),
        buy_price=btc_price if increased else 0.0,
    )
    if delivered > 0:
        save_baseline(
            entity.id,
            btc=current_btc,
            name=entity.name,
            usd=holdings.usd_value,
            source=holdings.source,
        )
        if increased:
            app.write_log(f"🚨 [{entity.id}] Purchase: +{app.format_btc(delta)} BTC")
            return t(lang, "check_entity_purchase_sent", entity=entity.name, delta=app.format_btc(delta))
        app.write_log(f"🚨 [{entity.id}] Sale: {app.format_btc(delta)} BTC")
        return t(lang, "check_entity_sale_sent", entity=entity.name, delta=app.format_btc(delta))
    app.write_log(f"⚠️ [{entity.id}] Alert not delivered — baseline kept")
    return t(lang, "check_fetch_error")
