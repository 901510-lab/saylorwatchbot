"""Нормализация текста писем для FAQ/playbook (кириллица, опечатки, homoglyphs)."""

from __future__ import annotations

import re
import unicodedata

# Целые слова/фразы: кириллица и разговорные варианты → латиница для матчинга
_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bетф\b", " etf "),
    (r"\bеtf\b", " etf "),
    (r"\bбиткоин\b", " bitcoin "),
    (r"\bбиткойн\b", " bitcoin "),
    (r"\bбитка\b", " bitcoin "),
    (r"\bбтк\b", " btc "),
    (r"\bбтс\b", " btc "),
    (r"\bпремиум\b", " premium "),
    (r"\bподписк\w*\b", " subscribe "),
    (r"\bтелеграм\b", " telegram "),
    (r"\bтелега\b", " telegram "),
    (r"\bстратеги\w*\b", " strategy "),
    (r"\bсайлор\w*\b", " saylor "),
    (r"\bмикростратег\w*\b", " microstrategy "),
    (r"\bмстра\b", " mstr "),
    (r"\bказн\w*\b", " treasury "),
    (r"\bхолдинг\w*\b", " holdings "),
    (r"\bалерт\w*\b", " alert "),
    (r"\bуведомлен\w*\b", " notification "),
    (r"\bкурс\w*\b", " price "),
    (r"\bцена\b", " price "),
    (r"\bтариф\w*\b", " plans "),
    (r"\bбесплатн\w*\b", " free "),
    (r"\bакци\w*\b", " promo "),
    (r"\bкомпани\w*\b", " company "),
    (r"\bкорпорац\w*\b", " company "),
    (r"\bкит\w*\b", " whale "),
    (r"\bдержател\w*\b", " holder "),
    (r"\bрейтинг\w*\b", " ranking "),
    (r"\bанализ\w*\b", " analysis "),
    (r"\bотслежива\w*\b", " track "),
    (r"\bмонитор\w*\b", " monitor "),
    (r"\bбот\w*\b", " bot "),
    (r"\bстарт\b", " start "),
    (r"\bкупить\b", " buy "),
    (r"\bприобрест\w*\b", " buy "),
    (r"\bпомощ\w*\b", " help "),
    (r"\bтрикер\w*\b", " ticker "),
    (r"\bтикер\w*\b", " ticker "),
    (r"\bнедельн\w*\b", " weekly "),
    (r"\bеженедельн\w*\b", " weekly "),
    (r"\bотчет\w*\b", " report "),
    (r"\bотчёт\w*\b", " report "),
    (r"\bдайджест\w*\b", " digest "),
    (r"\bсводк\w*\b", " digest "),
    (r"\bспасибо\b", " "),
    (r"\bздравствуй\w*\b", " "),
    (r"\bдобрый день\b", " "),
)

# Homoglyphs внутри «латинских» токенов (IBIT написан кириллицей и т.п.)
_HOMOGLYPH_MAP = str.maketrans({
    "а": "a", "А": "a",
    "в": "b", "В": "b",
    "с": "c", "С": "c",
    "е": "e", "Е": "e",
    "ё": "e",
    "н": "h", "Н": "h",
    "і": "i", "І": "i",
    "к": "k", "К": "k",
    "м": "m", "М": "m",
    "о": "o", "О": "o",
    "р": "p", "Р": "p",
    "т": "t", "Т": "t",
    "у": "y", "У": "y",
    "х": "x", "Х": "x",
})

_TICKER_TOKENS = frozenset({"ibit", "fbtc", "gbtc", "arkb", "mstr", "tsla", "mara", "riot"})

_QUESTION_MARKERS = (
    "скажи", "сколько", "какие", "какой", "какая", "как", "что", "где", "можно ли",
    "подскажи", "расскажи", "объясни", "интересует", "вопрос",
    "how", "what", "which", "where", "can i", "do you", "is there", "tell me",
    "please", "help me",
)


def _fold_ticker_homoglyphs(token: str) -> str:
    """IBIT написанный кириллицей → ibit."""
    if not token or token.isascii():
        return token
    if len(token) < 3 or len(token) > 8:
        return token
    folded = token.translate(_HOMOGLYPH_MAP).lower()
    if folded in _TICKER_TOKENS:
        return folded
    return token


def normalize_faq_blob(text: str) -> str:
    """Единый blob для detect_faq_topic / hints / relaxed match."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    s = s.replace("ё", "е")
    for pattern, repl in _PHRASE_REPLACEMENTS:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    tokens = []
    for raw_tok in re.split(r"(\s+|[^\w/]+)", s):
        if raw_tok and re.search(r"[а-я]", raw_tok):
            tokens.append(_fold_ticker_homoglyphs(raw_tok))
        else:
            tokens.append(raw_tok)
    s = "".join(tokens)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def looks_like_question(blob: str) -> bool:
    low = blob.lower()
    if "?" in low:
        return True
    return any(m in low for m in _QUESTION_MARKERS)


def build_faq_blob(*, subject: str, body: str) -> str:
    """subject + body, нормализовано."""
    parts = [p for p in (subject.strip(), body.strip()) if p]
    return normalize_faq_blob("\n".join(parts))
