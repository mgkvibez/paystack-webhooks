"""`paystack-webhook` - reconcile a ledger against deliveries, and replay them.

Exit codes are a contract, because this runs in cron and in CI:

    0  nothing wrong (no findings, or every replay was accepted)
    1  findings exist, or a replay was not accepted
    2  usage or configuration error (bad path, unreadable ledger, no url)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .reconcile import load_ledger, reconcile
from .replay import replay_deliveries
from .storage import SQLiteStore

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

SECRET_ENV = "PAYSTACK_WEBHOOK_SECRET"


def _store(path: str) -> SQLiteStore:
    if not path:
        raise ValueError("--store is required")
    if not os.path.exists(path):
        raise ValueError("no store at %s (point it at the file your handler writes)" % path)
    return SQLiteStore(path)


def _cmd_reconcile(args: argparse.Namespace) -> int:
    store = _store(args.store)
    try:
        ledger = load_ledger(args.ledger)
        n_deliveries = len(store)
        findings = reconcile(store.deliveries(), ledger)
    finally:
        store.close()

    if args.json:
        print(json.dumps(
            {"findings": [{"kind": f.kind, "reference": f.reference, "detail": f.detail}
                          for f in findings],
             "evidence": {"deliveries": n_deliveries, "ledger_entries": len(ledger)}},
            indent=2))
    elif findings:
        print("Reconciliation found %d problem(s):\n" % len(findings))
        for f in findings:
            print("  %-22s %-14s %s" % (f.kind, f.reference, f.detail))
    else:
        print("Reconciled %d ledger entries against %d deliveries, no discrepancies."
              % (len(ledger), n_deliveries))
    return EXIT_FINDINGS if findings else EXIT_OK


def _cmd_replay(args: argparse.Namespace) -> int:
    store = _store(args.store)
    try:
        wanted: Optional[Sequence[str]] = args.reference or None
        deliveries: List[object] = []
        if wanted:
            for reference in wanted:
                found = store.deliveries(reference)
                if not found:
                    raise ValueError("no stored delivery for reference %s" % reference)
                deliveries.extend(found)
        else:
            deliveries = store.deliveries()
        if not deliveries:
            raise ValueError("the store holds no deliveries to replay")
        secret = args.secret or os.environ.get(SECRET_ENV)

        if args.dry_run:
            for d in deliveries:
                print("would replay %s to %s (%d bytes%s)"
                      % (d.reference or d.key, args.url, len(d.body),
                         ", re-signed" if secret else ", original signature kept"))
            return EXIT_OK

        results = replay_deliveries(deliveries, args.url, secret=secret)
    finally:
        store.close()

    failed = 0
    for r in results:
        if r.ok:
            print("replayed %-14s -> %s %s" % (r.reference or "-", r.status, r.url))
        else:
            failed += 1
            print("FAILED   %-14s -> %s %s"
                  % (r.reference or "-", r.status if r.status else r.error, r.url))
    if failed:
        print("\n%d of %d replays were not accepted" % (failed, len(results)))
        return EXIT_FINDINGS
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paystack-webhook",
        description="Reconcile a provider ledger against the webhooks that actually arrived.")
    parser.add_argument("--version", action="version", version="paystack-webhook %s" % __version__)
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("reconcile", help="compare a ledger with recorded deliveries")
    rec.add_argument("--store", required=True, help="SQLite file your handler writes")
    rec.add_argument("--ledger", required=True, help="ledger JSON (list, or {data: [...]})")
    rec.add_argument("--json", action="store_true", help="machine-readable output")
    rec.set_defaults(func=_cmd_reconcile)

    rep = sub.add_parser("replay", help="send recorded deliveries again")
    rep.add_argument("--store", required=True, help="SQLite file your handler writes")
    rep.add_argument("--url", required=True, help="where to send them")
    rep.add_argument("--reference", action="append", help="repeatable; default is all")
    rep.add_argument("--secret", default=None,
                     help="re-sign with this secret (default: $%s)" % SECRET_ENV)
    rep.add_argument("--dry-run", action="store_true", help="show what would be sent")
    rep.set_defaults(func=_cmd_replay)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except (ValueError, OSError) as exc:
        print("paystack-webhook: %s" % exc, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
