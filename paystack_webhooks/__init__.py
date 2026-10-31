"""Verify Paystack and Flutterwave webhooks without getting it wrong.

    from paystack_webhooks import PaystackWebhook, MemoryStore

    paystack = PaystackWebhook("sk_live_...")
    event = paystack.process(raw_body, headers)   # None means already handled
"""

from .errors import MalformedPayload, RawBodyRequired, SignatureError, WebhookError
from .event import Event
from .flutterwave import FlutterwaveWebhook
from .idempotency import MemoryStore, Store
from .paystack import PaystackWebhook

__version__ = "0.1.1"

__all__ = [
    "Event",
    "FlutterwaveWebhook",
    "MalformedPayload",
    "MemoryStore",
    "PaystackWebhook",
    "RawBodyRequired",
    "SignatureError",
    "Store",
    "WebhookError",
    "__version__",
]
