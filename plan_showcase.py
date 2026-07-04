"""Витрина тарифов на /start: мини-карточки сигналов Free и Premium."""

from __future__ import annotations

import io
import json
import logging
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cards import (
    CardData,
    compose_showcase_collage,
    compose_showcase_grid,
    generate_card,
    thumbnail_card,
)
from entities import find_entity_by_name
from i18n import DEFAULT_LANG, t
from models import EntityType
from transactions import Transaction, list_transactions

logger = logging.getLogger(__name__)

SHOWCASE_FILE = Path(
    os.environ.get("PLAN_SHOWCASE_FILE", "assets/plan_showcase_signals.json")
)
START_SHOWCASE_ENABLED = os.environ.get("START_SHOWCASE_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

SignalSide = Literal["buy", "sell", "inflow", "outflow"]

_DEFAULT_HOLDINGS: dict[str, float] = {
    "strategy": 847_363,
    "tesla": 11_509,
    "block": 9_032,
    "mara": 35_303,
    "riot": 15_680,
    "metaplanet": 43_000,
}


@dataclass(frozen=True)
class ShowcaseSignal:
    entity_id: str
    entity_name: str
    side: SignalSide
    btc: float
    usd_value: float
    date: str
    holdings_btc: float = 0.0
    buy_price: float = 0.0
    is_etf: bool = False
    source: str = "showcase"

    @property
    def increased(self) -> bool:
        return self.side in {"buy", "inflow"}


def showcase_enabled() -> bool:
    return START_SHOWCASE_ENABLED


def _is_strategy(name: str) -> bool:
    n = name.lower()
    return "microstrategy" in n or n == "strategy" or "strategy inc" in n


def _card_title(entity: str, *, increased: bool, is_etf: bool) -> str:
    if _is_strategy(entity):
        raw = t(DEFAULT_LANG, "alert_buy_title" if increased else "alert_sell_title")
        return re.sub(r"^[^\x00-\x7f]+\s*", "", raw)
    if is_etf:
        action = "ETF INFLOW" if increased else "ETF OUTFLOW"
        return f"{entity.upper()} · {action}"
    action = "BITCOIN BUY" if increased else "BITCOIN SELL"
    return f"{entity.upper()} · {action}"


def _card_kind(entity: str, *, is_etf: bool) -> str:
    cfg = find_entity_by_name(entity)
    if _is_strategy(entity):
        return t(DEFAULT_LANG, "card_kind_treasury")
    if is_etf:
        kind = t(DEFAULT_LANG, "card_kind_etf")
    else:
        kind = t(DEFAULT_LANG, "card_kind_company")
    if cfg and cfg.ticker:
        return f"{kind} · {cfg.ticker}"
    return kind


def _fmt_btc(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _fmt_usd_compact(value: float) -> str:
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"${abs_v / 1e9:.1f}B"
    if abs_v >= 1e6:
        return f"${abs_v / 1e6:.1f}M"
    if abs_v >= 1e3:
        return f"${abs_v / 1e3:.1f}K"
    return f"${abs_v:,.0f}"


def _tx_to_signal(tx: Transaction) -> ShowcaseSignal:
    eid = tx.entity_id.lower()
    cfg = find_entity_by_name(tx.entity_name)
    is_etf = bool(cfg and cfg.type == EntityType.ETF)
    side: SignalSide = tx.side
    if is_etf:
        side = "inflow" if tx.side == "buy" else "outflow"
    holdings = _DEFAULT_HOLDINGS.get(eid, 0.0)
    return ShowcaseSignal(
        entity_id=eid,
        entity_name=tx.entity_name,
        side=side,
        btc=tx.btc,
        usd_value=tx.usd_value or tx.btc * (tx.price_usd or 0),
        date=tx.date,
        holdings_btc=holdings,
        buy_price=tx.price_usd if tx.side == "buy" and not tx.price_estimated else 0.0,
        is_etf=is_etf,
        source=tx.source,
    )


def _parse_fixture(raw: dict) -> ShowcaseSignal | None:
    try:
        side = str(raw.get("side", "")).lower()
        if side not in {"buy", "sell", "inflow", "outflow"}:
            return None
        btc = float(raw.get("btc", 0))
        if btc <= 0:
            return None
        eid = str(raw.get("entity_id", "")).lower()
        name = str(raw.get("entity_name") or eid)
        is_etf = bool(raw.get("is_etf")) or eid in {"ibit", "fbtc", "gbtc", "ark"}
        usd = float(raw.get("usd_value") or 0)
        return ShowcaseSignal(
            entity_id=eid,
            entity_name=name,
            side=side,  # type: ignore[arg-type]
            btc=btc,
            usd_value=usd,
            date=str(raw.get("date") or "—"),
            holdings_btc=float(raw.get("holdings_btc") or _DEFAULT_HOLDINGS.get(eid, 0)),
            buy_price=float(raw.get("buy_price") or 0),
            is_etf=is_etf,
            source=str(raw.get("source") or "showcase"),
        )
    except (TypeError, ValueError):
        return None


def load_showcase_pool() -> list[ShowcaseSignal]:
    pool: list[ShowcaseSignal] = []
    for tx in list_transactions():
        pool.append(_tx_to_signal(tx))

    path = SHOWCASE_FILE
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data.get("signals") if isinstance(data, dict) else None
            if isinstance(rows, list):
                for raw in rows:
                    if isinstance(raw, dict):
                        sig = _parse_fixture(raw)
                        if sig:
                            pool.append(sig)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("plan showcase fixtures: %s", exc)

    return pool


def _dedupe_pool(pool: list[ShowcaseSignal]) -> list[ShowcaseSignal]:
    seen: set[tuple[str, str, float, str]] = set()
    out: list[ShowcaseSignal] = []
    for sig in pool:
        key = (sig.entity_id, sig.side, round(sig.btc, 2), sig.date)
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out


def signal_to_card(sig: ShowcaseSignal) -> io.BytesIO | None:
    delta_str = f"{'+' if sig.increased else '−'}{_fmt_btc(sig.btc)} BTC"
    if sig.is_etf:
        panel_value = delta_str
    else:
        panel_value = f"{_fmt_btc(sig.holdings_btc)} BTC" if sig.holdings_btc else delta_str
    return generate_card(
        CardData(
            title=_card_title(sig.entity_name, increased=sig.increased, is_etf=sig.is_etf),
            delta_btc=delta_str,
            delta_usd=f"≈ {_fmt_usd_compact(sig.usd_value)}" if sig.usd_value else "",
            total_btc=panel_value,
            date=sig.date,
            is_sale=not sig.increased,
            compact=not _is_strategy(sig.entity_name),
            kind_label=_card_kind(sig.entity_name, is_etf=sig.is_etf),
            panel_label=t(DEFAULT_LANG, "card_panel_flow" if sig.is_etf else "card_panel_holdings"),
            strategy_style=_is_strategy(sig.entity_name),
        )
    )


def _pick_one(pool: list[ShowcaseSignal], pred) -> ShowcaseSignal | None:
    matches = [s for s in pool if pred(s)]
    return random.choice(matches) if matches else None


def pick_free_showcase(pool: list[ShowcaseSignal]) -> list[ShowcaseSignal]:
    """Две карточки покупок Strategy для Free-витрины."""
    strategy_buys = [
        s for s in pool if s.entity_id == "strategy" and s.side == "buy" and not s.is_etf
    ]
    if len(strategy_buys) >= 2:
        return random.sample(strategy_buys, 2)
    if strategy_buys:
        return strategy_buys[:1] * 2 if len(strategy_buys) == 1 else strategy_buys
    return []


def pick_premium_showcase(pool: list[ShowcaseSignal]) -> list[ShowcaseSignal]:
    """5 карточек: Strategy, company buy/sell, ETF in/out."""
    picks: list[ShowcaseSignal] = []
    for pred in (
        lambda s: s.entity_id == "strategy" and s.side == "buy",
        lambda s: not s.is_etf and s.entity_id != "strategy" and s.side == "buy",
        lambda s: not s.is_etf and s.entity_id != "strategy" and s.side == "sell",
        lambda s: s.is_etf and s.side == "inflow",
        lambda s: s.is_etf and s.side == "outflow",
    ):
        sig = _pick_one(pool, pred)
        if sig:
            picks.append(sig)
    return picks


def build_showcase_thumbs(signals: list[ShowcaseSignal], *, max_width: int = 400) -> list[io.BytesIO]:
    thumbs: list[io.BytesIO] = []
    for sig in signals:
        card = signal_to_card(sig)
        if not card:
            continue
        thumb = thumbnail_card(card, max_width=max_width)
        if thumb:
            thumbs.append(thumb)
    return thumbs


def build_start_showcase_images(
    free_signals: list[ShowcaseSignal],
    premium_signals: list[ShowcaseSignal],
    lang: str,
) -> tuple[io.BytesIO | None, io.BytesIO | None]:
    """Коллажи для /start: Free (2 Strategy) и Premium (5 сигналов)."""
    use_ru = lang == "ru"
    free_thumbs = build_showcase_thumbs(free_signals, max_width=340)
    prem_thumbs = build_showcase_thumbs(premium_signals, max_width=280)

    free_title = "FREE · Strategy buy alerts" if not use_ru else "FREE · Покупки Strategy"
    prem_title = "PREMIUM · Multi-whale signals" if not use_ru else "PREMIUM · Все киты"

    free_col = compose_showcase_collage(free_thumbs, title=free_title) if free_thumbs else None
    prem_col = (
        compose_showcase_grid(prem_thumbs, title=prem_title, cols=3, thumb_w=260)
        if prem_thumbs
        else None
    )
    return free_col, prem_col


def build_social_collages(
    free_signals: list[ShowcaseSignal],
    premium_signals: list[ShowcaseSignal],
) -> tuple[io.BytesIO | None, io.BytesIO | None]:
    free_imgs = build_showcase_thumbs(free_signals, max_width=360)
    prem_imgs = build_showcase_thumbs(premium_signals, max_width=300)
    free_col = compose_showcase_collage(free_imgs, title="FREE · Strategy alerts") if free_imgs else None
    prem_col = (
        compose_showcase_collage(prem_imgs, title="PREMIUM · Multi-whale cards")
        if prem_imgs
        else None
    )
    return free_col, prem_col


def get_showcase_sets() -> tuple[list[ShowcaseSignal], list[ShowcaseSignal]]:
    pool = _dedupe_pool(load_showcase_pool())
    return pick_free_showcase(pool), pick_premium_showcase(pool)


_START_CACHE_VARIANTS = max(1, int(os.environ.get("START_SHOWCASE_CACHE_VARIANTS", "2")))
_start_showcase_cache: dict[str, list[tuple[io.BytesIO | None, io.BytesIO | None]]] = {}


def _clone_bytesio(src: io.BytesIO | None, *, name: str) -> io.BytesIO | None:
    if src is None:
        return None
    src.seek(0)
    out = io.BytesIO(src.read())
    out.name = getattr(src, "name", None) or name
    out.seek(0)
    return out


def warm_start_showcase_cache(*, variants: int | None = None) -> int:
    """Предгенерация коллажей /start (CPU) — вызывать при старте бота в фоне."""
    n_var = variants if variants is not None else _START_CACHE_VARIANTS
    built = 0
    for lang in ("en", "ru"):
        pool: list[tuple[io.BytesIO | None, io.BytesIO | None]] = []
        for _ in range(n_var):
            free_sigs, prem_sigs = get_showcase_sets()
            free_col, prem_col = build_start_showcase_images(free_sigs, prem_sigs, lang)
            pool.append(
                (
                    _clone_bytesio(free_col, name="start_free.png"),
                    _clone_bytesio(prem_col, name="start_premium.png"),
                )
            )
            built += 1
        _start_showcase_cache[lang] = pool
    logger.info("Start showcase cache warmed: %s variants × 2 langs", n_var)
    return built


def get_cached_start_showcase(lang: str) -> tuple[io.BytesIO | None, io.BytesIO | None]:
    """Готовые коллажи для мгновенной отправки на /start."""
    key = lang if lang in {"ru", "en"} else "en"
    pool = _start_showcase_cache.get(key) or _start_showcase_cache.get("en") or []
    if pool:
        free_col, prem_col = random.choice(pool)
        return (
            _clone_bytesio(free_col, name="start_free.png"),
            _clone_bytesio(prem_col, name="start_premium.png"),
        )
    free_sigs, prem_sigs = get_showcase_sets()
    return build_start_showcase_images(free_sigs, prem_sigs, key)


def start_showcase_cache_ready(lang: str) -> bool:
    key = lang if lang in {"ru", "en"} else "en"
    return bool(_start_showcase_cache.get(key))


def format_social_tiers_summary(lang: str) -> str:
    from social_growth import bot_link, bot_mention, x_post_disclaimer

    link = bot_link()
    mention = bot_mention()
    if lang == "ru":
        body = (
            "🟠 SaylorWatch — как выглядят алерты в Telegram\n\n"
            "🆓 FREE\n"
            "• Покупки Strategy (Saylor) — текст + до 1 PNG/нед\n"
            "• Задержка ~15 мин · еженедельная текстовая сводка\n"
            "• /holdings /stats /whales топ-7\n\n"
            "⭐ PREMIUM\n"
            "• Мгновенные карточки по Strategy, компаниям и ETF\n"
            "• Tesla · MARA · Block · Metaplanet · IBIT · FBTC · GBTC · ARKB\n"
            "• Weekly PNG-дайджест · /whales топ-10\n\n"
            f"Попробовать → {link}\n"
            f"Premium: {mention} → /subscribe"
        )
    else:
        body = (
            "🟠 SaylorWatch — what alerts look like in Telegram\n\n"
            "🆓 FREE\n"
            "• Strategy (Saylor) buy alerts — text + up to 1 PNG/week\n"
            "• ~15 min delay · Sunday text weekly summary\n"
            "• /holdings /stats /whales top 7\n\n"
            "⭐ PREMIUM\n"
            "• Instant cards for Strategy, companies & ETFs\n"
            "• Tesla · MARA · Block · Metaplanet · IBIT · FBTC · GBTC · ARKB\n"
            "• Weekly PNG digest · /whales top 10\n\n"
            f"Try it → {link}\n"
            f"Premium: {mention} → /subscribe"
        )
    return f"{body}\n\n{x_post_disclaimer()}\n\n#Bitcoin #BTC #MicroStrategy #Saylor"


__all__ = [
    "SHOWCASE_FILE",
    "ShowcaseSignal",
    "build_start_showcase_images",
    "build_showcase_thumbs",
    "build_social_collages",
    "format_social_tiers_summary",
    "load_showcase_pool",
    "pick_free_showcase",
    "pick_premium_showcase",
    "get_showcase_sets",
    "get_cached_start_showcase",
    "warm_start_showcase_cache",
    "start_showcase_cache_ready",
    "showcase_enabled",
    "signal_to_card",
]
