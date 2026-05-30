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
ORANGE = (247, 147, 26)  # bitcoin orange
ORANGE_SOFT = (255, 176, 64)
WHITE = (245, 245, 247)
GREY = (138, 140, 150)
GREY_DIM = (95, 97, 107)
RED = (235, 87, 87)
GREEN = (46, 204, 113)

WIDTH = 1200
HEIGHT = 675

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
    total_btc: str  # "843,738 BTC"
    date: str  # "2026-05-28"
    is_sale: bool = False


def _text_size(draw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _draw_glow(base: "Image.Image", center: tuple[int, int], color: tuple[int, int, int]) -> None:
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    cx, cy = center
    radius = 360
    gdraw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(*color, 70),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(120))
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
    accent = RED if data.is_sale else ORANGE
    accent_soft = RED if data.is_sale else ORANGE_SOFT

    img = Image.new("RGBA", (WIDTH, HEIGHT), (*BG, 255))
    _draw_glow(img, (WIDTH - 180, 150), accent)
    _draw_glow(img, (220, HEIGHT - 80), accent)
    draw = ImageDraw.Draw(img)

    margin = 70

    # Верхняя акцентная полоса
    draw.rectangle((0, 0, WIDTH, 8), fill=accent)

    # Заголовок
    f_title = _load_font(34, bold=True)
    draw.text((margin, 64), data.title.upper(), font=f_title, fill=accent_soft)

    # Bitcoin-монета как watermark (рисуем вручную — глифа ₿ нет в системных шрифтах)
    _draw_coin_watermark(img, (WIDTH - 230, 300), 190, accent)

    # Главный блок: delta BTC
    f_delta = _load_font(118, bold=True)
    draw.text((margin, 190), data.delta_btc, font=f_delta, fill=WHITE)

    # USD под ним
    f_usd = _load_font(64, bold=True)
    draw.text((margin, 330), data.delta_usd, font=f_usd, fill=accent_soft)

    # Нижняя панель
    panel_y = HEIGHT - 150
    draw.rectangle((0, panel_y, WIDTH, HEIGHT), fill=(*BG_PANEL, 255))
    draw.rectangle((0, panel_y, WIDTH, panel_y + 3), fill=accent)

    f_label = _load_font(26, bold=False)
    f_value = _load_font(40, bold=True)

    draw.text((margin, panel_y + 28), "TOTAL HOLDINGS", font=f_label, fill=GREY)
    draw.text((margin, panel_y + 62), data.total_btc, font=f_value, fill=WHITE)

    date_label = "DATE"
    dl_w, _ = _text_size(draw, date_label, f_label)
    dv_w, _ = _text_size(draw, data.date, f_value)
    right_x = WIDTH - margin
    draw.text((right_x - dl_w, panel_y + 28), date_label, font=f_label, fill=GREY)
    draw.text((right_x - dv_w, panel_y + 62), data.date, font=f_value, fill=WHITE)

    # Подпись брендинга
    f_brand = _load_font(22, bold=False)
    draw.text((margin, HEIGHT - 34), "SaylorWatch · BTC Intelligence", font=f_brand, fill=GREY_DIM)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    out.seek(0)
    out.name = "alert.png"
    return out
