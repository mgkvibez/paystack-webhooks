#!/usr/bin/env bash
# Release gate. Every check here has caught a real problem at some point, or it
# would not be here. Run it before every tag.
set -uo pipefail
cd "$(dirname "$0")/.."

fail() { echo "GATE FAILED: $1"; exit 1; }

echo "== check 1/7: lint"
python3 -m ruff check . || fail "ruff"

echo "== check 2/7: tests"
python3 -m pytest -q || fail "pytest"

echo "== check 3/7: the core imports no web framework"
out=$(python3 -c "import sys, paystack_webhooks; print(','.join(m for m in ('fastapi','flask','django','starlette') if m in sys.modules))")
[ -z "$out" ] || fail "core pulled in $out"

echo "== check 4/7: version consistency (pyproject vs module)"
python3 - <<'PY' || fail "version mismatch"
import pathlib, sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
meta = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"]
mod = __import__("paystack_webhooks").__version__
print("version", meta, "vs module", mod)
sys.exit(0 if meta == mod else 1)
PY

echo "== check 5/7: README install name matches the distribution name"
pyname=$(grep -m1 -E '^name[[:space:]]*=' pyproject.toml | sed -E 's/.*"(.*)".*/\1/')
docname=$(grep -m1 -oE 'pipx install [A-Za-z0-9._-]+' README.md | awk '{print $3}')
echo "   pyproject=$pyname README=$docname"
[ "$pyname" = "$docname" ] || fail "README tells people to install '$docname' but the package is '$pyname'"

echo "== check 6/7: the built wheel actually contains the package"
python3 -c "import build" 2>/dev/null || fail "wheel check needs the 'build' package: pip install build"
tmpd=$(mktemp -d)
python3 -m build --wheel --outdir "$tmpd" >"$tmpd/build.log" 2>&1 || { cat "$tmpd/build.log"; fail "wheel build"; }
python3 - "$tmpd" <<'PY'
import glob, shutil, sys, zipfile
wheels = glob.glob(sys.argv[1] + "/*.whl")
if not wheels:
    sys.exit("no wheel was produced")
inside = [n for n in zipfile.ZipFile(wheels[0]).namelist()
          if n.startswith("paystack_webhooks/") and n.endswith(".py")]
shutil.rmtree(sys.argv[1], ignore_errors=True)
if len(inside) < 5:
    sys.exit("wheel has %d module file(s); the package is missing" % len(inside))
PY
[ $? -eq 0 ] || fail "wheel is missing the package; an editable install hides this"
echo "wheel contains the package"

echo "== check 7/7: the CLI honours its documented exit codes"
tmp=$(mktemp -d)
python3 - "$tmp" <<'CLI' || fail "cli contract"
import json, sys, pathlib
from paystack_webhooks.cli import main
from paystack_webhooks.storage import SQLiteStore

tmp = pathlib.Path(sys.argv[1])
db = str(tmp / "d.db")
store = SQLiteStore(db)
store.accept("k1", body=json.dumps({"event": "charge.success",
             "data": {"reference": "T1", "amount": 50000, "currency": "NGN"}}).encode(),
             reference="T1")
store.close()

clean = str(tmp / "clean.json")
pathlib.Path(clean).write_text(json.dumps([{"reference": "T1", "amount": 50000,
                                            "currency": "NGN", "status": "success"}]))
dirty = str(tmp / "dirty.json")
pathlib.Path(dirty).write_text(json.dumps([{"reference": "T2", "amount": 1,
                                            "currency": "NGN", "status": "success"}]))

assert main(["reconcile", "--store", db, "--ledger", clean]) == 0, "clean must exit 0"
assert main(["reconcile", "--store", db, "--ledger", dirty]) == 1, "findings must exit 1"
assert main(["reconcile", "--store", str(tmp / "missing.db"), "--ledger", clean]) == 2, "missing store must exit 2"
assert main([]) == 2, "no command must exit 2"
assert main(["replay", "--store", db, "--url", "http://127.0.0.1:9/never", "--dry-run"]) == 0, "dry run must exit 0"
print("CLI contract holds: 0 clean, 1 findings, 2 usage")
CLI
python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$tmp"

echo
echo "ALL CHECKS PASSED"
