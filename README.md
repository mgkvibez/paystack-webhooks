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
pipx install paystack-webhook
```

The distribution is called `paystack-webhook`, singular, because PyPI refused
`paystack-webhooks` as too similar to a project that already exists. Nothing a user
types changes: the import is `paystack_webhooks` and the repo keeps its name.

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

## When a delivery never arrives

Verification only helps if the body shows up. The failure that costs money is the
opposite one: the provider says paid, your handler never ran, and nothing is reconciling
the two. This package now carries a store, a reconciliation job and a replay CLI for it.

Pass the store when you construct the webhook, so deliveries are recorded with their raw
bytes:

```python
from paystack_webhooks import PaystackWebhook, SQLiteStore

store = SQLiteStore("deliveries.db")
paystack = PaystackWebhook("sk_live_...", store=store)
```

Then compare the provider's ledger against what actually arrived:

```bash
paystack-webhook reconcile --store deliveries.db --ledger transactions.json
```

Each finding is a different bug with a different fix:

| Finding | What it means |
|---|---|
| `paid_no_delivery` | the ledger says paid and no webhook ever reached you |
| `delivery_no_ledger` | a delivery for a reference the provider does not know |
| `amount_mismatch` / `currency_mismatch` | the delivery disagrees with the ledger, in minor units |
| `duplicate_delivery` | more than one delivery for one reference |
| `ledger_state_mismatch` | the delivery says success, the ledger says otherwise |
| `unparseable_delivery` | the stored body is not a payload with a reference |

Exit codes are the contract: `0` clean, `1` findings, `2` usage error. `--json` for a
machine.

To resend a loss:

```bash
paystack-webhook replay --store deliveries.db --url http://localhost:3000/webhook --reference T1234
```

The body is reused byte for byte and the signature is recomputed over those bytes. A
re-serialised JSON body produces a signature that no longer matches, which is the bug
replay exists to avoid. Without `--secret` (or `$PAYSTACK_WEBHOOK_SECRET`) the stored
signature header is reused unchanged, which is only correct if your secret has not
rotated. `--dry-run` prints the plan and touches no network.

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
