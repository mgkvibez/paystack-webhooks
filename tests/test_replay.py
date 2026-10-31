import hashlib
import hmac
import json

import pytest

from paystack_webhooks.replay import SIGNATURE_HEADER, replay_deliveries, sign
from paystack_webhooks.storage import SQLiteStore

SECRET = "sk_test_demo"


def _store(tmp_path, reference="T1", body=None):
    store = SQLiteStore(str(tmp_path / "d.db"))
    store.accept("%s-key" % reference,
                 body=body or json.dumps({"event": "charge.success",
                                          "data": {"reference": reference,
                                                   "amount": 50000}}).encode(),
                 headers={"X-Paystack-Signature": "stale", "Content-Type": "application/json"},
                 reference=reference, provider="paystack")
    return store


def test_resigned_over_the_original_bytes(tmp_path):
    """The punchline of the whole module: signature must match what we send."""
    store = _store(tmp_path)
    captured = {}

    def sender(url, body, headers):
        captured["body"] = body
        captured["headers"] = dict(headers)
        return 200

    results = replay_deliveries(store.deliveries(), "http://local/hook",
                                secret=SECRET, sender=sender)
    assert results[0].ok
    expected = hmac.new(SECRET.encode(), captured["body"], hashlib.sha512).hexdigest()
    assert captured["headers"][SIGNATURE_HEADER] == expected
    assert captured["body"] == store.deliveries()[0].body
    store.close()


def test_original_signature_is_kept_without_a_secret(tmp_path):
    store = _store(tmp_path)
    captured = {}
    replay_deliveries(store.deliveries(), "http://local/hook",
                      sender=lambda u, b, h: captured.update(h=h) or 200)
    assert captured["h"][SIGNATURE_HEADER] == "stale"
    store.close()


def test_sign_matches_the_packages_own_verifier():
    """Replay signs with the same function the verifier checks against."""
    from paystack_webhooks.signature import hmac_sha512_hex
    body = b'{"a": 1}'
    assert sign(body, SECRET) == hmac_sha512_hex(SECRET, body)


def test_one_bad_target_does_not_abort_the_run(tmp_path):
    store = _store(tmp_path, "T1")
    store.accept("t2-key", body=b'{"event":"charge.success","data":{"reference":"T2"}}',
                 reference="T2")
    calls = {"n": 0}

    def sender(url, body, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("refused")
        return 202

    results = replay_deliveries(store.deliveries(), "http://local/hook", sender=sender)
    assert [r.ok for r in results] == [False, True]
    assert "ConnectionError" in results[0].error
    store.close()


def test_non_2xx_is_not_ok(tmp_path):
    store = _store(tmp_path)
    results = replay_deliveries(store.deliveries(), "http://local/hook",
                                sender=lambda u, b, h: 500)
    assert results[0].ok is False and results[0].status == 500
    store.close()


def test_empty_url_is_refused(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        replay_deliveries(store.deliveries(), "", sender=lambda u, b, h: 200)
    store.close()
