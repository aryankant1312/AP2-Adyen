"""Key generation + loading helpers (idempotent)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa


_LOG = logging.getLogger("ap2.common.signing.keys")


def _write_private_pem(path: Path, key) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    _LOG.info("wrote new private key to %s", path)


def ensure_rsa_key(path: str | Path, *, bits: int = 2048) -> Path:
    """Generate an RSA private key at ``path`` if it doesn't exist."""
    p = Path(path)
    if p.exists():
        return p
    _write_private_pem(
        p, rsa.generate_private_key(public_exponent=65537, key_size=bits)
    )
    return p


def ensure_ec_key(path: str | Path,
                  *, curve: Literal["P-256", "P-384"] = "P-256") -> Path:
    """Generate an EC private key at ``path`` if it doesn't exist."""
    p = Path(path)
    if p.exists():
        return p
    curve_obj = ec.SECP256R1() if curve == "P-256" else ec.SECP384R1()
    _write_private_pem(p, ec.generate_private_key(curve_obj))
    return p


def load_private_key(path: str | Path):
    return serialization.load_pem_private_key(Path(path).read_bytes(),
                                              password=None)


def load_public_key(path: str | Path):
    return serialization.load_pem_public_key(Path(path).read_bytes())


def export_public_pem(private_key_path: str | Path,
                      public_key_path: str | Path) -> Path:
    """Write the matching public PEM next to the private key."""
    priv = load_private_key(private_key_path)
    pub = priv.public_key()
    p = Path(public_key_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    return p
