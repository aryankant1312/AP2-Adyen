"""ECDSA P-256 signing for Shopping Agent PaymentMandates.

A `MandateSigner` owns a persistent P-256 keypair stored at
`~/.ap2/shopper_key.pem` (PEM, PKCS#8, unencrypted — development only).

Design notes:
- The signing input is the canonical JSON (RFC 8785 subset, see `canonical.py`)
  of the object being signed. Canonicalization ensures that semantically
  identical payloads produce byte-identical signing inputs across runtimes.
- The digest is SHA-256. Signatures are DER-encoded ECDSA, then base64url.
- `sign_mandate` composes the AP2 authorization payload (cart hash +
  payment-contents hash + nonce + signer DID) and signs it. The returned
  string is what goes into PaymentMandate.user_authorization.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .canonical import canonical_json
from .did import public_key_to_did_key


_DEFAULT_KEY_PATH = Path.home() / ".ap2" / "shopper_key.pem"


@dataclass(frozen=True)
class SignedAuthorization:
    """Structured form of a PaymentMandate.user_authorization payload."""

    cart_hash: str  # hex SHA-256 of canonical CartMandate
    payment_contents_hash: str  # hex SHA-256 of canonical PaymentMandateContents
    nonce: str  # random 128-bit hex, prevents replay
    signer_did: str  # did:key of the signing public key
    signature_b64url: str  # base64url(DER(ECDSA_P256_SHA256))

    def to_compact(self) -> str:
        """Encode as a single base64url string suitable for user_authorization.

        The payload is canonical JSON of the four non-signature fields, then
        base64url-concatenated with the signature using a dot separator:

            base64url(canonical_json(payload)) + "." + signature_b64url
        """
        payload = {
            "cart_hash": self.cart_hash,
            "payment_contents_hash": self.payment_contents_hash,
            "nonce": self.nonce,
            "signer_did": self.signer_did,
        }
        header_b64 = _b64url_encode(canonical_json(payload))
        return f"{header_b64}.{self.signature_b64url}"


class MandateSigner:
    """ECDSA P-256 signer for AP2 mandates with persistent keypair."""

    def __init__(
        self,
        private_key: ec.EllipticCurvePrivateKey,
        key_path: Path | None = None,
    ) -> None:
        self._private_key = private_key
        self._key_path = key_path

    # ---------- construction ----------

    @classmethod
    def load_or_create(cls, key_path: Path | None = None) -> "MandateSigner":
        """Load the persisted keypair from disk, generating one on first run.

        The key file is created with mode 0o600 to discourage accidental
        exposure on multi-user systems. Windows does not enforce POSIX modes,
        but this is still a dev-only convenience — production deployments
        should use a KMS or hardware-backed key.
        """
        path = key_path or _DEFAULT_KEY_PATH
        if path.exists():
            return cls(_load_private_key(path), key_path=path)

        private_key = ec.generate_private_key(ec.SECP256R1())
        path.parent.mkdir(parents=True, exist_ok=True)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.write_bytes(pem)
        try:
            os.chmod(path, 0o600)
        except (OSError, NotImplementedError):
            # POSIX chmod unsupported on some Windows configs; ignore.
            pass
        return cls(private_key, key_path=path)

    # ---------- public key / identity ----------

    @property
    def public_key(self) -> ec.EllipticCurvePublicKey:
        return self._private_key.public_key()

    @property
    def did(self) -> str:
        return public_key_to_did_key(self.public_key)

    def public_key_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    # ---------- low-level primitives ----------

    @staticmethod
    def hash_object(obj: Any) -> str:
        """SHA-256 hex digest of the canonical JSON form of `obj`.

        Accepts either a plain dict/list or a Pydantic BaseModel (anything with
        a `model_dump` method that yields JSON-compatible types).
        """
        if hasattr(obj, "model_dump"):
            payload = obj.model_dump(mode="json")
        else:
            payload = obj
        return hashlib.sha256(canonical_json(payload)).hexdigest()

    def sign_bytes(self, data: bytes) -> str:
        """ECDSA-P256-SHA256 sign `data`; return base64url(DER(signature))."""
        signature = self._private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        return _b64url_encode(signature)

    # ---------- high-level: compose+sign a PaymentMandate auth ----------

    def sign_mandate(
        self,
        cart_mandate: Any,
        payment_mandate_contents: Any,
    ) -> SignedAuthorization:
        """Produce the signed authorization to stamp into user_authorization.

        The signing input binds:
          - the full CartMandate (including merchant_authorization)
          - the PaymentMandateContents
          - a fresh 128-bit nonce
          - the signer's DID
        """
        cart_hash = self.hash_object(cart_mandate)
        payment_contents_hash = self.hash_object(payment_mandate_contents)
        nonce = secrets.token_hex(16)
        signer_did = self.did

        signing_payload = {
            "cart_hash": cart_hash,
            "payment_contents_hash": payment_contents_hash,
            "nonce": nonce,
            "signer_did": signer_did,
        }
        signature_b64url = self.sign_bytes(canonical_json(signing_payload))

        return SignedAuthorization(
            cart_hash=cart_hash,
            payment_contents_hash=payment_contents_hash,
            nonce=nonce,
            signer_did=signer_did,
            signature_b64url=signature_b64url,
        )

    # ---------- verification (primarily for tests / receipts) ----------

    @staticmethod
    def verify_authorization(
        authorization: str,
        public_key: ec.EllipticCurvePublicKey,
    ) -> SignedAuthorization:
        """Verify a compact authorization string; raise on failure.

        Returns the parsed SignedAuthorization on success so callers can also
        cross-check the embedded hashes against their own mandate copies.
        """
        try:
            header_b64, signature_b64url = authorization.split(".", 1)
        except ValueError as exc:
            raise InvalidSignature("malformed authorization token") from exc

        import json as _json  # local import keeps module surface small
        header_bytes = _b64url_decode(header_b64)
        try:
            header = _json.loads(header_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidSignature("authorization header is not valid JSON") from exc

        expected_fields = {
            "cart_hash",
            "payment_contents_hash",
            "nonce",
            "signer_did",
        }
        if set(header) != expected_fields:
            raise InvalidSignature("authorization header has unexpected fields")

        signature = _b64url_decode(signature_b64url)
        public_key.verify(
            signature,
            canonical_json(header),
            ec.ECDSA(hashes.SHA256()),
        )
        return SignedAuthorization(
            cart_hash=header["cart_hash"],
            payment_contents_hash=header["payment_contents_hash"],
            nonce=header["nonce"],
            signer_did=header["signer_did"],
            signature_b64url=signature_b64url,
        )


# ---------- internal helpers ----------


def _load_private_key(path: Path) -> ec.EllipticCurvePrivateKey:
    pem = path.read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ValueError(
            f"key at {path} is not an ECDSA P-256 private key "
            f"(got {type(key).__name__})"
        )
    return key


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
