"""Compare what the provider says was paid against what actually reached you.

Every webhook integration fails the same way eventually: a delivery is lost, retried
past its window, or arrives twice, and the two systems quietly disagree about who paid
what. Verification cannot catch that, because there is nothing to verify when a body
never arrives.

The unit here is minor currency units, because that is what Paystack and Flutterwave
send (kobo, pesewas). Comparing floats to money is how you get a mismatch finding on
every single transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Union

PAID_NO_DELIVERY = "paid_no_delivery"
DELIVERY_NO_LEDGER = "delivery_no_ledger"
AMOUNT_MISMATCH = "amount_mismatch"
CURRENCY_MISMATCH = "currency_mismatch"
DUPLICATE_DELIVERY = "duplicate_delivery"
LEDGER_STATE_MISMATCH = "ledger_state_mismatch"
UNPARSEABLE_DELIVERY = "unparseable_delivery"

KINDS = (
    PAID_NO_DELIVERY,
    DELIVERY_NO_LEDGER,
    AMOUNT_MISMATCH,
    CURRENCY_MISMATCH,
    DUPLICATE_DELIVERY,
    LEDGER_STATE_MISMATCH,
    UNPARSEABLE_DELIVERY,
)

_SUCCESS_EVENTS = {
    "payment_intent.succeeded", "checkout.session.completed",
    "charge.succeeded", "invoice.paid",
}
_SUCCESS_STATUSES = {"success", "successful", "completed"}


@dataclass(frozen=True)
class LedgerEntry:
    """One transaction as the provider's API reports it."""

    reference: str
    amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[str] = None

    @property
    def paid(self) -> bool:
        return (self.status or "").lower() in _SUCCESS_STATUSES


@dataclass(frozen=True)
class Finding:
    kind: str
    reference: str
    detail: str


def _as_amount(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("an amount cannot be a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ValueError("amounts are minor units; %r is not whole" % value)
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    return int(text)


def load_ledger(source: Union[str, Sequence[Mapping[str, Any]]]) -> List[LedgerEntry]:
    """Read a ledger from a list of dicts or a JSON file.

    Accepts a bare list, ``{"transactions": [...]}``, or the provider's own
    ``{"data": [...]}`` envelope, because those are the three shapes you actually
    end up holding.
    """
    if isinstance(source, str):
        with open(source, "r", encoding="utf-8") as fh:
            return load_ledger(json.load(fh))
    if isinstance(source, Mapping):
        for key in ("transactions", "data"):
            if isinstance(source.get(key), list):
                return load_ledger(source[key])
        raise ValueError("ledger object has no transactions or data list")

    out: List[LedgerEntry] = []
    for raw in source:
        if not isinstance(raw, Mapping):
            raise ValueError("each ledger entry must be an object")
        reference = raw.get("reference")
        if not reference:
            raise ValueError("a ledger entry is missing its reference")
        currency = raw.get("currency")
        out.append(
            LedgerEntry(
                reference=str(reference),
                amount=_as_amount(raw.get("amount")),
                currency=str(currency).upper() if currency else None,
                status=str(raw["status"]) if raw.get("status") is not None else None,
            )
        )
    return out


def _facts(body: bytes) -> tuple:
    """(event name, reference, amount, currency, successful) from a raw body."""
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("payload is not an object")
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        data = {}
    if isinstance(data, Mapping) and isinstance(data.get("object"), Mapping):
        data = data["object"]           # Stripe nests the record one level deeper
    event = str(payload.get("event") or payload.get("type") or "")
    metadata = data.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    reference = (data.get("reference") or data.get("tx_ref")
                 or data.get("client_reference_id") or metadata.get("reference")
                 or data.get("id") or payload.get("reference"))
    status = str(data.get("status") or "").lower()
    successful = (status in _SUCCESS_STATUSES or event.lower().endswith(".success")
                  or event in _SUCCESS_EVENTS)
    return (
        event,
        str(reference) if reference else None,
        _as_amount(data.get("amount") or data.get("amount_total") or data.get("amount_received")),
        (str(data.get("currency")).upper() if data.get("currency") else None),
        successful,
    )


def reconcile(deliveries: Iterable[Any], ledger: Iterable[LedgerEntry]) -> List[Finding]:
    """Every way the two records can disagree, sorted so the output is stable."""
    findings: List[Finding] = []
    entries = {e.reference: e for e in ledger}
    by_reference: dict = {}

    for delivery in deliveries:
        try:
            event, reference, amount, currency, successful = _facts(delivery.body)
        except (ValueError, UnicodeDecodeError) as exc:
            findings.append(Finding(UNPARSEABLE_DELIVERY, delivery.key,
                                    "body is not readable JSON: %s" % exc))
            continue
        if not reference:
            findings.append(Finding(UNPARSEABLE_DELIVERY, delivery.key,
                                    "body carries no reference"))
            continue
        by_reference.setdefault(reference, []).append(
            {"event": event, "amount": amount, "currency": currency,
             "successful": successful}
        )

        entry = entries.get(reference)
        if entry is None:
            findings.append(Finding(DELIVERY_NO_LEDGER, reference,
                                    "delivery %s for an unknown reference" % event))
            continue
        if successful and not entry.paid:
            findings.append(Finding(LEDGER_STATE_MISMATCH, reference,
                                    "delivery says success, ledger says %s"
                                    % (entry.status or "unknown")))
        if amount is not None and entry.amount is not None and amount != entry.amount:
            findings.append(Finding(AMOUNT_MISMATCH, reference,
                                    "delivery %r, ledger %r (minor units)"
                                    % (amount, entry.amount)))
        if currency and entry.currency and currency != entry.currency:
            findings.append(Finding(CURRENCY_MISMATCH, reference,
                                    "delivery %s, ledger %s" % (currency, entry.currency)))

    for reference, seen in by_reference.items():
        if len(seen) > 1:
            findings.append(Finding(DUPLICATE_DELIVERY, reference,
                                    "%d deliveries for one reference" % len(seen)))

    for reference, entry in entries.items():
        if entry.paid and reference not in by_reference:
            findings.append(Finding(PAID_NO_DELIVERY, reference,
                                    "ledger says paid, no delivery was recorded"))

    return sorted(findings, key=lambda f: (f.kind, f.reference, f.detail))
