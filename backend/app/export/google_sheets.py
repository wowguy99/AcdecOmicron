"""Google OAuth and Sheets export for Text-Only flashcards."""
from __future__ import annotations

import os
import secrets
import time
from typing import Any

from ..config import ProviderConfig, load_config, save_config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_MISSING_GOOGLE_MSG = (
    "Google export dependencies are not installed. "
    "Restart via run.bat or run.ps1, or run: pip install -r backend/requirements.txt"
)

# Populated on first use so tests can patch app.export.google_sheets.build, etc.
Request: Any = None
Credentials: Any = None
Flow: Any = None
build: Any = None

_PENDING_TTL_SEC = 600
_pending_oauth: dict[str, tuple[Any, float]] = {}


def _load_google() -> None:
    global Request, Credentials, Flow, build
    if build is not None:
        return
    try:
        from google.auth.transport.requests import Request as _Request
        from google.oauth2.credentials import Credentials as _Credentials
        from google_auth_oauthlib.flow import Flow as _Flow
        from googleapiclient.discovery import build as _build
    except ModuleNotFoundError as exc:
        raise ValueError(_MISSING_GOOGLE_MSG) from exc
    Request = _Request
    Credentials = _Credentials
    Flow = _Flow
    build = _build


def oauth_redirect_uri() -> str:
    port = int(os.environ.get("PORT", "8000"))
    return f"http://127.0.0.1:{port}/api/auth/google/callback"


def _client_config(client_id: str) -> dict[str, Any]:
    redirect = oauth_redirect_uri()
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": "",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


def _require_client_id(cfg: ProviderConfig) -> str:
    client_id = (cfg.google_client_id or os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    if not client_id:
        raise ValueError(
            "Google OAuth client ID is not configured. Add google_client_id in Settings "
            "or set GOOGLE_CLIENT_ID."
        )
    return client_id


def _purge_stale_pending() -> None:
    now = time.time()
    stale = [k for k, (_, exp) in _pending_oauth.items() if exp <= now]
    for key in stale:
        _pending_oauth.pop(key, None)


def start_oauth() -> str:
    """Return the Google authorization URL."""
    _load_google()
    cfg = load_config()
    client_id = _require_client_id(cfg)
    _purge_stale_pending()

    flow = Flow.from_client_config(
        _client_config(client_id),
        scopes=SCOPES,
        redirect_uri=oauth_redirect_uri(),
    )
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    _pending_oauth[state] = (flow, time.time() + _PENDING_TTL_SEC)
    return auth_url


def finish_oauth(code: str, state: str | None) -> None:
    _load_google()
    if not state or state not in _pending_oauth:
        raise ValueError("OAuth session expired or invalid. Try connecting again.")
    flow, exp = _pending_oauth.pop(state)
    if exp <= time.time():
        raise ValueError("OAuth session expired. Try connecting again.")

    flow.fetch_token(code=code)
    creds = flow.credentials
    if not creds or not creds.refresh_token:
        raise ValueError("Google did not return a refresh token. Try again.")

    cfg = load_config()
    cfg.google_refresh_token = creds.refresh_token
    if not cfg.google_client_id:
        cfg.google_client_id = _require_client_id(cfg)
    save_config(cfg)


def disconnect_google() -> None:
    cfg = load_config()
    cfg.google_refresh_token = ""
    save_config(cfg)


def get_google_credentials(cfg: ProviderConfig | None = None) -> Any:
    _load_google()
    cfg = cfg or load_config()
    if not cfg.google_refresh_token:
        raise ValueError("Google account not connected.")
    client_id = _require_client_id(cfg)
    creds = Credentials(
        token=None,
        refresh_token=cfg.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret="",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def cards_to_sheet_values(cards: list[dict[str, str]]) -> list[list[str]]:
    return [[c["front"], c["back"], c["tag"]] for c in cards]


def create_spreadsheet(title: str, cards: list[dict[str, str]]) -> str:
    """Create a new spreadsheet and return its URL."""
    _load_google()
    creds = get_google_credentials()
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet_title = title[:-4] if title.lower().endswith(".csv") else title
    body: dict[str, Any] = {"properties": {"title": sheet_title}}
    created = service.spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl").execute()
    sheet_id = created["spreadsheetId"]
    url = created.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{sheet_id}"

    values = cards_to_sheet_values(cards)
    if values:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
    return url
