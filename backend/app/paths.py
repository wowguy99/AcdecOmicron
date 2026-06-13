"""Resolve app, data, and frontend paths for dev vs PyInstaller installs."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def backend_root() -> Path:
    """Backend package root (``backend/`` in dev, bundle root when frozen)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """Repository root (parent of ``backend/``)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return backend_root().parent


def data_dir() -> Path:
    """Writable user data directory (config, db, uploads)."""
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AcDecFlashcards"
        return base
    return backend_root() / "data"


def upload_dir() -> Path:
    return data_dir() / "uploads"


def db_path() -> Path:
    return data_dir() / "acdec.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def frontend_dist_dir() -> Path:
    """Built React app served by FastAPI."""
    if is_frozen():
        return Path(sys._MEIPASS) / "frontend_dist"
    return repo_root() / "frontend" / "dist"
