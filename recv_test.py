#!/usr/bin/env python3
"""Receive-side test (Verdikta #355, Ref: KB-2410-09): wallet B issues a BOLT-11 invoice with `wavecli recv --offchain`,
wallet A pays it with `wavecli send`, and we time it and read both sides' fee/balance/activity.

  recv_test.py AMOUNT_SAT [--go]     (dry run without --go: B's invoice + A's quote only)

Both wallets are ours (A = data/, rpc 10029; B = data_b/, rpc 10039). AMOUNT_SAT must be 1000..5000.
Invoices/preimages go to the private log only; results/recv_results.jsonl keeps short prefixes.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone

WAVECLI = os.environ.get("WAVECLI", "wavecli")
A = ["--network=mainnet", "--datadir=" + os.environ.get("WAVE_DATADIR", "./data"), "--rpcserver=localhost:10029"]
B = ["--network=mainnet", "--datadir=" + os.environ.get("WAVE_DATADIR_B", "./data_b"), "--rpcserver=localhost:10039"]
HERE = os.path.dirname(os.path.abspath(__file__))
PRIV = os.path.join(os.environ.get("PRIVATE_DIR", "./private"), "recv_private.jsonl")
PUB = os.path.join(HERE, "recv_results.jsonl")


def w(side, *args, timeout=400):
    p = subprocess.run([WAVECLI, *side, "--json", *args], capture_output=True, text=True, timeout=timeout)
    try:
        return p.returncode, json.loads(p.stdout or "{}"), p.stderr[-500:]
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout[-500:]}, p.stderr[-500:]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main():
    amt = int(sys.argv[1])
    go = "--go" in sys.argv
    if not 1000 <= amt <= 5000:
        sys.exit("amount must be 1000..5000 sats")
    rec = {"ts": now(), "amount_sat": amt}
    _, bal_a0, _ = w(A, "balance")
    _, bal_b0, _ = w(B, "balance")
    rc, inv, err = w(B, "recv", "--offchain", "--amt", str(amt), "--memo", "field test receive")
    if rc != 0 or not inv.get("invoice"):
        rec["result"] = "B recv failed rc=%s %s %s" % (rc, json.dumps(inv)[:300], err[-200:])
        print(json.dumps(rec)); open(PUB, "a").write(json.dumps(rec) + "\n"); return
    invoice = inv["invoice"]
    rc, q, err = w(A, "send", invoice, "--offchain", "--dry-run")
    pv = q.get("preview") or {}
    rec.update(quote_rail=pv.get("rail"), quote_fee_sat=pv.get("expected_fee_sat"), quote_outflow_sat=pv.get("expected_total_outflow_sat"))
    if not go:
        rec["result"] = "DRY RUN"
        print(json.dumps(rec)); return
    t0 = time.monotonic()
    rc, res, err = w(A, "send", invoice, "--offchain", "--force", "--max-fee", "30", "--wait-timeout", "5m")
    rec["ms_send"] = round((time.monotonic() - t0) * 1000)
    rec["send_rc"] = rc
    pre = res.get("preimage") or (res.get("entry") or {}).get("preimage")
    # wait for B to see it
    seen = None
    for _ in range(60):
        _, bb, _ = w(B, "balance")
        if int(bb.get("confirmed_sat") or 0) + int(bb.get("pending_in_sat") or 0) > int(bal_b0.get("confirmed_sat") or 0) + int(bal_b0.get("pending_in_sat") or 0):
            seen = bb
            break
        time.sleep(5)
    rec["ms_until_b_sees"] = round((time.monotonic() - t0) * 1000) if seen else None
    _, bal_a1, _ = w(A, "balance")
    rec.update(a_before=bal_a0, a_after=bal_a1, b_before=bal_b0, b_after=seen or w(B, "balance")[1],
               preimage=(pre[:10] + "...") if pre else None, result="paid" if rc == 0 else "send failed: %s" % (json.dumps(res)[:300] + err[-200:]))
    os.makedirs(os.path.dirname(PRIV), exist_ok=True)
    open(PRIV, "a").write(json.dumps({**rec, "invoice": invoice, "send_json": res}) + "\n")
    open(PUB, "a").write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
