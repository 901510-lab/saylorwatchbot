"""Печать и экспорт еженедельного отчёта: PDF, HTML (🖨), CSV, текстовая таблица."""

from __future__ import annotations

import csv
import html
import io
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from weekly_digest import (
    WeeklyDigestData,
    build_card_data,
    format_weekly_ticker_summary_en,
    weekly_en_summary_enabled,
)

logger = logging.getLogger(__name__)

ExportFormat = Literal["pdf", "html", "csv", "table"]

_CACHE_TTL_SEC = 3600
_digest_cache: dict[int, tuple[float, WeeklyDigestData]] = {}


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    filename: str
    mime: str


def cache_weekly_digest(user_id: int, data: WeeklyDigestData) -> None:
    _digest_cache[user_id] = (time.time(), data)


def get_cached_weekly_digest(user_id: int) -> WeeklyDigestData | None:
    entry = _digest_cache.get(user_id)
    if not entry:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL_SEC:
        _digest_cache.pop(user_id, None)
        return None
    return data


def _period_slug(data: WeeklyDigestData) -> str:
    return f"{data.period_start.isoformat()}_{data.period_end.isoformat()}"


def _ascii_safe(text: str) -> str:
    return (
        text.replace("−", "-")
        .replace("†", "*")
        .replace("→", "->")
        .encode("ascii", "replace")
        .decode("ascii")
    )


def _strip_emoji(text: str) -> str:
    return re.sub(
        r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]+",
        "",
        text,
    ).strip()


def _report_meta(data: WeeklyDigestData, lang: str) -> dict[str, str]:
    card = build_card_data(data)
    title = "SaylorWatch Weekly Report" if lang != "ru" else "SaylorWatch — еженедельная справка"
    return {
        "title": title,
        "period": data.period_label,
        "whale": card.whale_line,
        "market": card.market_line,
        "subtitle": card.subtitle,
        "etf_suffix": card.etf_section_suffix,
    }


def _company_table_rows(data: WeeklyDigestData) -> list[list[str]]:
    card = build_card_data(data)
    header = ["Entity", "Buy BTC", "Buy USD", "Sell BTC", "Sell USD", "Net", "Holdings BTC"]
    rows = [header]
    for row in card.company_rows:
        rows.append(list(row))
    return rows


def _etf_table_rows(data: WeeklyDigestData) -> list[list[str]]:
    card = build_card_data(data)
    header = ["Ticker", "Net BTC", "Net USD", "Best day", "Worst day"]
    rows = [header]
    for row in card.etf_rows:
        rows.append(list(row))
    return rows


def _en_summary_block(data: WeeklyDigestData) -> str:
    if not weekly_en_summary_enabled():
        return ""
    return format_weekly_ticker_summary_en(data)


def _text_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    lines: list[str] = []
    for idx, row in enumerate(rows):
        line = " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(line)
        if idx == 0:
            lines.append("-+-".join("-" * w for w in widths))
    return "\n".join(lines)


def export_weekly_table(data: WeeklyDigestData, lang: str) -> ExportFile:
    meta = _report_meta(data, lang)
    lines = [
        meta["title"],
        "=" * len(meta["title"]),
        f"Period: {meta['period']}",
        f"Whale: {meta['whale']}",
        f"Market: {meta['market']}",
        "",
        "COMPANIES (7D)",
        _text_table(_company_table_rows(data)),
    ]
    etf_rows = _etf_table_rows(data)
    if len(etf_rows) > 1:
        lines.extend(["", f"ETF FLOWS (7D){meta['etf_suffix']}", _text_table(etf_rows)])
    summary = _en_summary_block(data)
    if summary:
        lines.extend(["", _strip_emoji(summary)])
    lines.extend(
        [
            "",
            "* sell avg = spot estimate at alert time",
            "* NET from holdings delta (no alert); idle = no trades this week",
            "Public data only · not investment advice.",
            "SaylorWatch · Premium Digest v2",
        ]
    )
    body = "\n".join(lines)
    slug = _period_slug(data)
    return ExportFile(
        content=body.encode("utf-8"),
        filename=f"saylorwatch_weekly_{slug}.txt",
        mime="text/plain; charset=utf-8",
    )


def export_weekly_csv(data: WeeklyDigestData) -> ExportFile:
    buf = io.StringIO()
    writer = csv.writer(buf)
    meta = _report_meta(data, "en")
    writer.writerow(["section", "field", "value"])
    writer.writerow(["meta", "period", meta["period"]])
    writer.writerow(["meta", "whale", meta["whale"]])
    writer.writerow(["meta", "market", meta["market"]])
    writer.writerow([])
    writer.writerow(["companies"] + _company_table_rows(data)[0])
    for row in _company_table_rows(data)[1:]:
        writer.writerow(["companies"] + row)
    writer.writerow([])
    etf_header = _etf_table_rows(data)[0]
    writer.writerow(["etfs"] + etf_header)
    for row in _etf_table_rows(data)[1:]:
        writer.writerow(["etfs"] + row)
    slug = _period_slug(data)
    return ExportFile(
        content=buf.getvalue().encode("utf-8"),
        filename=f"saylorwatch_weekly_{slug}.csv",
        mime="text/csv; charset=utf-8",
    )


def export_weekly_html(data: WeeklyDigestData, lang: str) -> ExportFile:
    meta = _report_meta(data, lang)
    companies = _company_table_rows(data)
    etfs = _etf_table_rows(data)
    summary = _en_summary_block(data)

    def render_table(rows: list[list[str]], table_id: str) -> str:
        if len(rows) < 2:
            return ""
        head = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0])
        body_rows = []
        for row in rows[1:]:
            cells = "".join(f"<td>{html.escape(c)}</td>" for c in row)
            body_rows.append(f"<tr>{cells}</tr>")
        return (
            f'<table id="{table_id}"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )

    print_hint = (
        "Open this file in a browser and press Ctrl+P (Cmd+P) to print or save as PDF."
        if lang != "ru"
        else "Откройте файл в браузере и нажмите Ctrl+P (Cmd+P) для печати или сохранения в PDF."
    )
    summary_html = ""
    if summary:
        summary_html = (
            f'<section class="summary"><h2>EN summary</h2>'
            f'<pre>{html.escape(_strip_emoji(summary))}</pre></section>'
        )

    doc = f"""<!DOCTYPE html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(meta['title'])} · {html.escape(meta['period'])}</title>
<style>
:root {{
  --ink: #111;
  --muted: #555;
  --line: #ccc;
  --accent: #f7931a;
  --bg: #fff;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: "Segoe UI", system-ui, sans-serif;
  color: var(--ink);
  background: var(--bg);
  margin: 24px;
  line-height: 1.45;
}}
h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
.subtitle {{ color: var(--muted); margin-bottom: 16px; }}
.print-hint {{
  background: #fff8ee;
  border: 1px solid #f0d2a6;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 20px;
}}
.meta p {{ margin: 4px 0; }}
section {{ margin-top: 28px; }}
h2 {{
  font-size: 1.1rem;
  border-bottom: 2px solid var(--accent);
  padding-bottom: 4px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
  margin-top: 8px;
}}
th, td {{
  border: 1px solid var(--line);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}}
th {{ background: #f6f6f6; }}
pre {{
  white-space: pre-wrap;
  background: #fafafa;
  border: 1px solid var(--line);
  padding: 12px;
  border-radius: 6px;
}}
.foot {{
  margin-top: 28px;
  color: var(--muted);
  font-size: 0.85rem;
}}
@media print {{
  body {{ margin: 12mm; }}
  .print-hint {{ display: none; }}
  a {{ color: inherit; text-decoration: none; }}
}}
</style>
</head>
<body>
<header>
  <h1>{html.escape(meta['title'])}</h1>
  <div class="subtitle">{html.escape(meta['subtitle'])} · {html.escape(meta['period'])}</div>
</header>
<p class="print-hint">🖨 {html.escape(print_hint)}</p>
<section class="meta">
  <p><strong>Whale:</strong> {html.escape(meta['whale'])}</p>
  <p><strong>Market:</strong> {html.escape(meta['market'])}</p>
</section>
<section>
  <h2>Companies (7D)</h2>
  {render_table(companies, "companies")}
</section>
"""
    if len(etfs) > 1:
        doc += f"""
<section>
  <h2>ETF flows (7D){html.escape(meta['etf_suffix'])}</h2>
  {render_table(etfs, "etfs")}
</section>
"""
    doc += summary_html
    doc += """
<section class="foot">
  <p>* sell avg = spot estimate at alert time</p>
  <p>† NET from holdings Δ (no alert) · idle = no trades this week</p>
  <p>Public data only · not investment advice.</p>
  <p>SaylorWatch · Premium Digest v2</p>
</section>
</body>
</html>
"""
    slug = _period_slug(data)
    return ExportFile(
        content=doc.encode("utf-8"),
        filename=f"saylorwatch_weekly_{slug}.html",
        mime="text/html; charset=utf-8",
    )


def export_weekly_pdf(data: WeeklyDigestData, lang: str) -> ExportFile:
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as exc:
        raise RuntimeError("fpdf2 is not installed") from exc

    meta = _report_meta(data, lang)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _ascii_safe(meta["title"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _ascii_safe(f"{meta['subtitle']} · {meta['period']}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(pdf.epw, 5, _ascii_safe(f"Whale: {meta['whale']}"))
    pdf.multi_cell(pdf.epw, 5, _ascii_safe(f"Market: {meta['market']}"))
    pdf.ln(3)

    def write_table(title: str, rows: list[list[str]], col_widths: tuple[float, ...]) -> None:
        if len(rows) < 2:
            return
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _ascii_safe(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "B", 8)
        for idx, cell in enumerate(rows[0]):
            pdf.cell(col_widths[idx], 6, _ascii_safe(cell)[:24], border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for row in rows[1:]:
            for idx, cell in enumerate(row):
                pdf.cell(col_widths[idx], 6, _ascii_safe(str(cell))[:24], border=1)
            pdf.ln()
        pdf.ln(3)

    write_table(
        "Companies (7D)",
        _company_table_rows(data),
        (38, 16, 18, 16, 18, 16, 22),
    )
    etf_rows = _etf_table_rows(data)
    if len(etf_rows) > 1:
        write_table(
            f"ETF flows (7D){meta['etf_suffix']}",
            etf_rows,
            (20, 22, 22, 34, 34),
        )

    summary = _en_summary_block(data)
    if summary:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "EN summary", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(pdf.epw, 4, _ascii_safe(_strip_emoji(summary)))

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        pdf.epw,
        4,
        _ascii_safe(
            "* sell avg = spot estimate at alert time\n"
            "Public data only · not investment advice.\n"
            "SaylorWatch · Premium Digest v2"
        ),
    )

    slug = _period_slug(data)
    return ExportFile(
        content=pdf.output(),
        filename=f"saylorwatch_weekly_{slug}.pdf",
        mime="application/pdf",
    )


def build_weekly_export(data: WeeklyDigestData, fmt: ExportFormat, lang: str) -> ExportFile:
    if fmt == "pdf":
        return export_weekly_pdf(data, lang)
    if fmt == "html":
        return export_weekly_html(data, lang)
    if fmt == "csv":
        return export_weekly_csv(data)
    if fmt == "table":
        return export_weekly_table(data, lang)
    raise ValueError(f"Unknown export format: {fmt}")


__all__ = [
    "ExportFile",
    "ExportFormat",
    "build_weekly_export",
    "cache_weekly_digest",
    "get_cached_weekly_digest",
]
