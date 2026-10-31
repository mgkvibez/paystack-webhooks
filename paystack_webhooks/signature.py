"""HMAC helpers. Constant-time comparisons, no shortcuts."""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha512_hex(secret: str, body: bytes) -> str:
    """Paystack signs the raw body with HMAC-SHA512 and sends the hex digest."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha512).hexdigest()


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    """Provided for providers that use SHA-256; not used by Paystack."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def constant_time_equals(expected: str, provided: str) -> bool:
    """Compare two strings without leaking length or content through timing.

    Both operands are normalised to bytes first: ``compare_digest`` rejects ``str``
    arguments outside the ASCII range, which would otherwise raise on a crafted
    header instead of returning False.
    """
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.strip().encode("utf-8"))
