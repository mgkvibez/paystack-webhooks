"""Stripe adapter: the signature scheme, the tolerance window, and the error paths."""

import json

import pytest

from paystack_webhooks import StripeWebhook
from paystack_webhooks.errors import MalformedPayload, RawBodyRequired, SignatureError
from paystack_webhooks.reconcile import load_ledger, reconcile
from paystack_webhooks.stripe import compute_signature, parse_signature_header

SECRET = "whsec_test_secret"
NOW = 1_760_000_000


def body(reference="pi_123", amount=50000, currency="usd"):
    return json.dumps({
        "id": "evt_1",
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": "pi_123",
            "client_reference_id": reference,
            "amount_received": amount,
            "currency": currency,
            "status": "succeeded",
        }},
    }).encode()


def sign(raw, secret=SECRET, timestamp=NOW):
    return "t=%s,v1=%s" % (timestamp, compute_signature(secret, str(timestamp), raw))


def wh(**kwargs):
    kwargs.setdefault("clock", lambda: NOW)
    return StripeWebhook(SECRET, **kwargs)


def test_valid_delivery_is_accepted_and_decoded():
    raw = body()
    event = wh().parse(raw, {"Stripe-Signature": sign(raw)})
    assert event.provider == "stripe"
    assert event.name == "payment_intent.succeeded"
    assert event.data["id"] == "pi_123"
    assert event.raw is raw


def test_event_id_uses_stripes_record_id_then_survives_a_body_change():
    """Dedupe must key on the event id, not the bytes, or a retry re-processes."""
    raw = body()
    event = wh().parse(raw, {"stripe-signature": sign(raw)})
    assert event.event_id == "stripe:payment_intent.succeeded:evt_1"


def test_tampered_body_is_rejected():
    raw = body()
    header = sign(raw)
    with pytest.raises(SignatureError):
        wh().parse(raw.replace(b"50000", b"9"), {"Stripe-Signature": header})


def test_wrong_secret_is_rejected():
    raw = body()
    with pytest.raises(SignatureError):
        wh().parse(raw, {"Stripe-Signature": sign(raw, secret="whsec_other")})


def test_missing_header_is_rejected():
    with pytest.raises(SignatureError):
        wh().parse(body(), {})


def test_str_body_is_refused_because_re_encoding_changes_the_digest():
    with pytest.raises(RawBodyRequired):
        wh().parse(body().decode(), {"Stripe-Signature": sign(body())})


def test_empty_body_is_rejected():
    with pytest.raises(SignatureError):
        wh().parse(b"", {"Stripe-Signature": "t=%s,v1=abc" % NOW})


def test_stale_timestamp_is_refused_as_a_replay():
    raw = body()
    old = NOW - 4000
    with pytest.raises(SignatureError) as exc:
        wh().parse(raw, {"Stripe-Signature": sign(raw, timestamp=old)})
    assert "tolerance" in str(exc.value)


def test_future_timestamp_beyond_tolerance_is_also_refused():
    raw = body()
    with pytest.raises(SignatureError):
        wh().parse(raw, {"Stripe-Signature": sign(raw, timestamp=NOW + 4000)})


def test_tolerance_is_configurable():
    raw = body()
    old = NOW - 4000
    event = wh(tolerance=10_000).parse(raw, {"Stripe-Signature": sign(raw, timestamp=old)})
    assert event.name == "payment_intent.succeeded"


def test_any_matching_v1_digest_is_accepted_during_rotation():
    raw = body()
    timestamp = str(NOW)
    good = compute_signature(SECRET, timestamp, raw)
    header = "t=%s,v1=%s,v1=%s" % (timestamp, "0" * 64, good)
    assert wh().parse(raw, {"Stripe-Signature": header}).name == "payment_intent.succeeded"


def test_unknown_scheme_pairs_are_ignored_not_fatal():
    raw = body()
    timestamp = str(NOW)
    good = compute_signature(SECRET, timestamp, raw)
    header = "t=%s,v2=deadbeef,v1=%s" % (timestamp, good)
    assert wh().parse(raw, {"Stripe-Signature": header}).name


def test_non_numeric_timestamp_is_a_signature_error():
    raw = body()
    with pytest.raises(SignatureError):
        wh().parse(raw, {"Stripe-Signature": "t=abc,v1=deadbeef"})


def test_malformed_json_is_a_payload_error_not_a_signature_error():
    raw = b"not json at all"
    with pytest.raises(MalformedPayload):
        wh().parse(raw, {"Stripe-Signature": sign(raw)})


def test_payload_without_type_is_rejected():
    raw = json.dumps({"id": "evt_1", "data": {"object": {}}}).encode()
    with pytest.raises(MalformedPayload):
        wh().parse(raw, {"Stripe-Signature": sign(raw)})


def test_payload_without_data_object_is_rejected():
    raw = json.dumps({"id": "evt_1", "type": "payment_intent.succeeded"}).encode()
    with pytest.raises(MalformedPayload):
        wh().parse(raw, {"Stripe-Signature": sign(raw)})


def test_signature_header_parser_reads_timestamp_and_all_digests():
    assert parse_signature_header("t=123,v1=aa,v1=bb") == ("123", ["aa", "bb"])
    assert parse_signature_header("") == (None, [])
    assert parse_signature_header("v1=aa") == (None, ["aa"])


def test_empty_secret_is_refused_at_construction():
    with pytest.raises(ValueError):
        StripeWebhook("")


def test_reconcile_reads_stripe_payloads():
    """A Stripe delivery must reconcile against a ledger, not be skipped for its shape."""
    from paystack_webhooks.storage import SQLiteStore

    store = SQLiteStore()
    raw = body(reference="pi_123", amount=50000)
    store.accept("k1", body=raw, reference="pi_123", provider="stripe")
    ledger = load_ledger([
        {"reference": "pi_123", "amount": 50000, "currency": "USD", "status": "success"},
    ])
    findings = reconcile(store.deliveries(), ledger)
    assert findings == [], findings
