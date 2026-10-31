"""Shared fixtures. Signatures are computed with hashlib directly, not with the
library under test, so a bug in our HMAC helper cannot make its own test pass."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest


@pytest.fixture
def secret():
    return "sk_test_2f9b8c7d6e5a4b3c2d1e0f"


@pytest.fixture
def flutter_hash():
    return "flw_verif_hash_abc123"


@pytest.fixture
def charge_body():
    return json.dumps({
        "event": "charge.success",
        "data": {"id": 302961, "reference": "T1234", "amount": 100000,
                 "currency": "NGN", "status": "success"},
    }).encode()


def paystack_signature(secret: str, body: bytes) -> str:
    """Independent implementation, per the Paystack docs."""
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def headers(signature: str, name: str = "x-paystack-signature") -> dict:
    return {name: signature}
