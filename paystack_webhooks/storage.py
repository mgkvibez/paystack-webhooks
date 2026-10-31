"""A store that keeps the delivery, not just the fact that it arrived.

``MemoryStore`` answers one question: have I seen this key before? That is enough to
dedupe and nothing else. Reconciliation needs to know what was actually promised, and
replay needs the original raw body, because the signature is computed over exactly
those bytes. A re-serialised JSON body is not the same body and will fail verification
at the receiving end, which makes replay useless for the one job replay exists for.

SQLite because it is in the standard library, survives a restart, and needs no service
running beside it. A reconciliation job on a laptop wants a file, not a cluster.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Mapping, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    key         TEXT PRIMARY KEY,
    provider    TEXT,
    reference   TEXT,
    body        BLOB NOT NULL,
    headers     TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS deliveries_reference ON deliveries(reference);
"""


@dataclass(frozen=True)
class Delivery:
    """One webhook that actually arrived, raw body included."""

    key: str
    provider: Optional[str]
    reference: Optional[str]
    body: bytes
    headers: Mapping[str, str]
    received_at: str


class SQLiteStore:
    """Store-protocol compatible, plus the delivery log replay and reconcile need.

    ``seen`` exists so this can stand in wherever a ``Store`` is expected, but it
    records an empty body. New code should call ``accept`` and pass the body.
    """

    def __init__(self, path: str = ":memory:") -> None:
        if not path:
            raise ValueError("a store path is required")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL keeps a reader (reconcile) from blocking the writer (a delivery).
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- Store protocol ----------------------------------------------------
    def seen(self, key: str) -> bool:
        """True if the key was already present. Records it with an empty body."""
        return not self.accept(key, body=b"")

    # -- the real API ------------------------------------------------------
    def accept(
        self,
        key: str,
        *,
        body: bytes = b"",
        headers: Optional[Mapping[str, str]] = None,
        provider: Optional[str] = None,
        reference: Optional[str] = None,
        received_at: str = "",
    ) -> bool:
        """Record the delivery. True if it is new, False if it is a duplicate.

        One statement, so two concurrent deliveries of the same key cannot both be
        told they are new. That race is a double charge.
        """
        if not key:
            raise ValueError("an idempotency key is required")
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO deliveries"
                " (key, provider, reference, body, headers, received_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (key, provider, reference, bytes(body),
                 json.dumps(dict(headers or {})), received_at),
            )
            inserted = cur.rowcount == 1
            if inserted:
                self._conn.commit()
            return inserted

    def deliveries(self, reference: Optional[str] = None) -> List[Delivery]:
        """Every recorded delivery, oldest first, optionally for one reference."""
        sql = "SELECT * FROM deliveries"
        args: tuple = ()
        if reference is not None:
            sql += " WHERE reference = ?"
            args = (reference,)
        sql += " ORDER BY received_at, rowid"
        rows = self._conn.execute(sql, args).fetchall()
        return [
            Delivery(
                key=r["key"],
                provider=r["provider"],
                reference=r["reference"],
                body=bytes(r["body"]),
                headers=json.loads(r["headers"]),
                received_at=r["received_at"],
            )
            for r in rows
        ]

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
