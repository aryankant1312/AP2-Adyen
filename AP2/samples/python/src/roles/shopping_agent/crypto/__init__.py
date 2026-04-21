"""Real cryptographic primitives for the Shopping Agent.

Provides ECDSA P-256 signing over canonicalized mandate JSON, replacing the
placeholder "fake hash concatenation" found in the reference sample's
sign_mandates_on_user_device.
"""

from .canonical import canonical_json
from .did import public_key_to_did_key
from .signer import MandateSigner

__all__ = ["MandateSigner", "canonical_json", "public_key_to_did_key"]
