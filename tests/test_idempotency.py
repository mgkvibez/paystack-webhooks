"""The store that stops a retry from charging twice."""

from __future__ import annotations

import threading

import pytest

from paystack_webhooks.idempotency import MemoryStore


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_first_use_is_new_and_second_is_seen():
    store = MemoryStore()
    assert store.seen("k1") is False
    assert store.seen("k1") is True


def test_distinct_keys_are_independent():
    store = MemoryStore()
    assert store.seen("a") is False
    assert store.seen("b") is False
    assert store.seen("a") is True


def test_ttl_expiry_allows_the_key_again_only_after_the_window():
    clock = FakeClock()
    store = MemoryStore(ttl_seconds=60, clock=clock)
    assert store.seen("k") is False
    clock.now += 59
    assert store.seen("k") is True
    clock.now += 2
    assert store.seen("k") is False, "an expired key must look new again"


def test_oldest_entries_are_evicted_at_the_cap():
    clock = FakeClock()
    store = MemoryStore(max_entries=3, ttl_seconds=10_000, clock=clock)
    for i in range(4):
        store.seen("k%d" % i)
        clock.now += 1
    assert len(store) == 3
    assert store.seen("k0") is False, "the oldest key should have been evicted"


def test_concurrent_deliveries_of_one_key_elect_exactly_one_winner():
    store = MemoryStore()
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(50)

    def deliver():
        barrier.wait()
        fresh = not store.seen("same-event")
        with lock:
            results.append(fresh)

    threads = [threading.Thread(target=deliver) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1, "two threads must never both be told it is new"


def test_empty_key_is_refused():
    with pytest.raises(ValueError):
        MemoryStore().seen("")


@pytest.mark.parametrize("kwargs", [{"ttl_seconds": 0}, {"max_entries": 0},
                                    {"ttl_seconds": -5}, {"max_entries": -1}])
def test_invalid_configuration_is_refused(kwargs):
    with pytest.raises(ValueError):
        MemoryStore(**kwargs)
