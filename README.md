# paystack-webhooks

**Verify Paystack and Flutterwave webhooks in Python, including the part the docs skip: retries.**

[![ci](https://github.com/mgkvibez/paystack-webhooks/actions/workflows/ci.yml/badge.svg)](https://github.com/mgkvibez/paystack-webhooks/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](pyproject.toml)

```python
from paystack_webhooks import PaystackWebhook

paystack = PaystackWebhook("sk_live_...")

event = paystack.process(raw_body, headers)   # None means you already handled it
```

That is the whole library. The rest of this page is why `process` exists and the
four-line snippet on Stack Overflow is not enough.

## The snippet everyone copies, and what it misses

```python
if hmac.new(key, request.body, hashlib.sha512).hexdigest() != request.headers["x-paystack-signature"]:
    abort(401)
```

The signature check is right. Two other things are missing, and both cost money.

**1. Retries.** Paystack and Flutterwave both retry when your endpoint does not return
a 2xx: a timeout, a 500, a deploy that restarts the worker mid-request. Your handler
then runs twice for one payment. If the second run grants value again, you have given
away product, and no amount of signature checking prevents it.

**2. Verifying after parsing.** If you call `request.json()` first, the bytes you
hash are not the bytes that arrived: key order and whitespace change, the digest never
matches, and the usual "fix" is to drop the check.

This library handles the raw bytes, derives a stable event id, and gives you a
single call that is safe to repeat.

## Install

```bash
pip install git+https://github.com/mgkvibez/paystack-webhooks.git
```

The PyPI name is reserved for this project and the release workflow is in place; the
published package follows once the trusted publisher is configured. Until then, the
git install above is the honest one.

Python 3.9+, **zero runtime dependencies**. FastAPI and Flask are optional extras that
only the adapters import.

## FastAPI

```python
from fastapi import FastAPI
from paystack_webhooks import MemoryStore, PaystackWebhook
from paystack_webhooks.contrib.fastapi import webhook_route

app = FastAPI()

def on_event(event):
    if event.name == "charge.success":
        fulfil(event.data["reference"], event.data["amount"])

app.include_router(webhook_route(
    PaystackWebhook("sk_live_..."),
    store=MemoryStore(),          # dedupe across retries
    on_event=on_event,
    path="/webhooks/paystack",
))
```

Duplicates return **200**, not 409. Both providers retry on non-2xx, so answering
409 to something you already handled starts a retry storm.

## Flask

```python
from flask import Flask
from paystack_webhooks import MemoryStore, PaystackWebhook
from paystack_webhooks.contrib.flask import webhook_view

app = Flask(__name__)
app.add_url_rule("/webhooks/paystack", methods=["POST"], view_func=webhook_view(
    PaystackWebhook("sk_live_..."), store=MemoryStore(), on_event=on_event))
```

Anywhere else, the core is framework-agnostic: pass the raw bytes and a header mapping
you can read case-insensitively.

## Flutterwave, and the weaker guarantee it actually offers

```python
from paystack_webhooks import FlutterwaveWebhook

flutterwave = FlutterwaveWebhook("your_verif_hash")
event = flutterwave.process(raw_body, headers)
```

Flutterwave does not sign the body. It sends your static secret in a `verif-hash`
header, which proves the sender knows the hash and nothing else. A valid header can
accompany a tampered payload if the hash leaks. This library says so instead of
implying parity with Paystack.

## The security model, stated plainly

| | Paystack | Flutterwave |
|---|---|---|
| What is checked | HMAC-SHA512 over the raw body | static `verif-hash` header |
| Does it cover the body | yes | **no** |
| Signed timestamp | none | none |
| Replay defence | dedupe on `event_id` | dedupe, plus compare amount and currency |

Neither provider sends a signed timestamp, so a "5 minute replay window" is theatre:
there is nothing authentic to compare a clock against. Deduplication is the only
honest defence available, which is why `event_id` is computed for you and why the store
is part of the API.

For Flutterwave, always compare `event.data["amount"]` and `currency` against your own
record before fulfilling. The header cannot tell you the amount is right.

## What this deliberately does not do

- **It is not an API client.** Use `paystackapi` or `rave-python` to charge cards. This
  library only consumes webhooks.
- **It does not validate amounts for you.** That requires your records, not the payload.
- **`MemoryStore` is single-process.** It is correct for one worker. On several
  instances implement the four-line `Store` protocol against Redis or a table with a
  unique constraint; a check-then-insert will race and double-charge.
- **It does not decide your response codes for unknown events.** The adapter returns
  200 and calls your handler; ignore event types you do not care about.

## Errors map to status codes

| Exception | Meaning | Status |
|---|---|---|
| `SignatureError` | wrong secret, forged header, tampered body | 401 |
| `MalformedPayload` | valid signature, unusable body | 400 |
| `RawBodyRequired` | you passed text or a dict instead of bytes | 500, and it is a bug in your code |

## Tests

The suite runs offline: signatures are computed in the tests with `hmac`/`hashlib`
directly, so a bug in this library cannot make its own tests pass. It covers valid and
forged signatures, tampered bodies, non-ASCII headers, text bodies, validly signed
garbage, idempotency including a 50-thread race on one event id, TTL and capacity
eviction, both adapters, and a check that importing the core pulls in no web framework.

```bash
pip install -e ".[dev]"
python -m pytest -q
bash scripts/verify.sh
```

## License

MIT.
