"""Stripe webhooks, and the one guarantee the other two providers do not offer.

Stripe signs ``{timestamp}.{raw body}`` with HMAC-SHA256 and sends it as
``Stripe-Signature: t=...,v1=...``. Because the timestamp is inside the signed string, a
captured delivery cannot be replayed later: the receiver can reject anything outside a
tolerance window. Paystack signs the body alone, so a Paystack event stays valid forever,
which is why that adapter deduplicates and this one can also refuse staleness.

During a secret rotation Stripe sends several ``v1`` values; any one matching is enough.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, List, Mapping, Optional, Tuple

from .errors import MalformedPayload, RawBodyRequired, SignatureError
from .event import Event, header
from .idempotency import Store
from .signature import constant_time_equals, hmac_sha256_hex

SIGNATURE_HEADER = "stripe-signature"
PROVIDER = "stripe"
DEFAULT_TOLERANCE = 300


def signed_payload(timestamp: str, body: bytes) -> bytes:
    """Stripe signs the timestamp and the body together, joined by a period."""
    return timestamp.encode("utf-8") + b"." + body


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """The v1 digest for one timestamp and body."""
    return hmac_sha256_hex(secret, signed_payload(timestamp, body))


def parse_signature_header(value: str) -> Tuple[Optional[str], List[str]]:
    """Pull the timestamp and every v1 digest out of the header.

    Unknown scheme pairs are ignored rather than rejected: Stripe has added schemes
    before, and failing on one we do not use would break working integrations.
    """
    timestamp: Optional[str] = None
    digests: List[str] = []
    for part in (value or "").split(","):
        key, _, val = part.partition("=")
        key, val = key.strip(), val.strip()
        if not key or not val:
            continue
        if key == "t":
            timestamp = val
        elif key == "v1":
            digests.append(val)
    return timestamp, digests


class StripeWebhook:
    """Verify and decode Stripe webhook deliveries."""

    def __init__(self, secret_key: str, *, store: Optional[Store] = None,
                 tolerance: int = DEFAULT_TOLERANCE,
                 clock: Callable[[], float] = time.time) -> None:
        if not secret_key or not str(secret_key).strip():
            raise ValueError("secret_key is required: pass the endpoint secret (whsec_...)")
        if tolerance < 0:
            raise ValueError("tolerance cannot be negative")
        self._secret = str(secret_key).strip()
        self._store = store
        self._tolerance = tolerance
        self._clock = clock

    def parse(self, body: bytes, headers: Mapping[str, str]) -> Event:
        if isinstance(body, str):
            raise RawBodyRequired(
                "body arrived as str, which cannot be verified: re-encoding changes the "
                "digest. Pass the raw bytes instead (request.body(), request.get_data()).")
        if not body:
            raise SignatureError("empty body: there is nothing to verify")

        raw_header = header(headers, SIGNATURE_HEADER)
        if not raw_header:
            raise SignatureError("missing Stripe-Signature header")

        timestamp, digests = parse_signature_header(raw_header)
        if timestamp is None or not digests:
            raise SignatureError("Stripe-Signature is missing t= or v1=")

        self._check_fresh(timestamp)

        expected = compute_signature(self._secret, timestamp, body)
        if not any(constant_time_equals(expected, provided) for provided in digests):
            raise SignatureError("signature does not match the body and secret")

        payload = self._load(body)
        name = str(payload.get("type") or "").strip()
        if not name:
            raise MalformedPayload("payload has no type")

        data = payload.get("data")
        obj = data.get("object") if isinstance(data, Mapping) else None
        if not isinstance(obj, Mapping):
            raise MalformedPayload("payload has no data.object")

        return Event(provider=PROVIDER, name=name, data=obj,
                     event_id=self._event_id(name, payload, body),
                     raw=body, headers=dict(headers or {}))

    def _check_fresh(self, timestamp: str) -> None:
        try:
            sent = int(timestamp)
        except (TypeError, ValueError):
            raise SignatureError("Stripe-Signature has a non-numeric t=")
        age = abs(self._clock() - sent)
        if age > self._tolerance:
            raise SignatureError(
                "timestamp is %.0fs outside the %ds tolerance: treat the delivery as a "
                "replay, or raise tolerance if your clock is skewed" % (age, self._tolerance))

    @staticmethod
    def _load(body: bytes) -> Mapping[str, Any]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise MalformedPayload("body is not valid JSON")
        if not isinstance(payload, Mapping):
            raise MalformedPayload("body is not a JSON object")
        return payload

    @staticmethod
    def _event_id(name: str, payload: Mapping[str, Any], body: bytes) -> str:
        record_id = str(payload.get("id") or "").strip()
        if record_id:
            return "%s:%s:%s" % (PROVIDER, name, record_id)
        return "%s:%s:sha256:%s" % (
            PROVIDER, name, hashlib.sha256(body).hexdigest()[:32])
