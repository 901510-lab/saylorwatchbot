"""Генерация image-карточек "premium crypto terminal" стиля (чёрный + orange).

Карточка отправляется вместе с alert о покупке/продаже BTC — это даёт
вирусность (Bloomberg / Arkham / Glassnode look).

Модуль безопасно деградирует: если Pillow недоступен или генерация упала,
вызывающий код просто отправит текстовый alert без картинки.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - зависит от окружения
    PIL_AVAILABLE = False

# === Палитра ===
BG = (8, 8, 11)
BG_PANEL = (15, 15, 20)
# === Палитра Strategy (hero) — orange / red ===
ORANGE = (247, 147, 26)
ORANGE_SOFT = (255, 176, 64)
RED = (235, 87, 87)

# === Палитра компаний и ETF (compact) — green buy / purple sell ===
ALT_GREEN = (46, 204, 113)
ALT_GREEN_SOFT = (96, 230, 156)
ALT_PURPLE = (155, 89, 182)
ALT_PURPLE_SOFT = (190, 130, 220)

WHITE = (245, 245, 247)
GREY = (138, 140, 150)
GREY_DIM = (95, 97, 107)

WIDTH = 1200
HEIGHT = 675
# Strategy — hero (широкая). Компании и ETF — compact: ниже и уже (отличимо в ленте).
STRATEGY_SCALE = 4 / 3        # 1600 × 900
COMPACT_WIDTH_SCALE = 11 / 20  # 660 px — уже базовой compact-ширины (800)
COMPACT_HEIGHT_SCALE = 2 / 3   # 450 px — высота без изменений

# Шрифты пробуем по списку, иначе встроенный масштабируемый default.
_FONT_CANDIDATES_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "DejaVuSans-Bold.ttf",
)
_FONT_CANDIDATES_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "DejaVuSans.ttf",
)


def _load_font(size: int, *, bold: bool):
    candidates = _FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # старые версии Pillow без size
        return ImageFont.load_default()


@dataclass
class CardData:
    title: str  # "STRATEGY · BITCOIN BUY"
    delta_btc: str  # "+24,869 BTC"
    delta_usd: str  # "≈ $2.4B"
    total_btc: str  # "843,738 BTC" или значение потока для ETF
    date: str  # "2026-05-28"
    is_sale: bool = False
    compact: bool = False  # True — compact (Tesla, ETF…); False — hero Strategy
    kind_label: str = ""  # "PUBLIC COMPANY" / "SPOT ETF · IBIT"
    panel_label: str = "TOTAL HOLDINGS"  # для ETF: "DAILY NET FLOW"
    strategy_style: bool = True  # False — green/purple для компаний и ETF


def _accent_colors(*, strategy_style: bool, is_sale: bool) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if strategy_style:
        if is_sale:
            return RED, RED
        return ORANGE, ORANGE_SOFT
    if is_sale:
        return ALT_PURPLE, ALT_PURPLE_SOFT
    return ALT_GREEN, ALT_GREEN_SOFT


def _text_size(draw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _draw_glow(
    base: "Image.Image",
    center: tuple[int, int],
    color: tuple[int, int, int],
    *,
    scale: float = 1.0,
) -> None:
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx, cy = center
    radius = int(360 * scale)
    gdraw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(*color, 70),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(max(8, int(120 * scale))))
    base.alpha_composite(glow)


def generate_card(data: CardData) -> io.BytesIO | None:
    """Возвращает PNG-карточку в BytesIO или None, если генерация недоступна."""
    if not PIL_AVAILABLE:
        return None

    try:
        return _render(data)
    except Exception:  # pragma: no cover - не валим alert из-за картинки
        logger.exception("Card generation failed")
        return None


def _draw_coin_watermark(
    base: "Image.Image", center: tuple[int, int], radius: int, color: tuple[int, int, int]
) -> None:
    """Полупрозрачная BTC-монета: кольцо + 'B' + два вертикальных штриха."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    alpha = 55

    d.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(*color, alpha),
        width=max(10, radius // 14),
    )

    font = _load_font(int(radius * 1.5), bold=True)
    bbox = d.textbbox((0, 0), "B", font=font)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = cx - bw / 2 - bbox[0]
    by = cy - bh / 2 - bbox[1]
    d.text((bx, by), "B", font=font, fill=(*color, alpha))

    bar_w = max(6, radius // 16)
    bar_top = cy - bh * 0.62
    bar_bottom = cy + bh * 0.62
    for dx in (-bw * 0.16, bw * 0.16):
        x = cx + dx
        d.line((x, bar_top, x, bar_bottom), fill=(*color, alpha), width=bar_w)

    base.alpha_composite(layer)


def _render(data: CardData) -> io.BytesIO:
    if data.compact:
        width = int(WIDTH * COMPACT_WIDTH_SCALE)
        height = int(HEIGHT * COMPACT_HEIGHT_SCALE)
        ui_scale = COMPACT_HEIGHT_SCALE
    else:
        width = int(WIDTH * STRATEGY_SCALE)
        height = int(HEIGHT * STRATEGY_SCALE)
        ui_scale = STRATEGY_SCALE
    margin = int(70 * ui_scale)

    accent, accent_soft = _accent_colors(strategy_style=data.strategy_style, is_sale=data.is_sale)

    img = Image.new("RGBA", (width, height), (*BG, 255))
    _draw_glow(img, (width - int(180 * ui_scale), int(150 * ui_scale)), accent, scale=ui_scale)
    _draw_glow(img, (int(220 * ui_scale), height - int(80 * ui_scale)), accent, scale=ui_scale)
    draw = ImageDraw.Draw(img)

    # Верхняя акцентная полоса
    draw.rectangle((0, 0, width, max(4, int(8 * ui_scale))), fill=accent)

    # Заголовок + тип сущности (compact — чуть меньше шрифт под узкую ширину)
    title_size = 30 if data.compact else 34
    f_title = _load_font(int(title_size * ui_scale), bold=True)
    draw.text((margin, int(64 * ui_scale)), data.title.upper(), font=f_title, fill=accent_soft)

    delta_y = int(190 * ui_scale)
    if data.kind_label:
        f_kind = _load_font(int(22 * ui_scale), bold=False)
        draw.text((margin, int(108 * ui_scale)), data.kind_label.upper(), font=f_kind, fill=GREY)
        delta_y = int(210 * ui_scale)

    # Bitcoin-монета как watermark
    coin_r = int(160 * ui_scale) if data.compact else int(190 * ui_scale)
    _draw_coin_watermark(
        img,
        (width - int(200 * ui_scale), int(280 * ui_scale)),
        coin_r,
        accent,
    )

    # Главный блок: delta BTC
    delta_size = 100 if data.compact else 118
    f_delta = _load_font(int(delta_size * ui_scale), bold=True)
    draw.text((margin, delta_y), data.delta_btc, font=f_delta, fill=WHITE)

    # USD под ним
    f_usd = _load_font(int(64 * ui_scale), bold=True)
    draw.text((margin, delta_y + int(140 * ui_scale)), data.delta_usd, font=f_usd, fill=accent_soft)

    # Нижняя панель
    panel_h = int(150 * ui_scale)
    panel_y = height - panel_h
    draw.rectangle((0, panel_y, width, height), fill=(*BG_PANEL, 255))
    draw.rectangle((0, panel_y, width, panel_y + max(2, int(3 * ui_scale))), fill=accent)

    f_label = _load_font(int(26 * ui_scale), bold=False)
    f_value = _load_font(int(40 * ui_scale), bold=True)

    draw.text((margin, panel_y + int(28 * ui_scale)), data.panel_label.upper(), font=f_label, fill=GREY)
    draw.text((margin, panel_y + int(62 * ui_scale)), data.total_btc, font=f_value, fill=WHITE)

    date_label = "DATE"
    dl_w, _ = _text_size(draw, date_label, f_label)
    dv_w, _ = _text_size(draw, data.date, f_value)
    right_x = width - margin
    draw.text((right_x - dl_w, panel_y + int(28 * ui_scale)), date_label, font=f_label, fill=GREY)
    draw.text((right_x - dv_w, panel_y + int(62 * ui_scale)), data.date, font=f_value, fill=WHITE)

    # Подпись брендинга
    f_brand = _load_font(int(22 * ui_scale), bold=False)
    draw.text((margin, height - int(34 * ui_scale)), "SaylorWatch · BTC Intelligence", font=f_brand, fill=GREY_DIM)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    out.seek(0)
    out.name = "alert.png"
    return out


@dataclass
class WeeklyDigestCardData:
    period_label: str
    whale_line: str
    company_rows: list[tuple[str, str, str, str, str, str, str]]  # name buy buy$ sell sell$ net hold
    etf_rows: list[tuple[str, str, str, str, str]]
    market_line: str
    subtitle: str = "PREMIUM WEEKLY · V2 TRADES"
    etf_section_suffix: str = ""


def generate_weekly_digest_card(data: WeeklyDigestCardData) -> io.BytesIO | None:
    """PNG weekly digest — таблица компаний + ETF + рынок."""
    if not PIL_AVAILABLE:
        return None
    try:
        return _render_weekly_digest(data)
    except Exception:
        logger.exception("Weekly digest card generation failed")
        return None


def _render_weekly_digest(data: WeeklyDigestCardData) -> io.BytesIO:
    width = WIDTH
    row_h = 32
    header_block = 200
    company_header = 40
    company_body = max(1, len(data.company_rows)) * row_h
    etf_header = 44 if data.etf_rows else 0
    etf_body = max(0, len(data.etf_rows)) * row_h
    footer = 158
    height = header_block + company_header + company_body + etf_header + etf_body + footer

    accent = ORANGE
    accent_soft = ORANGE_SOFT

    img = Image.new("RGBA", (width, height), (*BG, 255))
    _draw_glow(img, (width - 180, 120), accent, scale=1.0)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, 8), fill=accent)

    margin = 36
    f_title = _load_font(36, bold=True)
    f_sub = _load_font(20, bold=False)
    f_section = _load_font(22, bold=True)
    f_hdr = _load_font(16, bold=True)
    f_row = _load_font(17, bold=False)
    f_whale = _load_font(20, bold=True)
    f_market = _load_font(22, bold=True)
    f_foot = _load_font(18, bold=False)

    y = 36
    draw.text((margin, y), "WEEKLY DIGEST", font=f_title, fill=accent_soft)
    y += 44
    draw.text((margin, y), data.subtitle.upper(), font=f_sub, fill=GREY)
    y += 30
    draw.text((margin, y), data.period_label, font=f_section, fill=WHITE)
    y += 34
    draw.text((margin, y), f"Whale: {data.whale_line}", font=f_whale, fill=accent_soft)
    y += 48

    cols = ["ENTITY", "BUY", "BUY$", "SELL", "SELL$", "NET", "HOLD"]
    col_x = [margin, 250, 370, 490, 610, 760, 900]
    for i, label in enumerate(cols):
        draw.text((col_x[i], y), label, font=f_hdr, fill=GREY)
    y += company_header

    for row in data.company_rows:
        for i, cell in enumerate(row):
            color = WHITE if i == 0 else GREY
            if i in {1, 5} and cell.startswith("+"):
                color = ALT_GREEN
            elif i in {3, 5} and (cell.startswith("−") or cell.startswith("-")):
                color = ALT_PURPLE
            elif i == 5 and cell == "idle":
                color = GREY_DIM
            elif i == 5 and "†" in cell:
                color = ALT_GREEN if cell.startswith("+") else ALT_PURPLE if cell.startswith("−") or cell.startswith("-") else GREY
            draw.text((col_x[i], y), cell[:18], font=f_row, fill=color)
        y += row_h

    if data.etf_rows:
        y += 14
        draw.text((margin, y), f"ETF FLOWS (7D){data.etf_section_suffix}", font=f_section, fill=WHITE)
        y += 34
        etf_cols = ["TICKER", "NET BTC", "NET USD", "BEST DAY", "WORST DAY"]
        etf_x = [margin, 250, 430, 650, 900]
        for i, label in enumerate(etf_cols):
            draw.text((etf_x[i], y), label, font=f_hdr, fill=GREY)
        y += 34
        for row in data.etf_rows:
            for i, cell in enumerate(row):
                draw.text((etf_x[i], y), cell[:22], font=f_row, fill=WHITE if i == 0 else GREY)
            y += row_h

    draw.rectangle((0, height - footer, width, height), fill=(*BG_PANEL, 255))
    draw.rectangle((0, height - footer, width, height - footer + 3), fill=accent)
    draw.text((margin, height - footer + 22), data.market_line, font=f_market, fill=WHITE)
    draw.text(
        (margin, height - footer + 58),
        "* sell avg = spot estimate at alert time",
        font=f_foot,
        fill=GREY_DIM,
    )
    draw.text(
        (margin, height - footer + 82),
        "† NET from holdings Δ (no alert) · idle = no trades this week",
        font=f_foot,
        fill=GREY_DIM,
    )
    draw.text(
        (margin, height - 30),
        "SaylorWatch · Premium Digest v2",
        font=f_sub,
        fill=GREY_DIM,
    )

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    out.seek(0)
    out.name = "weekly_digest.png"
    return out
