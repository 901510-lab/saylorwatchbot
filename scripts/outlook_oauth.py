"""OAuth2 для личного Outlook.com (MSA) — IMAP XOAUTH2.

Использует тот же desktop-flow, что Evolution/Thunderbird (login.live.com).
Токены хранятся локально в scripts/.email_oauth.json (не в git).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# Evolution / evolution-data-server (публичный desktop client для MSA)
DEFAULT_CLIENT_ID = "cc6e0693-0e26-4220-8322-9d363e308fc6"
DEFAULT_REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"
AUTHORIZE_URL = "https://login.live.com/oauth20_authorize.srf"
TOKEN_URL = "https://login.live.com/oauth20_token.srf"
DEFAULT_SCOPES = "wl.offline_access wl.emails wl.imap"


def token_file_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        root = Path(__file__).resolve().parents[1]
        path = root / path
    return path


def load_tokens(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_tokens(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _http_form(url: str, fields: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OAuth token error ({exc.code}): {detail}") from exc


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    login_hint: str = "",
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": scopes,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def parse_code_from_redirect(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("Пустой URL")
    if "://" not in raw:
        raw = f"https://login.live.com/oauth20_desktop.srf?{raw.lstrip('?')}"
    parsed = urllib.parse.urlparse(raw)
    qs = urllib.parse.parse_qs(parsed.query)
    if "code" not in qs:
        raise ValueError("В URL нет параметра code — скопируйте адрес после входа целиком")
    return qs["code"][0]


def exchange_code(
    code: str,
    *,
    client_id: str,
    redirect_uri: str,
) -> dict:
    return _http_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_access_token(
    refresh_token: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: str,
) -> dict:
    return _http_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
        },
    )


def store_token_response(data: dict, *, path: Path, mail_user: str) -> dict:
    now = int(time.time())
    expires_in = int(data.get("expires_in", 3600))
    stored = {
        "mail_user": mail_user,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": now + expires_in,
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", "bearer"),
    }
    if not stored["refresh_token"]:
        prev = load_tokens(path)
        if prev and prev.get("refresh_token"):
            stored["refresh_token"] = prev["refresh_token"]
    save_tokens(path, stored)
    return stored


def interactive_login(
    *,
    mail_user: str,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    token_path: Path,
) -> dict:
    url = build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        login_hint=mail_user,
    )
    print("OAuth2 — вход Microsoft (Outlook.com)\n")
    print("1. Откроется браузер (или откройте ссылку вручную).")
    print("2. Войдите как", mail_user, "и разрешите доступ.")
    print("3. Браузер перейдёт на login.live.com/oauth20_desktop.srf?code=...")
    print("4. Скопируйте **полный адрес** из строки браузера и вставьте сюда.\n")
    print(url, "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    pasted = input("Вставьте redirect URL: ").strip()
    code = parse_code_from_redirect(pasted)
    data = exchange_code(code, client_id=client_id, redirect_uri=redirect_uri)
    if "access_token" not in data:
        raise RuntimeError(f"OAuth: нет access_token в ответе: {data}")
    stored = store_token_response(data, path=token_path, mail_user=mail_user)
    print("✅ OAuth2 сохранён в", token_path)
    return stored


def get_access_token(
    *,
    mail_user: str,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    token_path: Path,
    refresh_skew: int = 300,
) -> str:
    tokens = load_tokens(token_path)
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError(
            "OAuth токен не найден. Запустите:\n"
            "  python3 scripts/email_support_agent.py --oauth-login"
        )
    if tokens.get("mail_user", "").lower() != mail_user.lower():
        raise RuntimeError(
            f"OAuth токен для {tokens.get('mail_user')}, а MAIL_USER={mail_user}. "
            "Повторите --oauth-login."
        )
    now = int(time.time())
    if int(tokens.get("expires_at", 0)) - refresh_skew > now:
        return tokens["access_token"]
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("OAuth access_token истёк, refresh_token отсутствует — --oauth-login")
    data = refresh_access_token(
        refresh,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )
    if "access_token" not in data:
        raise RuntimeError(f"OAuth refresh failed: {data}")
    stored = store_token_response(data, path=token_path, mail_user=mail_user)
    return stored["access_token"]


def xoauth2_string(username: str, access_token: str) -> str:
    return f"user={username}\x01auth=Bearer {access_token}\x01\x01"
