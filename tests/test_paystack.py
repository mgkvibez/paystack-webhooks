"""Paystack verification: the signature must bind to the exact bytes."""

from __future__ import annotations

import json

import pytest
from conftest import headers, paystack_signature

from paystack_webhooks import (
    MalformedPayload,
    MemoryStore,
    PaystackWebhook,
    RawBodyRequired,
    SignatureError,
)


@pytest.fixture
def client(secret):
    return PaystackWebhook(secret)


def test_a_correctly_signed_body_parses(client, secret, charge_body):
    event = client.parse(charge_body, headers(paystack_signature(secret, charge_body)))
    assert event.provider == "paystack"
    assert event.name == "charge.success"
    assert event.data["reference"] == "T1234"
    assert event.event_id == "paystack:charge.success:302961"


def test_expected_signature_matches_the_independent_helper(client, secret):
    body = b'{"event":"x"}'
    assert client.expected_signature(body) == paystack_signature(secret, body)


def test_wrong_secret_is_refused(client, charge_body):
    other = paystack_signature("sk_test_wrong", charge_body)
    with pytest.raises(SignatureError):
        client.parse(charge_body, headers(other))


def test_a_tampered_body_is_refused(client, secret, charge_body):
    good = paystack_signature(secret, charge_body)
    tampered = charge_body.replace(b"100000", b"1")
    with pytest.raises(SignatureError):
        client.parse(tampered, headers(good))


def test_missing_or_empty_header_is_refused(client, charge_body):
    with pytest.raises(SignatureError):
        client.parse(charge_body, {})
    with pytest.raises(SignatureError):
        client.parse(charge_body, {"x-paystack-signature": ""})


def test_header_name_is_case_insensitive(client, secret, charge_body):
    sig = paystack_signature(secret, charge_body)
    assert client.parse(charge_body, {"X-Paystack-Signature": sig}).name == "charge.success"


def test_surrounding_whitespace_in_the_header_is_tolerated(client, secret, charge_body):
    sig = paystack_signature(secret, charge_body)
    assert client.parse(charge_body, {"x-paystack-signature": " " + sig + "\n"}).name


def test_a_non_ascii_signature_header_does_not_crash(client, charge_body):
    with pytest.raises(SignatureError):
        client.parse(charge_body, {"x-paystack-signature": "sïgnature"})


def test_a_str_body_is_refused_with_an_explanation(client):
    with pytest.raises(RawBodyRequired) as exc:
        client.parse('{"event":"x"}', {})
    assert "raw bytes" in str(exc.value)


@pytest.mark.parametrize("body", [{"event": "x"}, 42, None])
def test_non_byte_bodies_are_refused(client, body):
    with pytest.raises(RawBodyRequired):
        client.parse(body, {})


def test_a_bytearray_body_is_accepted(client, secret, charge_body):
    sig = paystack_signature(secret, charge_body)
    assert client.parse(bytearray(charge_body), headers(sig)).name == "charge.success"


def test_invalid_json_with_a_valid_signature_is_a_payload_error(client, secret):
    body = b"<html>not json</html>"
    with pytest.raises(MalformedPayload) as exc:
        client.parse(body, headers(paystack_signature(secret, body)))
    assert "not JSON" in str(exc.value)


def test_a_json_array_with_a_valid_signature_is_a_payload_error(client, secret):
    body = b"[1,2,3]"
    with pytest.raises(MalformedPayload):
        client.parse(body, headers(paystack_signature(secret, body)))


def test_a_payload_without_an_event_name_is_a_payload_error(client, secret):
    body = json.dumps({"data": {"id": 1}}).encode()
    with pytest.raises(MalformedPayload):
        client.parse(body, headers(paystack_signature(secret, body)))


def test_event_without_data_still_produces_a_stable_id(client, secret):
    body = json.dumps({"event": "customeridentification.success"}).encode()
    first = client.parse(body, headers(paystack_signature(secret, body)))
    second = client.parse(body, headers(paystack_signature(secret, body)))
    assert first.data == {}
    assert first.event_id == second.event_id
    assert first.event_id.startswith("paystack:customeridentification.success:")


def test_process_returns_the_event_once_then_none(client, secret, charge_body):
    store = MemoryStore()
    sig = headers(paystack_signature(secret, charge_body))
    assert client.process(charge_body, sig, store=store) is not None
    assert client.process(charge_body, sig, store=store) is None


def test_a_store_passed_to_the_constructor_is_used_by_default(secret, charge_body):
    store = MemoryStore()
    client = PaystackWebhook(secret, store=store)
    sig = headers(paystack_signature(secret, charge_body))
    assert client.process(charge_body, sig) is not None
    assert client.process(charge_body, sig) is None


def test_process_still_verifies_before_deduplicating(secret, charge_body):
    client = PaystackWebhook(secret, store=MemoryStore())
    with pytest.raises(SignatureError):
        client.process(charge_body, headers("deadbeef"))


@pytest.mark.parametrize("value", ["", "   ", None])
def test_an_empty_secret_is_refused_at_construction(value):
    with pytest.raises(ValueError):
        PaystackWebhook(value)
