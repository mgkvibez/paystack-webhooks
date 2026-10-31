"""Flask view factory for verified webhooks.

    app.add_url_rule("/webhooks/paystack", view_func=webhook_view(verifier), methods=["POST"])

Flask gives you `request.get_data()` for the raw bytes. Do not use `request.json`:
by then the bytes are gone and the digest cannot match.
"""

from __future__ import annotations

from typing import Optional

from ..errors import MalformedPayload, RawBodyRequired, SignatureError
from ..idempotency import Store


def webhook_view(verifier, *, store: Optional[Store] = None, on_event=None):
    from flask import jsonify, request

    def view():
        body = request.get_data(cache=True)
        try:
            event = verifier.parse(body, request.headers)
        except RawBodyRequired as exc:
            return jsonify({"error": str(exc)}), 500
        except SignatureError:
            return jsonify({"error": "invalid signature"}), 401
        except MalformedPayload as exc:
            return jsonify({"error": str(exc)}), 400

        if store is not None and store.seen(event.event_id):
            return jsonify({"status": "duplicate", "event_id": event.event_id}), 200

        if on_event is not None:
            on_event(event)
        return jsonify({"status": "accepted", "event": event.name}), 200

    return view
