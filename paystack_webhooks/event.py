"""One incoming event, verified, with a stable id for deduplication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:32]


@dataclass(frozen=True)
class Event:
    """A verified webhook delivery.

    ``event_id`` is what you store to make retries harmless. Both providers retry
    on any non-2xx response, and neither sends a signed timestamp, so a delivery
    cannot be proven fresh by cryptography. Deduplicating on this id is the only
    honest replay defence available, which is why it is computed here rather than
    left to the caller.
    """

    provider: str
    name: str
    data: Mapping[str, Any]
    event_id: str
    raw: bytes = field(repr=False, default=b"")
    headers: Mapping[str, str] = field(repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("an event needs a name")

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "name": self.name,
            "event_id": self.event_id,
            "data": dict(self.data),
        }


def build_event(provider: str, payload: Mapping[str, Any], raw: bytes,
                headers: Mapping[str, str]) -> Event:
    """Turn a parsed payload into an Event, deriving a dedupe id you can trust.

    Preference order for the id: the provider's own record id, then a hash of the
    exact bytes. The hash fallback means an event with no id is still deduplicated
    rather than silently allowed to double-process.
    """
    name = str(payload.get("event") or payload.get("event_type") or "").strip()
    data = payload.get("data")
    if not isinstance(data, Mapping):
        data = {}

    record_id = data.get("id")
    if record_id is None:
        record_id = payload.get("id")
    if record_id is not None and str(record_id).strip():
        event_id = "%s:%s:%s" % (provider, name or "event", record_id)
    else:
        event_id = "%s:%s:sha256:%s" % (provider, name or "event", _digest(raw))

    return Event(provider=provider, name=name, data=data, event_id=event_id,
                 raw=raw, headers=dict(headers or {}))


def header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive header lookup that works for dicts and Starlette's Headers."""
    if not headers:
        return ""
    try:
        value = headers.get(name)  # type: ignore[union-attr]
        if value is not None:
            return str(value)
    except AttributeError:
        pass
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return "" if value is None else str(value)
    return ""


def load_json(raw: bytes) -> Mapping[str, Any]:
    """Parse the body into an object, or raise MalformedPayload via the caller."""
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("body is not JSON: %s" % exc.__class__.__name__) from exc
    if not isinstance(payload, Mapping):
        raise ValueError("body is JSON but not an object")
    return payload
