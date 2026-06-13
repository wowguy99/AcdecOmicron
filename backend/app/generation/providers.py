"""Pluggable AI provider abstraction.

The backend (never the browser) calls the provider with the user-supplied key.
All providers are asked to return strict JSON; the worker handles repair.
"""
from __future__ import annotations

from typing import Protocol

import httpx

from ..config import ProviderConfig


class ProviderError(RuntimeError):
    """Raised for non-retryable provider errors."""


class RateLimited(RuntimeError):
    """Raised on HTTP 429 so the worker can back off."""

    def __init__(self, retry_after: float = 5.0):
        super().__init__("rate limited")
        self.retry_after = retry_after


class Provider(Protocol):
    def generate(self, system: str, user: str) -> str: ...


class GeminiProvider:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    def generate(self, system: str, user: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.cfg.model}:generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.cfg.temperature,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                url, params={"key": self.cfg.api_key}, json=payload
            )
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ProviderError(f"Gemini empty response: {str(data)[:300]}")


class OpenAICompatProvider:
    """Works for Groq and any OpenAI-compatible chat completions endpoint."""

    def __init__(self, cfg: ProviderConfig, default_base: str):
        self.cfg = cfg
        self.base = (cfg.base_url or default_base).rstrip("/")

    def generate(self, system: str, user: str) -> str:
        url = f"{self.base}/chat/completions"
        payload = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        if resp.status_code >= 400:
            raise ProviderError(f"{self.base} {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise ProviderError(f"Empty response: {str(data)[:300]}")


def _retry_after(resp: httpx.Response) -> float:
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw else 5.0
    except ValueError:
        return 5.0


def get_provider(cfg: ProviderConfig) -> Provider:
    if cfg.provider == "gemini":
        return GeminiProvider(cfg)
    if cfg.provider == "groq":
        return OpenAICompatProvider(cfg, "https://api.groq.com/openai/v1")
    if cfg.provider == "openai_compat":
        if not cfg.base_url:
            raise ProviderError("openai_compat requires base_url")
        return OpenAICompatProvider(cfg, cfg.base_url)
    raise ProviderError(f"Unknown provider: {cfg.provider}")
