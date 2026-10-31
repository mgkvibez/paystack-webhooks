"""Event id derivation, because it is the only replay defence available."""

from __future__ import annotations

import pytest

from paystack_webhooks.event import Event, build_event, header


def test_data_id_is_preferred_for_the_event_id():
    event = build_event("paystack", {"event": "charge.success", "data": {"id": 77}}, b"{}", {})
    assert event.event_id == "paystack:charge.success:77"


def test_top_level_id_is_used_when_data_has_none():
    event = build_event("flutterwave", {"event": "x", "id": 5, "data": {}}, b"{}", {})
    assert event.event_id == "flutterwave:x:5"


def test_without_any_id_a_body_hash_is_used_and_is_stable():
    a = build_event("paystack", {"event": "x"}, b'{"event":"x"}', {})
    b = build_event("paystack", {"event": "x"}, b'{"event":"x"}', {})
    c = build_event("paystack", {"event": "x"}, b'{"event":"y"}', {})
    assert a.event_id == b.event_id
    assert a.event_id != c.event_id
    assert a.event_id.startswith("paystack:x:sha256:")


def test_non_mapping_data_is_replaced_with_an_empty_mapping():
    event = build_event("paystack", {"event": "x", "data": "oops"}, b"{}", {})
    assert event.data == {}


def test_to_dict_is_json_ready():
    event = build_event("paystack", {"event": "charge.success", "data": {"id": 1}}, b"{}", {})
    assert event.to_dict() == {"provider": "paystack", "name": "charge.success",
                               "event_id": "paystack:charge.success:1", "data": {"id": 1}}


def test_repr_hides_raw_bytes():
    event = build_event("paystack", {"event": "x"}, b"secret-ish-body", {})
    assert "secret-ish-body" not in repr(event)


def test_an_event_without_a_name_is_invalid():
    with pytest.raises(ValueError):
        Event(provider="paystack", name="", data={}, event_id="x")


def test_header_lookup_handles_missing_and_odd_values():
    assert header({}, "x-y") == ""
    assert header({"X-Y": "v"}, "x-y") == "v"
    assert header({"x-y": None}, "x-y") == ""
    assert header(None, "x-y") == ""
