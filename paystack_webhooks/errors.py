"""Typed failures, so a caller can tell a forged request from a broken one.

A 401 and a 400 are different problems for whoever is on call: one means someone
is posting to your endpoint with the wrong secret, the other means the payload is
not what the provider promised. Collapsing them into one exception makes that
distinction impossible to recover.
"""


class WebhookError(Exception):
    """Base class for everything this library raises."""


class SignatureError(WebhookError):
    """The request did not carry a valid signature for the configured secret.

    Treat this as hostile until proven otherwise. Never retry-and-hope on it, and
    never log the provided header value at info level: a wrong secret is usually a
    deployment mistake, but a valid-looking header with a bad digest is a forgery
    attempt and its contents are attacker-controlled.
    """


class MalformedPayload(WebhookError):
    """The signature was valid but the body is not a usable webhook event.

    A valid signature over garbage still means the provider sent garbage, so this
    is a 400, not a 401.
    """


class RawBodyRequired(WebhookError, TypeError):
    """The body arrived as text instead of bytes, so it cannot be verified.

    Re-serialising parsed JSON changes key order and whitespace, which changes the
    digest. This is the single most common way a correct signature check gets
    written and still fails in production, so it is a named error rather than a
    silent coercion.
    """
