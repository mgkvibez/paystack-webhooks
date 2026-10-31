"""Send a recorded delivery again, signed over the bytes that were actually received.

The failure this fixes: the provider retried three times, your handler 500ed, and the
body is gone. Re-posting a re-serialised dict produces a valid-looking payload whose
signature does not match, so the honest receiver rejects it and the debugging session
starts by blaming the wrong component.

So the body is reused byte for byte and the signature is recomputed over those bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping, Optional

SIGNATURE_HEADER = "X-Paystack-Signature"
CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class ReplayResult:
    reference: Optional[str]
    url: str
    status: Optional[int]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), bytes(body), hashlib.sha512).hexdigest()


def _default_sender(url: str, body: bytes, headers: Mapping[str, str]) -> int:
    request = urllib.request.Request(url, data=bytes(body), method="POST",
                                     headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def replay_deliveries(
    deliveries: Iterable[object],
    url: str,
    *,
    secret: Optional[str] = None,
    sender: Optional[Callable[[str, bytes, Mapping[str, str]], int]] = None,
) -> List[ReplayResult]:
    """POST each delivery to ``url``. The caller decides what to do with the results."""
    if not url:
        raise ValueError("a replay needs a target url")
    send = sender or _default_sender
    out: List[ReplayResult] = []

    for delivery in deliveries:
        body = bytes(delivery.body)
        headers = dict(getattr(delivery, "headers", {}) or {})
        headers.setdefault("Content-Type", CONTENT_TYPE)
        if secret:
            headers[SIGNATURE_HEADER] = sign(body, secret)
        reference = getattr(delivery, "reference", None)
        try:
            out.append(ReplayResult(reference, url, send(url, body, headers)))
        except Exception as exc:  # a single unreachable target must not abort the rest
            out.append(ReplayResult(reference, url, None, "%s: %s" % (type(exc).__name__, exc)))
    return out
