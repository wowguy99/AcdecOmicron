#!/usr/bin/env python3
"""Owner-only license key generator (never distribute this script or the private key).

Usage:
  python tools/make_key.py --init
  python tools/make_key.py --machine-id A1B2-C3D4-E5F6-7890 [--days 365]

GUI:
  python tools/make_key_gui.py
  or double-click tools/generate-key.bat
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_KEY_PATH = Path(__file__).resolve().parent / "license_private_key.pem"

sys.path.insert(0, str(ROOT / "backend"))

from app.licensing import (  # noqa: E402
    FINGERPRINT_RE,
    build_payload,
    format_fingerprint,
    normalize_fingerprint,
    sign_payload,
    _b64url_encode,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class KeyGenError(Exception):
    pass


@dataclass(frozen=True)
class ProductKeyResult:
    machine_id: str
    expires: str
    days: int
    key: str


def private_key_exists() -> bool:
    return PRIVATE_KEY_PATH.is_file()


def init_keypair() -> str:
    """Create Ed25519 keypair. Returns base64 public key for licensing.py."""
    if PRIVATE_KEY_PATH.exists():
        raise KeyGenError(
            f"Private key already exists at {PRIVATE_KEY_PATH}. "
            "Delete it first if you want to regenerate."
        )

    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.write_bytes(pem)
    try:
        PRIVATE_KEY_PATH.chmod(0o600)
    except OSError:
        pass

    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64url_encode(public_raw)


def generate_product_key(machine_id: str, days: int = 365) -> ProductKeyResult:
    if not PRIVATE_KEY_PATH.exists():
        raise KeyGenError(
            "Private key not found. Use Initialize keypair first (GUI) or run: "
            "python tools/make_key.py --init"
        )
    if days < 1:
        raise KeyGenError("Days must be at least 1.")

    fp = format_fingerprint(normalize_fingerprint(machine_id.strip()))
    if not FINGERPRINT_RE.match(fp):
        raise KeyGenError(
            f"Invalid machine ID (expected XXXX-XXXX-XXXX-XXXX): {machine_id!r}"
        )

    expiry_dt = datetime.now(tz=timezone.utc) + timedelta(days=days)
    expiry_epoch = int(expiry_dt.timestamp())
    payload = build_payload(fp, expiry_epoch)
    pem = PRIVATE_KEY_PATH.read_bytes()
    key = sign_payload(payload, pem)

    return ProductKeyResult(
        machine_id=fp,
        expires=expiry_dt.strftime("%Y-%m-%d"),
        days=days,
        key=key,
    )


def cmd_init() -> int:
    try:
        public_b64 = init_keypair()
    except KeyGenError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Ed25519 keypair created.")
    print(f"Private key saved to: {PRIVATE_KEY_PATH}")
    print("Keep the private key secret — never ship it with the app.")
    print()
    print("Paste this into backend/app/licensing.py as PUBLIC_KEY_B64:")
    print(public_b64)
    return 0


def cmd_make_key(machine_id: str, days: int) -> int:
    try:
        result = generate_product_key(machine_id, days)
    except KeyGenError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Machine ID: {result.machine_id}")
    print(f"Expires:    {result.expires} (UTC)")
    print(f"Days:       {result.days}")
    print()
    print("Product key (send to recipient):")
    print(result.key)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-bound product keys.")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Generate Ed25519 keypair (run once; embed printed public key in licensing.py).",
    )
    parser.add_argument(
        "--machine-id",
        metavar="ID",
        help="Recipient machine ID (XXXX-XXXX-XXXX-XXXX).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="License validity in days (default: 365).",
    )
    args = parser.parse_args()

    if args.init:
        return cmd_init()
    if args.machine_id:
        return cmd_make_key(args.machine_id, args.days)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
