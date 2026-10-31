# Changelog

## v0.1.0

- Paystack verification: HMAC-SHA512 over the raw request body, constant-time compare,
  typed errors.
- Flutterwave verification: `verif-hash`, with the weaker guarantee documented rather
  than implied.
- `event_id` derivation and a thread-safe, TTL-bounded `MemoryStore` for retry
  deduplication. `process()` returns the event once and `None` for repeat deliveries.
- FastAPI and Flask adapters. Duplicates answer 200 so providers stop retrying.
- Zero runtime dependencies; frameworks are dev extras only.
