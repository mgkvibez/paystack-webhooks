"""Framework adapters, plus the guarantee that the core imports no framework."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import charge_body as _charge_body  # noqa: F401  (fixture re-export)
from conftest import paystack_signature

fastapi = pytest.importorskip("fastapi")
flask = pytest.importorskip("flask")


def _fastapi_app(secret, calls, async_handler=False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from paystack_webhooks import MemoryStore, PaystackWebhook
    from paystack_webhooks.contrib.fastapi import webhook_route

    app = FastAPI()
    store = MemoryStore()
    if async_handler:
        async def on_event(event):
            calls.append(event.event_id)
    else:
        def on_event(event):
            calls.append(event.event_id)

    app.include_router(webhook_route(PaystackWebhook(secret), store=store,
                                     on_event=on_event, path="/hooks"))
    return TestClient(app)


def test_fastapi_accepts_a_valid_delivery_once(secret, charge_body):
    calls = []
    client = _fastapi_app(secret, calls)
    sig = paystack_signature(secret, charge_body)
    first = client.post("/hooks", content=charge_body, headers={"x-paystack-signature": sig})
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    second = client.post("/hooks", content=charge_body, headers={"x-paystack-signature": sig})
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert calls == ["paystack:charge.success:302961"], "the handler must run exactly once"


def test_fastapi_rejects_a_bad_signature_with_401(secret, charge_body):
    client = _fastapi_app(secret, [])
    response = client.post("/hooks", content=charge_body,
                           headers={"x-paystack-signature": "deadbeef"})
    assert response.status_code == 401


def test_fastapi_rejects_a_missing_signature_with_401(secret, charge_body):
    client = _fastapi_app(secret, [])
    assert client.post("/hooks", content=charge_body).status_code == 401


def test_fastapi_returns_400_for_validly_signed_garbage(secret):
    client = _fastapi_app(secret, [])
    body = b"not json"
    response = client.post("/hooks", content=body,
                           headers={"x-paystack-signature": paystack_signature(secret, body)})
    assert response.status_code == 400


def test_fastapi_awaits_an_async_handler(secret, charge_body):
    calls = []
    client = _fastapi_app(secret, calls, async_handler=True)
    sig = paystack_signature(secret, charge_body)
    assert client.post("/hooks", content=charge_body,
                       headers={"x-paystack-signature": sig}).status_code == 200
    assert calls, "an async handler must be awaited before responding"


def test_flask_view_accepts_and_deduplicates(secret, charge_body):
    from flask import Flask

    from paystack_webhooks import MemoryStore, PaystackWebhook
    from paystack_webhooks.contrib.flask import webhook_view

    app = Flask(__name__)
    app.add_url_rule("/hooks", view_func=webhook_view(PaystackWebhook(secret),
                                                      store=MemoryStore()), methods=["POST"])
    client = app.test_client()
    sig = paystack_signature(secret, charge_body)
    assert client.post("/hooks", data=charge_body,
                       headers={"x-paystack-signature": sig}).status_code == 200
    again = client.post("/hooks", data=charge_body, headers={"x-paystack-signature": sig})
    assert again.get_json()["status"] == "duplicate"


def test_flask_view_rejects_a_bad_signature(secret, charge_body):
    from flask import Flask

    from paystack_webhooks import PaystackWebhook
    from paystack_webhooks.contrib.flask import webhook_view

    app = Flask(__name__)
    app.add_url_rule("/hooks", view_func=webhook_view(PaystackWebhook(secret)),
                     methods=["POST"])
    assert app.test_client().post("/hooks", data=charge_body,
                                  headers={"x-paystack-signature": "nope"}).status_code == 401


def test_importing_the_core_pulls_in_no_web_framework():
    code = ("import sys, paystack_webhooks; "
            "print(','.join(m for m in ('fastapi','flask','django','starlette') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", "the core must stay dependency-free"
