#!/usr/bin/env python3
"""Headless L402 field test driver (Verdikta #355, Ref: KB-2410-09). Pays real third-party L402 endpoints from our Wavelength
mainnet wallet by shelling out to `wavecli --json`, and logs every step.

  l402_run.py probe                 GET each endpoint, parse the 402 challenge, print price (pays nothing)
  l402_run.py run [--go]            the planned runs (dry run without --go: shows what would be paid)
  l402_run.py one <name> [--go]     a single paid call to one endpoint

Safety: hosts are fixed in code; every invoice is decoded locally and must be <= PER_CALL_CAP sats; the whole session stops
at SESSION_CAP sats (amounts + fees). Macaroons, invoices and preimages are written to the private log only; the public
log (results.jsonl / results.csv) keeps 10-char prefixes.
"""
import csv, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WAVECLI = os.environ.get("WAVECLI", "wavecli")
DATADIR = os.environ.get("WAVE_DATADIR", "./data")
PRIV = os.path.join(os.environ.get("PRIVATE_DIR", "./private"), "l402_private.jsonl")
PUB_JSONL, PUB_CSV = os.path.join(HERE, "results.jsonl"), os.path.join(HERE, "results.csv")
UA = "swiftbotlab-fieldtest/1.0"
PER_CALL_CAP, SESSION_CAP = 150, 1000
ENDPOINTS = {
    "ipgeo": "https://api.lightningenable.com/l402/proxy/ip-geolocation-813d/lookup?ip=8.8.8.8",
    "fx": "https://api.lightningenable.com/l402/proxy/currency-exchange-9b9c/rates",
    "apw": "https://api.agentpaywire.com/v1/search?q=wavelength",
}
ALLOWED_HOSTS = {"api.lightningenable.com", "api.agentpaywire.com"}
spent = 0


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def short(s, n=10):
    return (s[:n] + "...") if s else s


def http(url, auth=None, timeout=30):
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise SystemExit("host not allowed: %s" % host)
    h = {"User-Agent": UA, "Accept": "application/json"}
    if auth:
        h["Authorization"] = auth
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
        code, hdrs, body = r.status, r.headers, r.read(200_000)
    except urllib.error.HTTPError as e:
        code, hdrs, body = e.code, e.headers, e.read(200_000)
    return code, hdrs, body, round((time.monotonic() - t0) * 1000)


def parse_l402(hdrs):
    for v in hdrs.get_all("WWW-Authenticate") or []:
        m = re.match(r'\s*(L402|LSAT)\s+macaroon="([^"]+)",\s*invoice="([^"]+)"', v)
        if m:
            return m.group(2), m.group(3)
    return None, None


def invoice_sats(inv):
    m = re.match(r"^lnbc(\d+)([munp]?)1", inv)
    if not m:
        raise SystemExit("cannot decode invoice amount")
    n, mult = int(m.group(1)), m.group(2)
    msat = {"m": n * 100_000_000, "u": n * 100_000, "n": n * 100, "p": n // 10, "": n * 100_000_000_000}[mult]
    return msat / 1000


def wavecli(*args, timeout=360):
    p = subprocess.run([WAVECLI, "--network=mainnet", "--datadir=" + DATADIR, "--json", *args],
                       capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip()
    try:
        return p.returncode, json.loads(out) if out else {}, p.stderr.strip()[-600:]
    except json.JSONDecodeError:
        return p.returncode, {"raw": out[-600:]}, p.stderr.strip()[-600:]


def log(pub, priv):
    os.makedirs(os.path.dirname(PRIV), exist_ok=True)
    with open(PRIV, "a") as f:
        f.write(json.dumps({**pub, **priv}) + "\n")
    with open(PUB_JSONL, "a") as f:
        f.write(json.dumps(pub) + "\n")
    new = not os.path.exists(PUB_CSV)
    with open(PUB_CSV, "a", newline="") as f:
        w = csv.writer(f)
        cols = ["ts", "endpoint", "step", "http", "price_sat", "fee_sat", "rail", "credit_before", "credit_after", "confirmed_before", "confirmed_after", "ms_402", "ms_pay", "ms_200", "ms_total", "result"]
        if new:
            w.writerow(cols)
        w.writerow([pub.get(c, "") for c in cols])


def paid_call(name, go, reuse=0):
    """402 -> pay -> 200, then `reuse` extra calls with the same token."""
    global spent
    url = ENDPOINTS[name]
    t_start = time.monotonic()
    code, hdrs, body, ms402 = http(url)
    mac, inv = parse_l402(hdrs)
    rec = {"ts": now(), "endpoint": name, "url": url, "step": "challenge", "http": code, "ms_402": ms402}
    if code != 402 or not inv:
        rec["result"] = "no L402 challenge: %s" % body[:200].decode("utf-8", "replace")
        log(rec, {})
        return rec
    price = invoice_sats(inv)
    rec.update(price_sat=price, macaroon=short(mac), invoice=short(inv, 14))
    if price > PER_CALL_CAP or spent + price > SESSION_CAP:
        rec["result"] = "refused: over cap (price %s, spent %s)" % (price, spent)
        log(rec, {})
        return rec
    if not go:
        rec["result"] = "DRY RUN (would pay %s sats)" % price
        print(json.dumps(rec))
        return rec
    b0 = wavecli("balance")[1]
    t_pay = time.monotonic()
    rc, res, err = wavecli("send", inv, "--offchain", "--force", "--max-fee", "20", "--max-credit", "1500", "--max-credit-topup", "1000",
                           "--wait-timeout", "5m")
    ms_pay = round((time.monotonic() - t_pay) * 1000)
    pre = None
    for k in ("preimage", "payment_preimage", "preimage_hex"):
        pre = pre or res.get(k) or (res.get("entry") or {}).get(k) or ((res.get("entry") or {}).get("progress") or {}).get(k)
    fee = res.get("fee_sat") if "fee_sat" in res else (res.get("entry") or {}).get("fee_sat")
    spent += price + float(fee or 0)
    rec["rail"] = res.get("settlement") or res.get("rail") or (res.get("entry") or {}).get("rail")
    b1 = wavecli("balance")[1]
    rec["credit_before"], rec["credit_after"] = b0.get("credit_available_sat"), b1.get("credit_available_sat")
    rec["confirmed_before"], rec["confirmed_after"] = b0.get("confirmed_sat"), b1.get("confirmed_sat")
    rec.update(step="pay", ms_pay=ms_pay, fee_sat=fee, result="paid" if (rc == 0 and pre) else "pay failed rc=%s %s" % (rc, err[-300:]))
    priv = {"macaroon_full": mac, "invoice_full": inv, "preimage": pre, "send_json": res}
    if not pre:
        log(rec, priv)
        return rec
    auth = "L402 %s:%s" % (mac, pre)
    code2, _, body2, ms200 = http(url, auth=auth)
    rec2 = {**rec, "ts": now(), "step": "retry", "http": code2, "ms_200": ms200, "ms_total": round((time.monotonic() - t_start) * 1000),
            "preimage": short(pre), "result": "ok %d bytes" % len(body2) if code2 == 200 else "retry failed: %s" % body2[:200].decode("utf-8", "replace")}
    log(rec2, {**priv, "body_head": body2[:400].decode("utf-8", "replace")})
    print(json.dumps({k: rec2.get(k) for k in ("endpoint", "http", "price_sat", "fee_sat", "ms_pay", "ms_total", "result")}))
    for i in range(reuse):
        code3, _, body3, ms3 = http(url, auth=auth)
        r3 = {"ts": now(), "endpoint": name, "step": "token_reuse_%d" % (i + 1), "http": code3, "ms_200": ms3, "price_sat": 0,
              "result": "ok %d bytes" % len(body3) if code3 == 200 else "%d: %s" % (code3, body3[:160].decode("utf-8", "replace"))}
        log(r3, {})
        print(json.dumps(r3))
    return rec2


def main():
    a = sys.argv[1:]
    go = "--go" in a
    a = [x for x in a if x != "--go"]
    if not a or a[0] == "probe":
        for n, u in ENDPOINTS.items():
            code, hdrs, body, ms = http(u)
            mac, inv = parse_l402(hdrs)
            print(n, code, ms, "ms", invoice_sats(inv) if inv else None, "sats")
        return
    if a[0] == "one":
        paid_call(a[1], go, reuse=int(a[2]) if len(a) > 2 else 0)
        return
    if a[0] == "run":
        # lightning-enable: 5 paid calls each, one token-reuse check on the first; agentpaywire: one 100-sat purchase = 100 credits, 4 reuses
        for n in ("ipgeo", "fx"):
            for i in range(5):
                paid_call(n, go, reuse=1 if i == 0 else 0)
                time.sleep(2)
        paid_call("apw", go, reuse=4)
        print("spent (amount + reported fees):", spent)


if __name__ == "__main__":
    main()
