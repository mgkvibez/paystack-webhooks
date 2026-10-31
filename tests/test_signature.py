"""HMAC and constant-time comparison."""

from __future__ import annotations

import hashlib
import hmac

from paystack_webhooks.signature import constant_time_equals, hmac_sha256_hex, hmac_sha512_hex


def test_sha512_digest_matches_a_hand_rolled_hmac():
    body = b'{"event":"charge.success"}'
    assert hmac_sha512_hex("sk_test_x", body) == hmac.new(
        b"sk_test_x", body, hashlib.sha512).hexdigest()


def test_sha256_helper_matches_its_own_digest():
    body = b"payload"
    assert hmac_sha256_hex("k", body) == hmac.new(b"k", body, hashlib.sha256).hexdigest()


def test_constant_time_equals_matches_and_rejects():
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("abc", "abcd")


def test_constant_time_equals_strips_surrounding_whitespace():
    assert constant_time_equals("abc", "  abc\n")


def test_empty_either_side_is_never_equal():
    assert not constant_time_equals("", "")
    assert not constant_time_equals("abc", "")
    assert not constant_time_equals("", "abc")


def test_non_ascii_header_returns_false_instead_of_raising():
    # compare_digest refuses non-ASCII str, so this must not explode on a crafted header
    assert constant_time_equals("abc", "ábc") is False
