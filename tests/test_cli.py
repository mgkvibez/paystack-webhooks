import json

from paystack_webhooks.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main
from paystack_webhooks.storage import SQLiteStore


def _db(tmp_path, *references):
    path = str(tmp_path / "d.db")
    store = SQLiteStore(path)
    for i, reference in enumerate(references):
        store.accept("k%d" % i,
                     body=json.dumps({"event": "charge.success",
                                      "data": {"reference": reference, "amount": 50000,
                                               "currency": "NGN"}}).encode(),
                     reference=reference)
    store.close()
    return path


def _ledger(tmp_path, entries):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(entries))
    return str(path)


def test_version_prints_package_version(capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("paystack-webhook ")


def test_no_command_is_a_usage_error():
    assert main([]) == EXIT_USAGE


def test_missing_store_is_a_usage_error(tmp_path):
    ledger = _ledger(tmp_path, [])
    missing = str(tmp_path / "nope.db")
    assert main(["reconcile", "--store", missing, "--ledger", ledger]) == EXIT_USAGE


def test_clean_reconciliation_exits_zero(tmp_path, capsys):
    db = _db(tmp_path, "T1")
    ledger = _ledger(tmp_path, [{"reference": "T1", "amount": 50000,
                                 "currency": "NGN", "status": "success"}])
    assert main(["reconcile", "--store", db, "--ledger", ledger]) == EXIT_OK
    assert "no discrepancies" in capsys.readouterr().out


def test_findings_exit_one_and_are_printed(tmp_path, capsys):
    db = _db(tmp_path, "T1")
    ledger = _ledger(tmp_path, [{"reference": "T2", "amount": 1, "currency": "NGN",
                                 "status": "success"}])
    assert main(["reconcile", "--store", db, "--ledger", ledger]) == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "paid_no_delivery" in out and "delivery_no_ledger" in out


def test_json_output_is_machine_readable(tmp_path, capsys):
    db = _db(tmp_path, "T1")
    ledger = _ledger(tmp_path, [{"reference": "T2", "amount": 1, "currency": "NGN",
                                 "status": "success"}])
    assert main(["reconcile", "--store", db, "--ledger", ledger, "--json"]) == EXIT_FINDINGS
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence"]["deliveries"] == 1
    assert {f["kind"] for f in payload["findings"]} == {"paid_no_delivery", "delivery_no_ledger"}


def test_replay_dry_run_sends_nothing(tmp_path, capsys):
    db = _db(tmp_path, "T1")
    args = ["replay", "--store", db, "--url", "http://127.0.0.1:9/never", "--dry-run"]
    assert main(args) == EXIT_OK
    assert "would replay T1" in capsys.readouterr().out


def test_replay_unknown_reference_is_a_usage_error(tmp_path):
    db = _db(tmp_path, "T1")
    assert main(["replay", "--store", db, "--url", "http://127.0.0.1:9/x",
                 "--reference", "ghost", "--dry-run"]) == EXIT_USAGE


def test_unreadable_ledger_is_a_usage_error(tmp_path):
    db = _db(tmp_path, "T1")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["reconcile", "--store", db, "--ledger", str(bad)]) == EXIT_USAGE
