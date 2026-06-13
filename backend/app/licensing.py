"""Machine-bound product key verification (Ed25519-signed).

Key format (displayed with optional dashes for readability):
  base64url(payload).base64url(signature)
  payload = "v1.<fingerprint>.<expiry_epoch>"
"""
from __future__ import annotations

import base64
import hashlib
import platform
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Populated by `python tools/make_key.py --init` (public key only; safe to ship).
PUBLIC_KEY_B64 = "GgYnr1mkQ1FGCtFqUjdaKprI4sLG3ByNPAJQk0SY04c"

LicenseStatusCode = Literal[
    "valid", "expired", "wrong_machine", "bad_signature", "malformed", "missing"
]

FINGERPRINT_RE = re.compile(r"^[0-9A-F]{4}(?:-[0-9A-F]{4}){3}$")


@dataclass(frozen=True)
class LicenseResult:
    status: LicenseStatusCode
    expires_at: int | None = None  # unix epoch seconds (UTC)
    fingerprint: str | None = None

    @property
    def expires_iso(self) -> str | None:
        if self.expires_at is None:
            return None
        return datetime.fromtimestamp(self.expires_at, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def normalize_key(key: str) -> str:
    """Strip display grouping spaces only (base64url may contain '-')."""
    return key.replace(" ", "").strip()


def format_key(raw: str) -> str:
    """Insert spaces every 4 chars for readability."""
    raw = normalize_key(raw)
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def normalize_fingerprint(fingerprint: str) -> str:
    return fingerprint.replace("-", "").upper()


def format_fingerprint(raw: str) -> str:
    raw = normalize_fingerprint(raw)
    if len(raw) != 16:
        return raw
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def get_machine_guid() -> str:
    """Return a stable machine identifier (Windows MachineGuid when available)."""
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                if value:
                    return str(value).strip()
        except OSError:
            pass
    # Fallback for non-Windows or registry failure.
    node = uuid.getnode()
    return f"{platform.node()}:{platform.system()}:{node}"


def machine_fingerprint() -> str:
    """Short formatted ID shown to the user and embedded in license keys."""
    digest = hashlib.sha256(get_machine_guid().encode("utf-8")).hexdigest()
    return format_fingerprint(digest[:16].upper())


def build_payload(fingerprint: str, expiry_epoch: int) -> str:
    fp = normalize_fingerprint(fingerprint)
    return f"v1.{fp}.{expiry_epoch}"


def sign_payload(payload: str, private_key_pem: bytes) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Expected Ed25519 private key.")
    payload_b = payload.encode("utf-8")
    signature = private_key.sign(payload_b)
    raw = f"{_b64url_encode(payload_b)}.{_b64url_encode(signature)}"
    return format_key(raw)


def _load_public_key() -> Ed25519PublicKey | None:
    if not PUBLIC_KEY_B64:
        return None
    try:
        raw = _b64url_decode(PUBLIC_KEY_B64)
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        return None


def verify_key(key: str) -> LicenseResult:
    if not key or not key.strip():
        return LicenseResult(status="missing")

    public_key = _load_public_key()
    if public_key is None:
        return LicenseResult(status="malformed")

    normalized = normalize_key(key)
    parts = normalized.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return LicenseResult(status="malformed")

    try:
        payload_b = _b64url_decode(parts[0])
        signature = _b64url_decode(parts[1])
        payload = payload_b.decode("utf-8")
    except Exception:
        return LicenseResult(status="malformed")

    try:
        public_key.verify(signature, payload_b)
    except InvalidSignature:
        return LicenseResult(status="bad_signature")
    except Exception:
        return LicenseResult(status="bad_signature")

    payload_parts = payload.split(".")
    if len(payload_parts) != 3 or payload_parts[0] != "v1":
        return LicenseResult(status="malformed")

    fp_raw = payload_parts[1]
    if len(fp_raw) != 16 or not re.fullmatch(r"[0-9A-F]{16}", fp_raw):
        return LicenseResult(status="malformed")

    try:
        expiry = int(payload_parts[2])
    except ValueError:
        return LicenseResult(status="malformed")

    fingerprint = format_fingerprint(fp_raw)
    current = machine_fingerprint()
    if normalize_fingerprint(fingerprint) != normalize_fingerprint(current):
        return LicenseResult(
            status="wrong_machine", expires_at=expiry, fingerprint=fingerprint
        )

    now = int(datetime.now(tz=timezone.utc).timestamp())
    if expiry < now:
        return LicenseResult(
            status="expired", expires_at=expiry, fingerprint=fingerprint
        )

    return LicenseResult(status="valid", expires_at=expiry, fingerprint=fingerprint)
