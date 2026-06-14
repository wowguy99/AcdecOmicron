"""Local app configuration and API-key storage.

The API key never leaves the machine: the UI posts it to the backend, which
persists it to a git-ignored plaintext JSON file under ``data/config.json``.
Only the backend ever calls the AI provider.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .paths import config_path, data_dir, db_path, upload_dir

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = data_dir()
UPLOAD_DIR = upload_dir()
DB_PATH = db_path()
CONFIG_PATH = config_path()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ProviderConfig(BaseModel):
    """Pluggable provider settings. ``api_key`` is stored plaintext locally."""

    provider: str = "gemini"  # gemini | groq | openai_compat
    model: str = "gemini-2.5-flash-lite"
    api_key: str = ""
    base_url: Optional[str] = None  # for openai_compat
    # Conservative free-tier defaults; counted locally (providers don't report RPD reliably).
    rpm: int = 15
    rpd: int = 1000
    temperature: float = 0.1
    license_key: str = ""
    text_export_format: str = "csv"  # csv | google_sheet
    google_client_id: str = ""
    google_refresh_token: str = ""


def load_config() -> ProviderConfig:
    ensure_dirs()
    if CONFIG_PATH.exists():
        try:
            data: dict[str, Any] = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return ProviderConfig(**data)
        except Exception:
            return ProviderConfig()
    return ProviderConfig()


def save_config(cfg: ProviderConfig) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    # Best-effort tighten perms on POSIX; harmless on Windows.
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def public_config(cfg: ProviderConfig) -> dict[str, Any]:
    """Config safe to return to the UI (key masked)."""
    d = cfg.model_dump()
    d["api_key"] = bool(cfg.api_key)  # expose only whether a key is set
    d["google_connected"] = bool(cfg.google_refresh_token)
    d.pop("google_refresh_token", None)
    return d
