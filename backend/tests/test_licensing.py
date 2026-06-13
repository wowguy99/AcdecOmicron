"""Tests for product key verification."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import licensing


@pytest.fixture()
def keypair(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = licensing._b64url_encode(public_raw)
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", public_b64)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fp = licensing.machine_fingerprint()
    return pem, fp


def test_valid_key(keypair):
    pem, fp = keypair
    expiry = int((datetime.now(tz=timezone.utc) + timedelta(days=30)).timestamp())
    payload = licensing.build_payload(fp, expiry)
    key = licensing.sign_payload(payload, pem)
    result = licensing.verify_key(key)
    assert result.status == "valid"
    assert result.expires_at == expiry


def test_expired_key(keypair):
    pem, fp = keypair
    expiry = int((datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp())
    payload = licensing.build_payload(fp, expiry)
    key = licensing.sign_payload(payload, pem)
    result = licensing.verify_key(key)
    assert result.status == "expired"


def test_wrong_machine(keypair):
    pem, _fp = keypair
    expiry = int((datetime.now(tz=timezone.utc) + timedelta(days=30)).timestamp())
    payload = licensing.build_payload("AAAA-BBBB-CCCC-DDDD", expiry)
    key = licensing.sign_payload(payload, pem)
    result = licensing.verify_key(key)
    assert result.status == "wrong_machine"


def test_bad_signature(keypair):
    pem, fp = keypair
    expiry = int((datetime.now(tz=timezone.utc) + timedelta(days=30)).timestamp())
    payload = licensing.build_payload(fp, expiry)
    key = licensing.sign_payload(payload, pem)
    normalized = licensing.normalize_key(key)
    payload_part, sig_part = normalized.split(".", 1)
    sig_bytes = bytearray(licensing._b64url_decode(sig_part))
    sig_bytes[0] ^= 0x01
    tampered = f"{payload_part}.{licensing._b64url_encode(bytes(sig_bytes))}"
    result = licensing.verify_key(tampered)
    assert result.status == "bad_signature"
