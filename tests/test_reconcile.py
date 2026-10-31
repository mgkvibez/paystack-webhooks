import json

import pytest

from paystack_webhooks.reconcile import (
    AMOUNT_MISMATCH,
    CURRENCY_MISMATCH,
    DELIVERY_NO_LEDGER,
    DUPLICATE_DELIVERY,
    LEDGER_STATE_MISMATCH,
    PAID_NO_DELIVERY,
    UNPARSEABLE_DELIVERY,
    LedgerEntry,
    load_ledger,
    reconcile,
)


class FakeDelivery:
    def __init__(self, key, body, reference=None):
        self.key = key
        self.body = body
        self.reference = reference


def _d(key, reference="T1", amount=50000, currency="NGN", event="charge.success", ref=None):
    return FakeDelivery(key, json.dumps(
        {"event": event, "data": {"reference": reference, "amount": amount,
                                  "currency": currency}}).encode())


def _ledger(*entries):
    return [LedgerEntry(reference=r, amount=a, currency=c, status=s) for r, a, c, s in entries]


def test_agreement_is_silent():
    findings = reconcile([_d("k1")], _ledger(("T1", 50000, "NGN", "success")))
    assert findings == []


def test_paid_but_never_delivered():
    findings = reconcile([], _ledger(("T1", 50000, "NGN", "success")))
    assert [f.kind for f in findings] == [PAID_NO_DELIVERY]
    assert findings[0].reference == "T1"


def test_pending_ledger_entry_is_not_a_finding():
    assert reconcile([], _ledger(("T1", 50000, "NGN", "pending"))) == []


def test_delivery_for_unknown_reference():
    findings = reconcile([_d("k1", reference="ghost")], _ledger(("T1", 50000, "NGN", "success")))
    kinds = sorted(f.kind for f in findings)
    assert DELIVERY_NO_LEDGER in kinds
    assert PAID_NO_DELIVERY in kinds


def test_amount_and_currency_mismatch():
    findings = reconcile([_d("k1", amount=49999, currency="GHS")],
                         _ledger(("T1", 50000, "NGN", "success")))
    assert sorted(f.kind for f in findings) == [AMOUNT_MISMATCH, CURRENCY_MISMATCH]


def test_success_delivery_against_failed_ledger():
    findings = reconcile([_d("k1")], _ledger(("T1", 50000, "NGN", "failed")))
    assert [f.kind for f in findings] == [LEDGER_STATE_MISMATCH]


def test_duplicate_deliveries_are_one_finding():
    findings = reconcile([_d("k1"), _d("k2")], _ledger(("T1", 50000, "NGN", "success")))
    assert [f.kind for f in findings] == [DUPLICATE_DELIVERY]
    assert "2 deliveries" in findings[0].detail


def test_unparseable_body_is_reported_not_raised():
    broken = FakeDelivery("k1", b"not json")
    findings = reconcile([broken], _ledger(("T1", 50000, "NGN", "success")))
    kinds = sorted(f.kind for f in findings)
    assert UNPARSEABLE_DELIVERY in kinds


def test_body_without_reference_is_reported():
    body = json.dumps({"event": "charge.success", "data": {"amount": 5}}).encode()
    findings = reconcile([FakeDelivery("k1", body)], [])
    assert [f.kind for f in findings] == [UNPARSEABLE_DELIVERY]


def test_flutterwave_status_and_tx_ref():
    body = json.dumps({"event": "charge.completed",
                       "data": {"tx_ref": "FLW1", "amount": 100, "currency": "NGN",
                                "status": "successful"}}).encode()
    assert reconcile([FakeDelivery("k1", body)],
                     _ledger(("FLW1", 100, "NGN", "successful"))) == []


@pytest.mark.parametrize("payload", [
    {"transactions": [{"reference": "T1", "amount": 1, "currency": "ngn", "status": "success"}]},
    {"data": [{"reference": "T1", "amount": 1, "currency": "NGN", "status": "success"}]},
    [{"reference": "T1", "amount": 1, "currency": "NGN", "status": "success"}],
])
def test_ledger_shapes(payload):
    entries = load_ledger(payload)
    assert entries[0].reference == "T1"
    assert entries[0].currency == "NGN"


def test_ledger_from_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps([{"reference": "T1", "amount": "50000",
                                 "currency": "NGN", "status": "success"}]))
    entries = load_ledger(str(path))
    assert entries[0].amount == 50000


def test_ledger_rejects_missing_reference():
    with pytest.raises(ValueError):
        load_ledger([{"amount": 1}])


def test_ledger_rejects_fractional_minor_units():
    with pytest.raises(ValueError):
        load_ledger([{"reference": "T1", "amount": 1.5}])
