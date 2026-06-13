"""Tests for settings persistence."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.config import ProviderConfig, load_config, save_config
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    return TestClient(app)


def test_post_config_preserves_license_key(client):
    save_config(
        ProviderConfig(
            provider="gemini",
            model="gemini-2.5-flash-lite",
            api_key="sk-existing",
            license_key="stored-license-key",
        )
    )

    response = client.post(
        "/api/config",
        json={
            "provider": "groq",
            "model": "llama-3.1-8b-instant",
            "rpm": 30,
            "rpd": 14400,
            "temperature": 0.1,
        },
    )
    assert response.status_code == 200

    cfg = load_config()
    assert cfg.provider == "groq"
    assert cfg.api_key == "sk-existing"
    assert cfg.license_key == "stored-license-key"
