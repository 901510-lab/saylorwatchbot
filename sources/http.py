"""Общий асинхронный HTTP-хелпер для источников данных.

Вынесен отдельно, чтобы источники (`sources/`) не зависели от main.py.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "SaylorWatchBot/1.0"


async def fetch_json(
    url: str,
    timeout_seconds: int = 20,
    headers: dict[str, str] | None = None,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> Any | None:
    """HTTP JSON-запрос. Возвращает None при ошибке/не-200."""
    req_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        async with aiohttp.ClientSession(headers=req_headers) as session:
            kwargs: dict[str, Any] = {
                "timeout": aiohttp.ClientTimeout(total=timeout_seconds),
            }
            if json_body is not None:
                kwargs["json"] = json_body
            async with session.request(method.upper(), url, **kwargs) as resp:
                if resp.status != 200:
                    logger.warning("HTTP %s from %s", resp.status, url)
                    return None
                return await resp.json()
    except Exception as exc:  # noqa: BLE001 — источник не должен ронять монитор
        logger.warning("HTTP error for %s: %s: %s", url, type(exc).__name__, exc)
        return None


async def fetch_json_post(
    url: str,
    body: dict[str, Any],
    timeout_seconds: int = 20,
    headers: dict[str, str] | None = None,
) -> Any | None:
    """POST с JSON-телом и разбором ответа."""
    return await fetch_json(
        url,
        timeout_seconds=timeout_seconds,
        headers=headers,
        method="POST",
        json_body=body,
    )


async def fetch_text(
    url: str,
    timeout_seconds: int = 20,
    headers: dict[str, str] | None = None,
) -> str | None:
    """GET-запрос с возвратом текста (для HTML-парсеров вроде strategy.com)."""
    req_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        async with aiohttp.ClientSession(headers=req_headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
            ) as resp:
                if resp.status != 200:
                    logger.warning("HTTP %s from %s", resp.status, url)
                    return None
                return await resp.text()
    except Exception as exc:  # noqa: BLE001
        logger.warning("HTTP error for %s: %s: %s", url, type(exc).__name__, exc)
        return None


__all__ = ["fetch_json", "fetch_json_post", "fetch_text", "DEFAULT_USER_AGENT"]
