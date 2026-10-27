#!/usr/bin/env python3
"""x402 side of the field test (Verdikta #355, Ref: KB-2410-09): pay the SAME agentpaywire search endpoint with USDC on Base
(x402 v2, scheme exact, EIP-3009 TransferWithAuthorization signed by our wallet; the seller's facilitator pays gas).

  x402_run.py probe           read the 402 and print the x402 terms (pays nothing)
  x402_run.py run N [--go]    N paid calls (default dry run)

Safety: host fixed; network must be eip155:8453, asset must be Base USDC, amount <= 20000 (0.02 USDC) per call, at most 10
calls per run; the EIP-712 domain comes from our own constants, not from the seller. Key derived in-process, never printed.
"""
import base64, csv, json, os, secrets, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from eth_account import Account
from eth_account.messages import encode_typed_data

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://api.agentpaywire.com/v1/search?q=wavelength"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
FROM = os.environ.get("PAYER_ADDRESS", "0x2481E29895b43e87e547a50fB0BB5aa1E70585EB")
CAP, MAX_CALLS = 20_000, 10
UA = "swiftbotlab-fieldtest/1.0"
PUB_JSONL, PUB_CSV = os.path.join(HERE, "x402_results.jsonl"), os.path.join(HERE, "x402_results.csv")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def http(headers=None):
    h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(urllib.request.Request(URL, headers=h), timeout=60)
        code, hdrs, body = r.status, r.headers, r.read(200_000)
    except urllib.error.HTTPError as e:
        code, hdrs, body = e.code, e.headers, e.read(200_000)
    return code, hdrs, body, round((time.monotonic() - t0) * 1000)


def terms(hdrs, body):
    pr = hdrs.get("PAYMENT-REQUIRED")
    d = json.loads(base64.b64decode(pr + "=" * (-len(pr) % 4))) if pr else json.loads(body)
    acc = [a for a in d.get("accepts", []) if a.get("scheme") == "exact" and a.get("network") == "eip155:8453"
           and a.get("asset", "").lower() == USDC.lower()]
    if not acc:
        raise SystemExit("no Base USDC exact option")
    a = acc[0]
    if int(a["amount"]) > CAP:
        raise SystemExit("price over cap: %s" % a["amount"])
    return d, a


def account():
    env = dict(l.strip().split("=", 1) for l in open(os.environ["WALLET_ENV_FILE"]) if "=" in l)
    Account.enable_unaudited_hdwallet_features()
    acct = Account.from_mnemonic(env["EVM_MNEMONIC"], account_path=env["EVM_PATH"])
    if acct.address.lower() != FROM.lower():
        raise SystemExit("derived address mismatch")
    return acct


def sign(acct, a):
    t = int(time.time())
    au = {"from": FROM, "to": a["payTo"], "value": str(int(a["amount"])), "validAfter": str(t - 60),
          "validBefore": str(t + int(a.get("maxTimeoutSeconds", 60))), "nonce": "0x" + secrets.token_hex(32)}
    td = {"types": {"EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                                     {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                    "TransferWithAuthorization": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"},
                                                  {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
                                                  {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}]},
          "primaryType": "TransferWithAuthorization",
          "domain": {"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": USDC},
          "message": {"from": FROM, "to": a["payTo"], "value": int(au["value"]), "validAfter": int(au["validAfter"]),
                      "validBefore": int(au["validBefore"]), "nonce": bytes.fromhex(au["nonce"][2:])}}
    sig = "0x" + bytes(acct.sign_message(encode_typed_data(full_message=td)).signature).hex()
    return au, sig


def log(rec):
    with open(PUB_JSONL, "a") as f:
        f.write(json.dumps(rec) + "\n")
    new = not os.path.exists(PUB_CSV)
    cols = ["ts", "call", "http_402", "ms_402", "amount_usdc", "ms_sign", "http_paid", "ms_paid", "ms_total", "tx", "result"]
    with open(PUB_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(cols)
        w.writerow([rec.get(c, "") for c in cols])


def main():
    a = sys.argv[1:]
    go = "--go" in a
    a = [x for x in a if x != "--go"]
    if not a or a[0] == "probe":
        code, hdrs, body, ms = http()
        d, t = terms(hdrs, body)
        print(code, ms, "ms", json.dumps(t))
        return
    n = min(int(a[1]) if len(a) > 1 else 1, MAX_CALLS)
    acct = account() if go else None
    for i in range(n):
        t0 = time.monotonic()
        code, hdrs, body, ms402 = http()
        d, t = terms(hdrs, body)
        rec = {"ts": now(), "call": i + 1, "http_402": code, "ms_402": ms402, "amount_usdc": int(t["amount"]) / 1e6, "pay_to": t["payTo"]}
        if not go:
            print(json.dumps({**rec, "result": "DRY RUN"}))
            continue
        ts = time.monotonic()
        au, sig = sign(acct, t)
        pp = {"x402Version": 2, "accepted": t, "payload": {"authorization": au, "signature": sig}}
        if d.get("resource"):
            pp["resource"] = d["resource"]
        hdr = base64.b64encode(json.dumps(pp, separators=(",", ":")).encode()).decode()
        ms_sign = round((time.monotonic() - ts) * 1000)
        code2, hdrs2, body2, ms_paid = http({"PAYMENT-SIGNATURE": hdr, "X-PAYMENT": hdr})
        resp = hdrs2.get("PAYMENT-RESPONSE") or hdrs2.get("X-PAYMENT-RESPONSE")
        tx = None
        if resp:
            try:
                tx = json.loads(base64.b64decode(resp + "=" * (-len(resp) % 4))).get("transaction")
            except Exception:
                tx = None
        rec.update(ms_sign=ms_sign, http_paid=code2, ms_paid=ms_paid, ms_total=round((time.monotonic() - t0) * 1000), tx=tx,
                   result=("ok %d bytes" % len(body2)) if code2 == 200 else body2[:240].decode("utf-8", "replace"))
        log(rec)
        print(json.dumps(rec))
        time.sleep(2)


if __name__ == "__main__":
    main()
