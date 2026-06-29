"""Ежедневный пост CoinGecko-таблиц в Telegram-канал @Paper_wallet_co.

Запускается фоновым планировщиком в main.py на сервере (JustRunMy) — ПК не нужен.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
import os
import random
import string
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime as dt_datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from json_store import atomic_write_json, json_rw_lock, read_json_file

logger = logging.getLogger(__name__)

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

PAPER_WALLET_ENABLED = os.environ.get("PAPER_WALLET_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PAPER_WALLET_CHANNEL = os.environ.get("PAPER_WALLET_CHANNEL", "@Paper_wallet_co").strip()
PAPER_WALLET_TIMEZONE = os.environ.get("PAPER_WALLET_TIMEZONE", "Europe/Moscow")
PAPER_WALLET_POST_HOUR = int(os.environ.get("PAPER_WALLET_POST_HOUR", "12"))
PAPER_WALLET_POST_MINUTE = int(os.environ.get("PAPER_WALLET_POST_MINUTE", "0"))
STATE_FILE = Path(os.environ.get("PAPER_WALLET_STATE_FILE", "paper_wallet_state.json"))

BG = (23, 24, 27)
BG_HEADER = (30, 32, 38)
BG_ROW_ALT = (26, 27, 31)
TEXT = (234, 236, 239)
TEXT_DIM = (141, 146, 157)
GREEN = (22, 199, 132)
RED = (234, 57, 67)
ACCENT = (88, 166, 255)
PROMO_BG = (18, 19, 22)
CARD_BG = (32, 33, 38)
ICON_SIZE = 28

DECOR_SYMBOLS = ("₿", "Ξ", "◎", "◆", "●", "▲", "▼", "◈", "⬡", "◉")

_SEP_SYMBOLS = ';"%+-=*#@&|~.:!?[](){}^$'


def _random_separator_line(min_len: int = 38, max_len: int = 62) -> str:
    """Одна монолитная строка: буквы, цифры, символы без пробелов и ;."""
    pool = string.ascii_letters + string.digits + _SEP_SYMBOLS
    length = random.randint(min_len, max_len)
    return "".join(random.choice(pool) for _ in range(length))


def build_random_separator_block() -> str:
    """Одна монолитная строка-разделитель."""
    return _random_separator_line()


def build_ticker_line(symbols: list[str]) -> str:
    """Среднее сообщение между таблицами — реклама SaylorWatch (не тикеры)."""
    _ = symbols
    return (
        f"🟠 {bot_name()} — Strategy BTC buys/sells, ETF flows, corporate treasuries\n"
        f"Free Telegram alerts with auto cards → {bot_link()}"
    )


@dataclass(frozen=True)
class MarketRow:
    rank: int
    name: str
    symbol: str
    price: float
    change_1h: float | None
    change_24h: float | None
    change_7d: float | None
    market_cap: float
    volume: float
    image_url: str = ""


@dataclass(frozen=True)
class GlobalSnapshot:
    total_market_cap_usd: float
    total_volume_24h_usd: float
    market_cap_change_24h: float
    btc_dominance: float
    summary: str


def paper_wallet_enabled() -> bool:
    return PAPER_WALLET_ENABLED and bool(PAPER_WALLET_CHANNEL)


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def min_volume_usd() -> float:
    return _env_float("PAPER_WALLET_MIN_VOLUME_USD", 100_000.0)


def bot_link() -> str:
    return os.environ.get("PAPER_WALLET_BOT_LINK", "https://t.me/Saylor_w_bot").strip()


def bot_name() -> str:
    return os.environ.get("PAPER_WALLET_BOT_NAME", "SaylorWatch").strip()


def digest_tz() -> ZoneInfo:
    try:
        return ZoneInfo(PAPER_WALLET_TIMEZONE)
    except Exception:
        logger.warning("Invalid PAPER_WALLET_TIMEZONE=%s, using Europe/Moscow", PAPER_WALLET_TIMEZONE)
        return ZoneInfo("Europe/Moscow")


def today_key(when: dt_datetime | None = None) -> str:
    tz = digest_tz()
    moment = (when or dt_datetime.now(tz)).astimezone(tz)
    return moment.date().isoformat()


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = read_json_file(STATE_FILE, default={})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def already_posted_today(when: dt_datetime | None = None) -> bool:
    return load_state().get("last_post_date") == today_key(when)


def mark_posted_today(
    *,
    when: dt_datetime,
    top_symbols: list[str],
    bottom_symbols: list[str],
    mid_symbols: list[str],
) -> None:
    with json_rw_lock(STATE_FILE, default={}) as payload:
        payload["last_post_date"] = today_key(when)
        payload["last_post_at"] = when.isoformat()
        payload["top_symbols"] = top_symbols
        payload["bottom_symbols"] = bottom_symbols
        payload["mid_symbols"] = mid_symbols


def _parse_row(raw: dict[str, Any]) -> MarketRow | None:
    try:
        return MarketRow(
            rank=int(raw.get("market_cap_rank") or 0),
            name=str(raw.get("name") or ""),
            symbol=str(raw.get("symbol") or "").upper(),
            price=float(raw.get("current_price") or 0),
            change_1h=_pct(raw, "price_change_percentage_1h_in_currency"),
            change_24h=_pct(raw, "price_change_percentage_24h"),
            change_7d=_pct(raw, "price_change_percentage_7d_in_currency"),
            market_cap=float(raw.get("market_cap") or 0),
            volume=float(raw.get("total_volume") or 0),
            image_url=str(raw.get("image") or ""),
        )
    except (TypeError, ValueError):
        return None


def _pct(raw: dict[str, Any], key: str) -> float | None:
    val = raw.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "SaylorWatchBot/PaperWallet/1.0"}
    api_key = os.environ.get("COINGECKO_API_KEY", "").strip()
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
    return headers


def _markets_url(*, order: str, per_page: int, page: int) -> str:
    params = {
        "vs_currency": "usd",
        "order": order,
        "per_page": str(per_page),
        "page": str(page),
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d",
    }
    return f"{COINGECKO_MARKETS_URL}?{urllib.parse.urlencode(params)}"


def _fetch_json_sync(url: str) -> Any | None:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                logger.warning("CoinGecko HTTP %s %s", resp.status, url)
                return None
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.warning("CoinGecko fetch failed %s: %s", url, exc)
        return None


async def fetch_markets(
    *,
    order: str = "market_cap_desc",
    per_page: int = 250,
    page: int = 1,
) -> list[MarketRow]:
    url = _markets_url(order=order, per_page=per_page, page=page)
    data = await asyncio.to_thread(_fetch_json_sync, url)
    if not isinstance(data, list):
        return []
    rows: list[MarketRow] = []
    for item in data:
        if isinstance(item, dict):
            row = _parse_row(item)
            if row and row.symbol and row.price > 0:
                rows.append(row)
    return rows


async def collect_daily_sets(
    *,
    top_min: int | None = None,
    top_max: int | None = None,
    bottom_min: int | None = None,
    bottom_max: int | None = None,
    min_volume: float | None = None,
) -> tuple[list[MarketRow], list[MarketRow], list[str]]:
    top_min = top_min if top_min is not None else _env_int("PAPER_WALLET_TOP_MIN", 8)
    top_max = top_max if top_max is not None else _env_int("PAPER_WALLET_TOP_MAX", 10)
    bottom_min = bottom_min if bottom_min is not None else _env_int("PAPER_WALLET_BOTTOM_MIN", 8)
    bottom_max = bottom_max if bottom_max is not None else _env_int("PAPER_WALLET_BOTTOM_MAX", 10)
    if top_min > top_max:
        top_min, top_max = top_max, top_min
    if bottom_min > bottom_max:
        bottom_min, bottom_max = bottom_max, bottom_min

    min_vol = min_volume if min_volume is not None else min_volume_usd()
    top_pool, bottom_pool = await _fetch_pools()

    top_n = random.randint(top_min, top_max)
    bottom_n = random.randint(bottom_min, bottom_max)

    top_pick = top_pool[:top_n]

    tail_candidates = [r for r in bottom_pool if r.volume >= min_vol and r.market_cap > 0]
    if len(tail_candidates) < bottom_n:
        tail_candidates = bottom_pool[-max(bottom_n * 3, 30) :]

    if len(tail_candidates) <= bottom_n:
        bottom_pick = tail_candidates[:]
    else:
        bottom_pick = random.sample(tail_candidates, bottom_n)
    bottom_pick.sort(key=lambda r: r.market_cap)

    mid_pool = [r.symbol for r in top_pool[15:120] if r.symbol]
    mid_count = random.randint(6, 12)
    mid_symbols = random.sample(mid_pool, min(mid_count, len(mid_pool))) if mid_pool else []

    return top_pick, bottom_pick, mid_symbols


async def _fetch_pools() -> tuple[list[MarketRow], list[MarketRow]]:
    top = await fetch_markets(order="market_cap_desc", per_page=250, page=1)
    bottom = await fetch_markets(order="market_cap_asc", per_page=250, page=1)
    return top, bottom


def _build_market_summary(
    *,
    market_cap_usd: float,
    volume_24h_usd: float,
    cap_change_24h: float,
    btc_dominance: float,
    btc_change_24h: float | None,
) -> str:
    """Краткий summary в стиле CoinGecko (API summary недоступен — из global + BTC)."""
    if cap_change_24h > 0.05:
        cap_phrase = f"Crypto market cap rose {cap_change_24h:.1f}% to {_fmt_usd_compact(market_cap_usd)}"
    elif cap_change_24h < -0.05:
        cap_phrase = f"Crypto market cap fell {abs(cap_change_24h):.1f}% to {_fmt_usd_compact(market_cap_usd)}"
    else:
        cap_phrase = f"Crypto market cap near {_fmt_usd_compact(market_cap_usd)}"

    vol_phrase = f"24h volume {_fmt_usd_compact(volume_24h_usd)}"
    dom_phrase = f"BTC dominance {btc_dominance:.1f}%"
    if btc_change_24h is not None:
        if btc_change_24h > 0:
            btc_phrase = f"Bitcoin up {btc_change_24h:.1f}%"
        elif btc_change_24h < 0:
            btc_phrase = f"Bitcoin down {abs(btc_change_24h):.1f}%"
        else:
            btc_phrase = "Bitcoin flat"
        return f"{cap_phrase}. {btc_phrase}. {vol_phrase}. {dom_phrase}."
    return f"{cap_phrase}. {vol_phrase}. {dom_phrase}."


async def fetch_global_snapshot(btc_change_24h: float | None = None) -> GlobalSnapshot | None:
    data = await asyncio.to_thread(_fetch_json_sync, COINGECKO_GLOBAL_URL)
    if not isinstance(data, dict):
        return None
    block = data.get("data")
    if not isinstance(block, dict):
        return None
    try:
        cap = float((block.get("total_market_cap") or {}).get("usd") or 0)
        vol = float((block.get("total_volume") or {}).get("usd") or 0)
        ch = float(block.get("market_cap_change_percentage_24h_usd") or 0)
        dom = float((block.get("market_cap_percentage") or {}).get("btc") or 0)
    except (TypeError, ValueError):
        return None
    if cap <= 0:
        return None
    summary = _build_market_summary(
        market_cap_usd=cap,
        volume_24h_usd=vol,
        cap_change_24h=ch,
        btc_dominance=dom,
        btc_change_24h=btc_change_24h,
    )
    return GlobalSnapshot(
        total_market_cap_usd=cap,
        total_volume_24h_usd=vol,
        market_cap_change_24h=ch,
        btc_dominance=dom,
        summary=summary,
    )


def _fetch_bytes_sync(url: str) -> bytes | None:
    if not url:
        return None
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except Exception as exc:
        logger.debug("icon fetch %s: %s", url, exc)
        return None


async def load_coin_icons(rows: list[MarketRow]) -> dict[str, Any]:
    """symbol → PIL Image (RGBA), круглая обрезка."""
    from PIL import Image, ImageDraw

    icons: dict[str, Any] = {}
    for row in rows:
        if not row.image_url or row.symbol in icons:
            continue
        raw = await asyncio.to_thread(_fetch_bytes_sync, row.image_url)
        if not raw:
            continue
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            img = img.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), fill=255)
            circ = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
            circ.paste(img, (0, 0), mask)
            icons[row.symbol] = circ
        except Exception as exc:
            logger.debug("icon parse %s: %s", row.symbol, exc)
    return icons


def _text_width(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fmt_price(value: float) -> str:
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:,.4f}".rstrip("0").rstrip(".")
    if value >= 0.0001:
        return f"${value:.6f}".rstrip("0").rstrip(".")
    return f"${value:.8f}".rstrip("0").rstrip(".")


def _fmt_usd_compact(value: float) -> str:
    v = abs(value)
    if v >= 1_000_000_000_000:
        out = f"{v / 1_000_000_000_000:.2f}T"
    elif v >= 1_000_000_000:
        out = f"{v / 1_000_000_000:.2f}B"
    elif v >= 1_000_000:
        out = f"{v / 1_000_000:.2f}M"
    elif v >= 1_000:
        out = f"{v / 1_000:.2f}K"
    else:
        out = f"{v:.0f}"
    return f"${out}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _pct_color(value: float | None) -> tuple[int, int, int]:
    if value is None:
        return TEXT_DIM
    if value > 0:
        return GREEN
    if value < 0:
        return RED
    return TEXT_DIM


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_lines(draw, text: str, font, max_width: int, *, max_lines: int = 4) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(words) > len(" ".join(lines).split()):
        lines[-1] = lines[-1][: max(0, len(lines[-1]) - 3)] + "..."
    return lines


def _draw_sparkline(draw, x: int, y: int, w: int, h: int, *, positive: bool) -> None:
    """Мини-график в карточке (декоративный тренд)."""
    import random as rnd

    color = GREEN if positive else RED
    pts: list[tuple[int, int]] = []
    val = h // 2
    step = max(1, w // 12)
    for i in range(13):
        val += rnd.randint(-3, 3) + (1 if positive else -1)
        val = max(2, min(h - 2, val))
        pts.append((x + i * step, y + h - val))
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=2)


def _draw_global_cards(draw, snap: GlobalSnapshot, *, width: int, y: int) -> int:
    """Три карточки: Global Market Cap · 24H Volume · Summary."""
    margin = 28
    gap = 12
    card_h = 108
    card_w = (width - margin * 2 - gap * 2) // 3

    f_label = _font(14)
    f_value = _font(24, bold=True)
    f_change = _font(15, bold=True)
    f_summary_title = _font(14, bold=True)
    f_summary = _font(13)

    for i, kind in enumerate(("cap", "vol", "summary")):
        x0 = margin + i * (card_w + gap)
        draw.rounded_rectangle((x0, y, x0 + card_w, y + card_h), radius=10, fill=CARD_BG)

        if kind == "cap":
            draw.text((x0 + 14, y + 12), "Global Market Cap", font=f_label, fill=TEXT_DIM)
            draw.text((x0 + 14, y + 34), _fmt_usd_compact(snap.total_market_cap_usd), font=f_value, fill=TEXT)
            ch = snap.market_cap_change_24h
            arrow = "▲" if ch > 0 else "▼" if ch < 0 else "•"
            ch_color = GREEN if ch > 0 else RED if ch < 0 else TEXT_DIM
            draw.text(
                (x0 + 14, y + 68),
                f"{arrow} {abs(ch):.1f}%",
                font=f_change,
                fill=ch_color,
            )
            _draw_sparkline(draw, x0 + card_w - 110, y + 58, 96, 36, positive=ch >= 0)
        elif kind == "vol":
            draw.text((x0 + 14, y + 12), "24H Volume", font=f_label, fill=TEXT_DIM)
            draw.text((x0 + 14, y + 34), _fmt_usd_compact(snap.total_volume_24h_usd), font=f_value, fill=TEXT)
            _draw_sparkline(draw, x0 + 14, y + 72, card_w - 28, 28, positive=snap.market_cap_change_24h >= 0)
        else:
            draw.text((x0 + 14, y + 12), "✦ Summary", font=f_summary_title, fill=TEXT)
            lines = _wrap_lines(draw, snap.summary, f_summary, card_w - 28, max_lines=4)
            ly = y + 34
            for line in lines:
                draw.text((x0 + 14, ly), line, font=f_summary, fill=TEXT_DIM)
                ly += 18

    return y + card_h + 16


def render_market_table(
    rows: list[MarketRow],
    *,
    title: str,
    subtitle: str,
    promo_line: str,
    global_snap: GlobalSnapshot | None = None,
    icons: dict[str, Any] | None = None,
) -> io.BytesIO | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("Pillow not installed — Paper Wallet PNG skipped")
        return None

    if not rows:
        return None

    width = 1320
    row_h = 56
    title_h = 52
    cards_h = 124 if global_snap else 0
    table_header_h = 40
    promo_h = 76 if promo_line else 0
    height = title_h + cards_h + table_header_h + len(rows) * row_h + promo_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(28, bold=True)
    f_sub = _font(17)
    f_th = _font(15, bold=True)
    f_rank = _font(16)
    f_coin_name = _font(17)
    f_symbol = _font(22, bold=True)
    f_price = _font(21, bold=True)
    f_pct = _font(17)
    f_mcap = _font(16)
    f_promo = _font(14, bold=True)
    icon_map = icons or {}

    y = 14
    draw.text((28, y), title, font=f_title, fill=TEXT)
    y += 32
    draw.text((28, y), subtitle, font=f_sub, fill=TEXT_DIM)
    y += 28

    if global_snap:
        y = _draw_global_cards(draw, global_snap, width=width, y=y)

    cols = ["#", "Coin", "Price", "1h", "24h", "7d", "Market Cap"]
    col_x = [28, 76, 420, 600, 730, 860, 1000]
    coin_text_x = col_x[1] + ICON_SIZE + 10

    draw.rectangle((0, y, width, y + table_header_h), fill=BG_HEADER)
    for i, label in enumerate(cols):
        draw.text((col_x[i], y + 10), label, font=f_th, fill=TEXT_DIM)
    y += table_header_h

    for idx, row in enumerate(rows):
        bg = BG_ROW_ALT if idx % 2 else BG
        draw.rectangle((0, y, width, y + row_h), fill=bg)
        text_y = y + 15

        draw.text((col_x[0], text_y), str(row.rank or idx + 1), font=f_rank, fill=TEXT_DIM)

        icon = icon_map.get(row.symbol)
        if icon is not None:
            img.paste(icon, (col_x[1], text_y - 2), icon)

        name = row.name[:16]
        draw.text((coin_text_x, text_y + 2), name, font=f_coin_name, fill=TEXT_DIM)
        sym_x = coin_text_x + _text_width(draw, name, f_coin_name) + 8
        draw.text((sym_x, text_y - 2), row.symbol, font=f_symbol, fill=TEXT)

        draw.text((col_x[2], text_y - 1), _fmt_price(row.price), font=f_price, fill=TEXT)

        for col_i, ch in enumerate((row.change_1h, row.change_24h, row.change_7d), start=3):
            draw.text((col_x[col_i], text_y), _fmt_pct(ch), font=f_pct, fill=_pct_color(ch))

        draw.text((col_x[6], text_y + 1), _fmt_usd_compact(row.market_cap), font=f_mcap, fill=TEXT_DIM)
        y += row_h

    if promo_line:
        draw.rectangle((0, height - promo_h, width, height), fill=PROMO_BG)
        draw.line((0, height - promo_h, width, height - promo_h), fill=ACCENT, width=2)
        draw.text((28, height - promo_h + 24), promo_line, font=f_promo, fill=ACCENT)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    out.name = "paper_wallet.png"
    return out


def caption_for_block(*, kind: str, when: dt_datetime) -> str:
    label = when.strftime("%Y-%m-%d %H:%M")
    if kind == "top":
        return f"Top cryptocurrencies by market cap · {label} · CoinGecko"
    return f"Lowest market cap (min volume) · {label} · CoinGecko"


def promo_line() -> str:
    return f"{bot_name()} → {bot_link()} · Strategy & ETF BTC alerts"


def seconds_until_next_run(*, now: dt_datetime | None = None) -> float:
    tz = digest_tz()
    moment = (now or dt_datetime.now(tz)).astimezone(tz)
    try:
        target = moment.replace(
            hour=PAPER_WALLET_POST_HOUR,
            minute=PAPER_WALLET_POST_MINUTE,
            second=0,
            microsecond=0,
        )
    except ValueError:
        logger.error(
            "Invalid PAPER_WALLET_POST_HOUR/MINUTE: %s:%s",
            PAPER_WALLET_POST_HOUR,
            PAPER_WALLET_POST_MINUTE,
        )
        return 3600.0

    if moment >= target:
        if not already_posted_today(moment):
            return 1.0
        target = target + datetime.timedelta(days=1)
    return max(1.0, (target - moment).total_seconds())


async def deliver_paper_wallet_daily(
    bot,
    *,
    force: bool = False,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Три сообщения в канал. True если пост ушёл."""
    if not paper_wallet_enabled():
        return False

    tz = digest_tz()
    now = dt_datetime.now(tz)

    if not force and already_posted_today(now):
        logger.info("Paper Wallet: already posted %s", today_key(now))
        return False

    top_rows, bottom_rows, mid_symbols = await collect_daily_sets()
    if not top_rows or not bottom_rows:
        if log_fn:
            log_fn("⚠️ Paper Wallet: CoinGecko returned no data")
        return False

    btc_change = top_rows[0].change_24h if top_rows and top_rows[0].symbol == "BTC" else None
    if btc_change is None:
        for r in top_rows:
            if r.symbol == "BTC":
                btc_change = r.change_24h
                break
    global_snap = await fetch_global_snapshot(btc_change_24h=btc_change)
    icons_top, icons_bottom = await asyncio.gather(
        load_coin_icons(top_rows),
        load_coin_icons(bottom_rows),
    )

    promo = promo_line() if os.environ.get("PAPER_WALLET_IMAGE_PROMO", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    } else ""
    top_png = render_market_table(
        top_rows,
        title="Cryptocurrency Prices by Market Cap",
        subtitle=f"Top {len(top_rows)} · USD · {now.strftime('%d %b %Y')}",
        promo_line=promo,
        global_snap=global_snap,
        icons=icons_top,
    )
    bottom_png = render_market_table(
        bottom_rows,
        title="Smallest Market Cap (with volume)",
        subtitle=f"Random {len(bottom_rows)} · min volume filter · {now.strftime('%d %b %Y')}",
        promo_line=promo,
        global_snap=global_snap,
        icons=icons_bottom,
    )
    if top_png is None or bottom_png is None:
        if log_fn:
            log_fn("⚠️ Paper Wallet: PNG render failed")
        return False

    sep_top = build_random_separator_block()
    tickers = build_ticker_line(mid_symbols)
    sep_bottom = build_random_separator_block()
    channel = PAPER_WALLET_CHANNEL

    try:
        await bot.send_message(chat_id=channel, text=sep_top)
        top_png.seek(0)
        msg1 = await bot.send_photo(
            chat_id=channel,
            photo=top_png,
            caption=caption_for_block(kind="top", when=now),
        )
        await bot.send_message(chat_id=channel, text=tickers)
        await bot.send_message(chat_id=channel, text=sep_bottom)
        bottom_png.seek(0)
        msg2 = await bot.send_photo(
            chat_id=channel,
            photo=bottom_png,
            caption=caption_for_block(kind="bottom", when=now),
        )
    except Exception as exc:
        logger.exception("Paper Wallet post failed")
        if log_fn:
            log_fn(f"⚠️ Paper Wallet post failed: {type(exc).__name__}: {exc}")
        return False

    mark_posted_today(
        when=now,
        top_symbols=[r.symbol for r in top_rows],
        bottom_symbols=[r.symbol for r in bottom_rows],
        mid_symbols=mid_symbols,
    )
    if log_fn:
        log_fn(
            f"📰 Paper Wallet posted → {channel} "
            f"(top={msg1.message_id}, bottom={msg2.message_id})"
        )
    return True


async def run_scheduled_paper_wallet_post(
    bot,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    if not paper_wallet_enabled():
        return
    await deliver_paper_wallet_daily(bot, log_fn=log_fn)


async def paper_wallet_scheduler(
    bot,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Фоновый цикл: каждый день в PAPER_WALLET_POST_HOUR (Europe/Moscow по умолчанию)."""
    while True:
        if not paper_wallet_enabled():
            await asyncio.sleep(3600)
            continue
        delay = seconds_until_next_run()
        logger.info("Paper Wallet next post in %.0f s", delay)
        await asyncio.sleep(delay)
        for attempt in range(1, 4):
            try:
                posted = await deliver_paper_wallet_daily(bot, log_fn=log_fn)
                if posted or already_posted_today():
                    break
                logger.warning("Paper Wallet attempt %s failed, retry in 5 min", attempt)
                await asyncio.sleep(300)
            except Exception as exc:
                logger.exception("Paper Wallet scheduler error: %s", exc)
                if log_fn:
                    log_fn(f"⚠️ Paper Wallet scheduler: {exc}")
                await asyncio.sleep(300)


__all__ = [
    "PAPER_WALLET_CHANNEL",
    "PAPER_WALLET_POST_HOUR",
    "PAPER_WALLET_POST_MINUTE",
    "PAPER_WALLET_TIMEZONE",
    "already_posted_today",
    "deliver_paper_wallet_daily",
    "paper_wallet_enabled",
    "paper_wallet_scheduler",
    "run_scheduled_paper_wallet_post",
]
