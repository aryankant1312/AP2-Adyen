"""Tests for the canonical_json helper."""

from __future__ import annotations

from roles.shopping_agent.crypto.canonical import canonical_json


def test_key_order_is_lexicographic():
    """Object keys are sorted regardless of input order."""
    a = {"b": 1, "a": 2, "c": 3}
    b = {"c": 3, "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a) == b'{"a":2,"b":1,"c":3}'


def test_no_insignificant_whitespace():
    assert canonical_json({"x": [1, 2]}) == b'{"x":[1,2]}'


def test_nested_objects_are_sorted_recursively():
    payload = {"outer": {"z": 1, "a": 2}}
    assert canonical_json(payload) == b'{"outer":{"a":2,"z":1}}'


def test_non_ascii_preserved():
    assert canonical_json({"name": "café"}) == '{"name":"café"}'.encode("utf-8")


def test_rejects_nan():
    import pytest

    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
