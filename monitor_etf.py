"""Мониторинг ETF-потоков (Farside) — День 13."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from baseline import Baseline, load_baseline, save_baseline
from entities import EntityConfig, enabled_entities
from i18n import t
from models import Holdings
from sources.farside_etf import FarsideEtfSource, SOURCE_KEY, fetch_entity_etf_flow_series

logger = logging.getLogger(__name__)


def _entity_id(holdings: Holdings) -> str:
    eid = holdings.meta.get("entity_id")
    if eid:
        return str(eid).lower()
    return holdings.entity_id


async def run_etf_check(
    bot,
    lang: str | None = None,
    *,
    send_alerts: bool = True,
) -> list[str]:
    """Проверить enabled ETF Farside. Возвращает строки-отчёты."""
    import main as app

    msg_lang = lang or app.alert_lang()
    tracked = [e for e in enabled_entities() if e.source == SOURCE_KEY]
    if not tracked:
        return []

    snapshots = await FarsideEtfSource().fetch()
    if not snapshots:
        app.last_monitor_error = t(msg_lang, "check_etf_fetch_error")
        return [t(msg_lang, "check_etf_fetch_error")]

    by_id = {_entity_id(h): h for h in snapshots}
    summaries: list[str] = []

    for entity in tracked:
        line = await _check_one_etf(
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


async def _apply_etf_flow(
    bot,
    entity: EntityConfig,
    holdings: Holdings,
    *,
    lang: str,
    send_alerts: bool,
    app: Any,
    previous: Baseline | None,
) -> tuple[str | None, Baseline | None]:
    flow_date = holdings.date
    flow_btc = float(holdings.change or 0.0)
    flow_usd = float(holdings.usd_value or 0.0)
    threshold = entity.min_btc_change

    if previous is None or not previous.flow_date:
        save_baseline(
            entity.id,
            btc=abs(flow_btc),
            name=entity.name,
            usd=flow_usd,
            source=holdings.source,
            flow_date=flow_date,
        )
        app.write_log(
            f"📊 ETF baseline [{entity.id}] {flow_date}: "
            f"{app.format_btc(abs(flow_btc))} BTC flow"
        )
        return (
            t(
                lang,
                "check_etf_baseline_saved",
                entity=entity.name,
                date=flow_date,
                btc=app.format_btc(abs(flow_btc)),
            ),
            load_baseline(entity.id),
        )

    if previous.flow_date == flow_date:
        prev_usd = float(previous.usd or 0)
        prev_btc = float(previous.btc or 0)
        usd_changed = abs(flow_usd - prev_usd)
        btc_changed = abs(abs(flow_btc) - prev_btc)
        # Реальная ревизия Farside — заметное изменение USD; иначе шум SoSoValue/цены BTC
        material_revision = usd_changed >= max(250_000.0, abs(prev_usd) * 0.01)
        if not material_revision:
            if usd_changed > 1.0 or btc_changed > 0.01:
                save_baseline(
                    entity.id,
                    btc=abs(flow_btc),
                    name=entity.name,
                    usd=flow_usd,
                    source=holdings.source,
                    flow_date=flow_date,
                )
            logger.debug("[%s] ETF flow already processed for %s", entity.id, flow_date)
            return (
                t(
                    lang,
                    "check_etf_no_flow",
                    entity=entity.name,
                    date=flow_date,
                    flow=app.format_btc(abs(flow_btc)),
                    threshold=threshold,
                ),
                load_baseline(entity.id),
            )
        app.write_log(
            f"ℹ️ [{entity.id}] ETF flow revised for {flow_date} "
            f"(USD Δ ${usd_changed:,.0f})"
        )

    if previous.flow_date and flow_date and previous.flow_date > flow_date:
        app.write_log(f"ℹ️ [{entity.id}] ETF flow date {flow_date} older than baseline {previous.flow_date}")
        return (
            t(
                lang,
                "check_etf_no_flow",
                entity=entity.name,
                date=flow_date,
                flow=app.format_btc(abs(flow_btc)),
                threshold=threshold,
            ),
            previous,
        )

    if abs(flow_btc) < threshold:
        save_baseline(
            entity.id,
            btc=abs(flow_btc),
            name=entity.name,
            usd=flow_usd,
            source=holdings.source,
            flow_date=flow_date,
        )
        app.write_log(
            f"ℹ️ [{entity.id}] ETF flow {flow_date} below threshold "
            f"({app.format_btc(abs(flow_btc))} < {threshold})"
        )
        return (
            t(
                lang,
                "check_etf_no_flow",
                entity=entity.name,
                date=flow_date,
                flow=app.format_btc(abs(flow_btc)),
                threshold=threshold,
            ),
            load_baseline(entity.id),
        )

    if not send_alerts:
        sign = "+" if flow_btc > 0 else ""
        return (
            t(
                lang,
                "check_etf_would_alert",
                entity=entity.name,
                date=flow_date,
                delta=f"{sign}{app.format_btc(flow_btc)}",
            ),
            previous,
        )

    inflow = flow_btc > 0
    alert_text = app.format_etf_flow_alert(
        entity=entity.name,
        flow_btc=flow_btc,
        flow_usd=flow_usd,
        flow_date=flow_date,
        inflow=inflow,
        lang=lang,
    )
    alert_instant, _alert_queued = await app.send_alert_with_card(
        bot,
        text=alert_text,
        delta_btc=flow_btc,
        delta_usd=flow_usd,
        total_btc=0.0,
        date=flow_date,
        increased=inflow,
        entity=entity.name,
        entity_id=entity.id,
        is_etf=True,
    )
    if alert_instant + _alert_queued <= 0:
        app.write_log(f"⚠️ [{entity.id}] ETF alert not delivered — baseline kept")
        return (
            t(
                lang,
                "check_etf_no_flow",
                entity=entity.name,
                date=flow_date,
                flow=app.format_btc(abs(flow_btc)),
                threshold=threshold,
            ),
            previous,
        )

    save_baseline(
        entity.id,
        btc=abs(flow_btc),
        name=entity.name,
        usd=flow_usd,
        source=holdings.source,
        flow_date=flow_date,
    )

    if inflow:
        app.write_log(
            f"🚨 [{entity.id}] ETF inflow {flow_date}: +{app.format_btc(flow_btc)} BTC"
        )
        line = t(
            lang,
            "check_etf_inflow_sent",
            entity=entity.name,
            date=flow_date,
            delta=app.format_btc(flow_btc),
        )
    else:
        app.write_log(
            f"🚨 [{entity.id}] ETF outflow {flow_date}: {app.format_btc(flow_btc)} BTC"
        )
        line = t(
            lang,
            "check_etf_outflow_sent",
            entity=entity.name,
            date=flow_date,
            delta=app.format_btc(flow_btc),
        )
    return line, load_baseline(entity.id)


async def _check_one_etf(
    bot,
    entity: EntityConfig,
    holdings: Holdings | None,
    *,
    lang: str,
    send_alerts: bool,
    app: Any,
) -> str | None:
    if holdings is None:
        app.write_log(f"⚠️ [{entity.id}] no Farside ETF data")
        return t(lang, "check_etf_missing", entity=entity.name)

    flow_date = holdings.date or ""
    previous = load_baseline(entity.id)

    if previous and previous.flow_date and flow_date:
        try:
            prev_d = datetime.date.fromisoformat(previous.flow_date)
            cur_d = datetime.date.fromisoformat(flow_date)
            gap = (cur_d - prev_d).days
        except ValueError:
            gap = 0
        if gap > 1:
            series = await fetch_entity_etf_flow_series(
                entity,
                since_date_exclusive=previous.flow_date,
                until_date_inclusive=flow_date,
            )
            if series:
                last_line: str | None = None
                bl = previous
                for h in series:
                    last_line, bl = await _apply_etf_flow(
                        bot, entity, h, lang=lang, send_alerts=send_alerts, app=app, previous=bl
                    )
                return last_line

    line, _ = await _apply_etf_flow(
        bot, entity, holdings, lang=lang, send_alerts=send_alerts, app=app, previous=previous
    )
    return line
