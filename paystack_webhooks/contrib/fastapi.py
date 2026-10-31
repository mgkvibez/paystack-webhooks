"""Mount a verified webhook route in four lines.

    app.include_router(webhook_route(PaystackWebhook(secret), store=MemoryStore()))

Duplicates return 200 on purpose. Paystack retries on any non-2xx, so answering
409 to a duplicate starts a retry storm for an event you already handled.
"""

import inspect
from typing import Awaitable, Callable, Optional, Union

from fastapi import APIRouter, HTTPException, Request

from ..errors import MalformedPayload, RawBodyRequired, SignatureError
from ..event import Event
from ..idempotency import Store

Handler = Callable[[Event], Union[None, Awaitable[None]]]


def webhook_route(verifier, *, store: Optional[Store] = None,
                  on_event: Optional[Handler] = None, path: str = "/webhooks/paystack"):
    router = APIRouter()

    @router.post(path)
    async def receive(request: Request) -> dict:
        body = await request.body()
        try:
            event = verifier.parse(body, request.headers)
        except RawBodyRequired as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except SignatureError as exc:
            raise HTTPException(status_code=401, detail="invalid signature") from exc
        except MalformedPayload as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if store is not None and store.seen(event.event_id):
            return {"status": "duplicate", "event_id": event.event_id}

        if on_event is not None:
            result = on_event(event)
            if inspect.isawaitable(result):
                await result
        return {"status": "accepted", "event": event.name, "event_id": event.event_id}

    return router
