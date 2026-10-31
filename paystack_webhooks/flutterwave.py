"""Flutterwave webhooks.

Flutterwave does not sign the payload. It sends your configured secret hash in the
``verif-hash`` header, and the only thing that proves is that the sender knows the
hash. It does **not** cover the body, so a valid header can accompany a tampered
payload if the hash ever leaks.

That is a weaker guarantee than Paystack's, and pretending otherwise would be
dishonest. Practical implications, documented rather than hidden:

* Rotate the hash if it is exposed anywhere (logs, a public repo, a screenshot).
* Deduplicate on ``event_id``; the hash is static, so it cannot prevent replay.
* Compare the transaction amount and currency against your own record before
  fulfilling. The signature cannot tell you the amount is right, only that the
  sender knows the secret.
"""

from __future__ import annotations

from typing import Mapping, Optional

from .errors import MalformedPayload, RawBodyRequired, SignatureError
from .event import Event, build_event, header, load_json
from .idempotency import Store
from .signature import constant_time_equals

VERIF_HASH_HEADER = "verif-hash"
PROVIDER = "flutterwave"


class FlutterwaveWebhook:
    """Verify and decode Flutterwave webhook deliveries."""

    def __init__(self, secret_hash: str, *, store: Optional[Store] = None) -> None:
        if not secret_hash or not str(secret_hash).strip():
            raise ValueError(
                "secret_hash is required: pass the hash you set in the Flutterwave dashboard")
        self._hash = str(secret_hash).strip()
        self._store = store

    def parse(self, body: bytes, headers: Mapping[str, str]) -> Event:
        if isinstance(body, str):
            raise RawBodyRequired(
                "body arrived as str, which cannot be verified: re-encoding changes the "
                "digest. Pass the raw bytes instead (request.body(), request.get_data()).")
        if isinstance(body, (bytearray, memoryview)):
            body = bytes(body)
        if not isinstance(body, bytes):
            raise RawBodyRequired(
                "body must be raw bytes; pass request.body() before parsing JSON")
        provided = header(headers, VERIF_HASH_HEADER)
        # Deliberately no body in this comparison: Flutterwave's hash is static.
        if not constant_time_equals(self._hash, provided):
            raise SignatureError("verif-hash did not match the configured secret hash")
        try:
            payload = load_json(body)
        except ValueError as exc:
            raise MalformedPayload(str(exc)) from exc
        if not str(payload.get("event") or payload.get("event_type") or "").strip():
            raise MalformedPayload("payload has no 'event' field")
        return build_event(PROVIDER, payload, body, headers or {})

    def process(self, body: bytes, headers: Mapping[str, str],
                *, store: Optional[Store] = None) -> Optional[Event]:
        event = self.parse(body, headers)
        target = store if store is not None else self._store
        if target is not None and target.seen(event.event_id):
            return None
        return event


