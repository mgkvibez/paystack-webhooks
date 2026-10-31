# Changelog

## v0.2.0 - 2026-10-31

Reconciliation and replay: the half of the webhook problem verification cannot cover,
because verification is worthless when the body never arrives.

- `SQLiteStore` records each delivery with its **raw body**, not just the dedupe key.
  Replay is only valid if the signature is recomputed over the bytes that were actually
  received, so storing a parsed payload would have made replay silently useless.
- `reconcile` compares a provider ledger against recorded deliveries and reports six
  distinct findings. Amounts are integers in minor units; comparing floats would report a
  mismatch on transactions that agree.
- `replay` re-posts stored deliveries, re-signing over the original bytes. A failed target
  does not abort the remaining replays. `--dry-run` proves the plan without a network.
- New `paystack-webhook` console script. The package had no entry point at all before
  this, which is why it was library-only.
- `scripts/verify.sh` gained check 7: the documented exit codes (0 clean, 1 findings,
  2 usage) asserted against a real database and real ledgers.


## v0.1.1 - 2026-10-31

- Distribution renamed to `paystack-webhook` (singular). PyPI rejected
  `paystack-webhooks` as too similar to an existing project, and the distribution name
  must equal the PyPI project name exactly or the upload fails with a 403. The import
  path `paystack_webhooks`, the repo name and the API are unchanged.
- `scripts/verify.sh` gained check 6: the distribution name in `pyproject.toml` must
  equal the name the README tells people to install. The wheel-content check already
  existed (it guards the tokentracker 0.2.0 mode where a wheel holds only dist-info);
  this rename proved a different gap, that the published name can drift from the
  documented one without any test noticing.


## v0.1.0

- Paystack verification: HMAC-SHA512 over the raw request body, constant-time compare,
  typed errors.
- Flutterwave verification: `verif-hash`, with the weaker guarantee documented rather
  than implied.
- `event_id` derivation and a thread-safe, TTL-bounded `MemoryStore` for retry
  deduplication. `process()` returns the event once and `None` for repeat deliveries.
- FastAPI and Flask adapters. Duplicates answer 200 so providers stop retrying.
- Zero runtime dependencies; frameworks are dev extras only.
