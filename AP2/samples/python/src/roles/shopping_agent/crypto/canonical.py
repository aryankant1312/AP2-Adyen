"""JSON canonicalization for deterministic hashing.

Implements RFC 8785 (JSON Canonicalization Scheme, JCS) semantics sufficient
for hashing AP2 mandates: lexicographic object key ordering, no insignificant
whitespace, UTF-8 output, and JSON-standard number serialization. Mandate
payloads only use strings/bools/ints/None/nested dicts+lists, so the subset we
implement here is sufficient.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(payload: Any) -> bytes:
    """Serialize a JSON-compatible value to canonical UTF-8 bytes.

    - Object keys are sorted lexicographically (as UTF-16 code units, which
      matches Python's default string ordering for the ASCII key space used by
      AP2 mandates).
    - Separators are the minimum (",", ":") with no whitespace.
    - Non-ASCII characters are preserved (ensure_ascii=False) per JCS.
    - NaN / Infinity are rejected (allow_nan=False) because they are not valid
      JSON and would poison any downstream verifier.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
