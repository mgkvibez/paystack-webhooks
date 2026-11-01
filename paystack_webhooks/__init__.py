"""Verify Paystack and Flutterwave webhooks without getting it wrong, then check up
on them when a delivery goes missing.

    from paystack_webhooks import PaystackWebhook, SQLiteStore

    store = SQLiteStore("deliveries.db")
    paystack = PaystackWebhook("sk_live_...", store=store)
    event = paystack.process(raw_body, headers)   # None means already handled
"""

from .errors import MalformedPayload, RawBodyRequired, SignatureError, WebhookError
from .event import Event
from .flutterwave import FlutterwaveWebhook
from .idempotency import MemoryStore, Store
from .paystack import PaystackWebhook
from .reconcile import Finding, LedgerEntry, load_ledger, reconcile
from .replay import ReplayResult, replay_deliveries, sign
from .storage import Delivery, SQLiteStore
from .stripe import StripeWebhook

__version__ = "0.3.0"

__all__ = [
    "Delivery",
    "Event",
    "Finding",
    "FlutterwaveWebhook",
    "LedgerEntry",
    "MalformedPayload",
    "MemoryStore",
    "PaystackWebhook",
    "StripeWebhook",
    "RawBodyRequired",
    "ReplayResult",
    "SQLiteStore",
    "SignatureError",
    "Store",
    "WebhookError",
    "__version__",
    "load_ledger",
    "reconcile",
    "replay_deliveries",
    "sign",
]
