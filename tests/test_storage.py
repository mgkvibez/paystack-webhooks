import json

import pytest

from paystack_webhooks.storage import Delivery, SQLiteStore


def _body(reference="T1", amount=50000):
    return json.dumps({"event": "charge.success",
                       "data": {"reference": reference, "amount": amount,
                                "currency": "NGN"}}).encode()


def test_accept_reports_first_sight_only(tmp_path):
    store = SQLiteStore(str(tmp_path / "d.db"))
    assert store.accept("k1", body=_body()) is True
    assert store.accept("k1", body=_body()) is False
    assert len(store) == 1
    store.close()


def test_raw_body_survives_byte_for_byte(tmp_path):
    """Replay is only valid if the signature covers the same bytes we send back."""
    exact = b'{"event": "charge.success",   "data": {"reference": "T1"}}'
    store = SQLiteStore(str(tmp_path / "d.db"))
    store.accept("k1", body=exact, headers={"X-Paystack-Signature": "abc"})
    got = store.deliveries()[0]
    assert got.body == exact
    assert got.headers == {"X-Paystack-Signature": "abc"}
    store.close()


def test_it_persists_across_reopen(tmp_path):
    path = str(tmp_path / "d.db")
    first = SQLiteStore(path)
    first.accept("k1", body=_body(), reference="T1", provider="paystack",
                 received_at="2026-10-31T20:00:00")
    first.close()

    second = SQLiteStore(path)
    assert len(second) == 1
    assert second.seen("k1") is True
    assert second.deliveries("T1")[0].provider == "paystack"
    second.close()


def test_deliveries_filter_and_order(tmp_path):
    store = SQLiteStore(str(tmp_path / "d.db"))
    store.accept("k1", body=_body("T1"), reference="T1", received_at="2026-10-31T20:00:00")
    store.accept("k2", body=_body("T2"), reference="T2", received_at="2026-10-31T20:00:01")
    store.accept("k3", body=_body("T1"), reference="T1", received_at="2026-10-31T20:00:02")
    assert [d.key for d in store.deliveries()] == ["k1", "k2", "k3"]
    assert [d.key for d in store.deliveries("T1")] == ["k1", "k3"]
    assert store.deliveries("nope") == []
    store.close()


def test_seen_is_the_store_protocol(tmp_path):
    store = SQLiteStore(str(tmp_path / "d.db"))
    assert store.seen("k1") is False
    assert store.seen("k1") is True
    store.close()


def test_empty_key_is_refused(tmp_path):
    store = SQLiteStore(str(tmp_path / "d.db"))
    with pytest.raises(ValueError):
        store.accept("", body=_body())
    store.close()


def test_delivery_is_immutable(tmp_path):
    d = Delivery("k", None, "T1", b"{}", {}, "")
    with pytest.raises(Exception):
        d.key = "other"
