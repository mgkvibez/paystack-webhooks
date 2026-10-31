"""Paystack webhooks.

Paystack signs the **raw request body** with HMAC-SHA512 using your secret key and
sends the hex digest in ``x-paystack-signature``. Two consequences that trip up
most integrations:

* You must verify the bytes that arrived, before any JSON parsing. Re-encoding a
  parsed dict changes whitespace and key order, so the digest no longer matches.
* The signature covers the body only. Paystack sends no signed timestamp, so a
  captured delivery stays valid forever. Freshness cannot be proven cryptographically;
  deduplicate on ``event_id`` and treat that as your replay defence.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .errors import MalformedPayload, RawBodyRequired, SignatureError
from .event import Event, build_event, header, load_json
from .idempotency import Store
from .signature import constant_time_equals, hmac_sha512_hex

SIGNATURE_HEADER = "x-paystack-signature"
PROVIDER = "paystack"


class PaystackWebhook:
    """Verify and decode Paystack webhook deliveries."""

    def __init__(self, secret_key: str, *, store: Optional[Store] = None) -> None:
        if not secret_key or not str(secret_key).strip():
            raise ValueError("secret_key is required: pass your Paystack secret key")
        self._secret = str(secret_key).strip()
        self._store = store

    def expected_signature(self, body: bytes) -> str:
        """The digest Paystack should have sent for these exact bytes."""
        return hmac_sha512_hex(self._secret, body)

    def parse(self, body: bytes, headers: Mapping[str, str]) -> Event:
        """Verify the signature and return the event, or raise."""
        if isinstance(body, str):
            raise RawBodyRequired(
                "body arrived as str, which cannot be verified: re-encoding changes the "
                "digest. Pass the raw bytes instead (request.body(), request.get_data()).")
        if isinstance(body, (bytearray, memoryview)):
            body = bytes(body)
        if not isinstance(body, bytes):
            raise RawBodyRequired(
                "body must be raw bytes; pass request.body() before parsing JSON")
        provided = header(headers, SIGNATURE_HEADER)
        if not constant_time_equals(self.expected_signature(body), provided):
            raise SignatureError(
                "x-paystack-signature did not match the body for the configured secret")
        try:
            payload = load_json(body)
        except ValueError as exc:
            raise MalformedPayload(str(exc)) from exc
        if not str(payload.get("event") or payload.get("event_type") or "").strip():
            raise MalformedPayload("payload has no 'event' field")
        return build_event(PROVIDER, payload, body, headers or {})

    def process(self, body: bytes, headers: Mapping[str, str],
                *, store: Optional[Store] = None) -> Optional[Event]:
        """Verify, then return the event once. A repeat delivery returns ``None``."""
        event = self.parse(body, headers)
        target = store if store is not None else self._store
        if target is not None and target.seen(event.event_id):
            return None
        return event


