"""Flutterwave verification, including the honest limits of a static hash."""

from __future__ import annotations

import json

import pytest

from paystack_webhooks import (
    FlutterwaveWebhook,
    MalformedPayload,
    MemoryStore,
    RawBodyRequired,
    SignatureError,
)


@pytest.fixture
def client(flutter_hash):
    return FlutterwaveWebhook(flutter_hash)


def test_matching_verif_hash_is_accepted(client, flutter_hash, charge_body):
    event = client.parse(charge_body, {"verif-hash": flutter_hash})
    assert event.provider == "flutterwave"
    assert event.name == "charge.success"


def test_wrong_hash_is_refused(client, charge_body):
    with pytest.raises(SignatureError):
        client.parse(charge_body, {"verif-hash": "nope"})


def test_missing_hash_is_refused(client, charge_body):
    with pytest.raises(SignatureError):
        client.parse(charge_body, {})


def test_header_is_case_insensitive(client, flutter_hash, charge_body):
    assert client.parse(charge_body, {"Verif-Hash": flutter_hash}).name


def test_the_hash_does_not_cover_the_body_so_dedupe_and_amount_checks_carry_it(
        client, flutter_hash, charge_body):
    # Documents the real weakness: a tampered body still verifies.
    tampered = charge_body.replace(b"100000", b"1")
    assert client.parse(tampered, {"verif-hash": flutter_hash}).data["amount"] == 1


def test_a_str_body_is_refused(client, flutter_hash):
    with pytest.raises(RawBodyRequired):
        client.parse('{"event":"x"}', {"verif-hash": flutter_hash})


def test_invalid_json_with_a_valid_hash_is_a_payload_error(client, flutter_hash):
    with pytest.raises(MalformedPayload):
        client.parse(b"not json", {"verif-hash": flutter_hash})


def test_missing_event_name_is_a_payload_error(client, flutter_hash):
    with pytest.raises(MalformedPayload):
        client.parse(json.dumps({"data": {"id": 9}}).encode(), {"verif-hash": flutter_hash})


def test_process_deduplicates_repeat_deliveries(client, flutter_hash, charge_body):
    store = MemoryStore()
    assert client.process(charge_body, {"verif-hash": flutter_hash}, store=store) is not None
    assert client.process(charge_body, {"verif-hash": flutter_hash}, store=store) is None


@pytest.mark.parametrize("value", ["", "  ", None])
def test_empty_hash_is_refused_at_construction(value):
    with pytest.raises(ValueError):
        FlutterwaveWebhook(value)
