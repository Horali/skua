"""appoffer Ã¢â‚¬â€ enumerate the Play subscription offers of ANY installed app.

Generalises the per-app work (claude_probe/claude_skus, gpt_skus) into one command:

  1. pull every split of the package, parse dex string tables for Play product-id
     shaped identifiers, and keep the plausible ones
  2. query those candidates through Play Billing *from inside the app's process*
     (Play only returns products for the calling package) using the toolkit's own
     BillingClient module
  3. report every pricing phase, flagging zero-priced and discounted first phases

This works for any app that sells subscriptions through Play. It cannot work for
web/Stripe-only products, account entitlements behind verification, or storefronts
the account's payment profile is not in.

Read-only: queries product details, never launches a purchase.

Usage:
    python appoffer.py --package com.perplexity.ai
    python appoffer.py --package com.microsoft.copilot --max 60
    python appoffer.py --package com.openai.chatgpt --extra oai.chatgpt.go
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import frida

import ultra0

FRIDA_PORT = 27042
WORK = Path("tmpdb/appoffer")

# A Play product id is lowercase, dotted/underscored, short, and usually carries a
# plan word. Anything class-shaped (uppercase, path, framework prefix) is dropped.
RE_ID = re.compile(r"^[a-z][a-z0-9_]*(?:[._][a-z0-9]+){0,5}$")
PLAN_WORDS = ("month", "annual", "year", "week", "pro", "max", "plus", "premium",
              "sub", "tier", "plan", "credit", "trial")
NOISE = ("android", "google", "gms", "kotlin", "okhttp", "retrofit", "firebase",
         "crashlytics", "androidx", "material", "kotlinx", "com.google", "org.jetbrains",
         "exoplayer", "protobuf", "gson", "jackson", "reactivex", "squareup")


def adb(*args: str, timeout: int = 180) -> str:
    return subprocess.run([ultra0.ADB, "-s", ultra0.SERIAL, *args],
                          capture_output=True, text=True, timeout=timeout).stdout


def uleb128(buf: bytes, off: int):
    result = shift = 0
    while True:
        b = buf[off]
        off += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, off
        shift += 7


def dex_strings(blob: bytes) -> list[str]:
    if blob[:4] != b"dex\n":
        return []
    size, off = struct.unpack_from("<II", blob, 0x38)
    out = []
    for i in range(size):
        try:
            sidx = struct.unpack_from("<I", blob, off + i * 4)[0]
            _, so = uleb128(blob, sidx)
            out.append(blob[so:blob.index(b"\x00", so)].decode("utf-8", "replace"))
        except Exception:
            continue
    return out


def pull_splits(pkg: str) -> list[Path]:
    work = WORK / pkg.replace(".", "_")
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for line in adb("shell", f"pm path {pkg}").splitlines():
        p = line.strip().replace("package:", "")
        if not p:
            continue
        local = work / Path(p).name
        if not local.exists():
            adb("pull", p, str(local))
        if local.exists():
            out.append(local)
    return out


def vendor_tokens(pkg: str) -> list[str]:
    """Id segments that real Play products tend to carry, derived from the package.

    Segment-based only: 3-letter prefixes matched noise like 'cla' inside
    'classname' and poisoned the ranking.
    """
    parts = [p for p in pkg.split(".") if p not in ("com", "org", "net", "io", "app", "android")]
    toks = {p for p in parts if len(p) >= 3}
    if "openai" in pkg:
        toks.add("oai")
    return sorted(toks)


def score_id(low: str, vendor: list[str]) -> int:
    """Rank a candidate. Real ids are dotted, contain a plan segment, and usually
    carry the vendor's name as a segment. Bare words score zero and are dropped."""
    if "." not in low:
        return 0
    segs = re.split(r"[._]", low)
    if not segs:
        return 0
    score = 0
    if any(seg in PLAN_WORDS for seg in segs):
        score += 3
    if any(seg in vendor for seg in segs):
        score += 3
    if len(segs) >= 3:
        score += 1
    if len(segs) > 5:
        score -= 2
    return score


def discover_ids(apks: list[Path], max_ids: int, pkg: str) -> list[str]:
    vendor = vendor_tokens(pkg)
    cands: dict[str, int] = {}
    for apk in apks:
        try:
            z = zipfile.ZipFile(apk)
        except Exception:
            continue
        for name in z.namelist():
            if not name.endswith(".dex"):
                continue
            try:
                strings = dex_strings(z.read(name))
            except Exception:
                continue
            for s in strings:
                low = s.lower()
                if not RE_ID.match(low) or len(low) > 60:
                    continue
                if any(n in low for n in NOISE):
                    continue
                sc = score_id(low, vendor)
                if sc <= 0:
                    continue
                cands[low] = max(cands.get(low, 0), sc)  # max, not sum: frequent noise would dominate
    ranked = sorted(cands.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ranked[:max_ids]]


def query_in_process(pkg: str, candidates: list[str], timeout: int = 120) -> tuple[list[dict], list[str]]:
    out = adb("shell", f"pidof {pkg}").split()
    if not out:
        adb("shell", f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        time.sleep(5)
        out = adb("shell", f"pidof {pkg}").split()
    if not out:
        return [], [f"process for {pkg} not running"]
    pid = int(out[0])

    adb("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")
    js = (Path(__file__).parent / "assets" / "frida" / "sku_probe_iso.js").read_text("utf-8")
    js = js.replace("var PRODUCTS = __PRODUCTS__;",
                    "var PRODUCTS = " + json.dumps(candidates) + ";", 1)

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    done = threading.Event()
    offers: list[dict] = []
    errors: list[str] = []

    def on_msg(m, d):
        p = m.get("payload") or {}
        ev = p.get("ev")
        if ev == "offer":
            offers.append(p)
            col = (p.get("phases") or [{}])[0].get("formatted", "")
            print(f"  offer {p['product']:44s} id={str(p.get('id')):18s} {col}")
        elif ev == "done":
            done.set()
        elif ev in ("boot_err", "query_err", "parse_err"):
            errors.append(f"{ev}: {p.get('m')}")
            print(f"  [{ev}] {str(p.get('m'))[:120]}")

    script = sess.create_script(js)
    script.on("message", on_msg)
    script.load()
    done.wait(timeout=max(60, len(candidates) // 20 * 4 + 20))
    time.sleep(1)
    try:
        sess.detach()
    except Exception:
        pass
    return offers, errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Enumerate any installed app's Play offers (read-only)")
    ap.add_argument("--package", required=True)
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--extra", nargs="*", default=[], help="extra candidate product ids")
    ap.add_argument("--max", type=int, default=40, help="max discovered ids to query")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial
    ultra0.ensure_root()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()

    if not adb("shell", f"pm path {args.package}").strip():
        raise SystemExit(f"{args.package} is not installed")

    apks = pull_splits(args.package)
    print(f"{args.package}: {len(apks)} split(s)")
    ids = discover_ids(apks, args.max, args.package)
    candidates = sorted(set(ids) | set(args.extra))
    print(f"discovered {len(ids)} candidate id(s); querying {len(candidates)}\n")
    for c in candidates:
        print(f"  ? {c}")
    print()

    offers, errors = query_in_process(args.package, candidates)
    print(f"\n=== {len(offers)} offer(s), {len(errors)} error(s) ===")
    by_product: dict[str, list[dict]] = {}
    for o in offers:
        by_product.setdefault(o["product"], []).append(o)
    zero, discounted = [], []
    for pid in sorted(by_product):
        print(f"\n{pid}")
        for o in by_product[pid]:
            phases = o.get("phases") or []
            desc = "  ->  ".join(f"{p.get('formatted')}/{p.get('period')}" for p in phases)
            print(f"  offer={str(o.get('id')):20s} phases={len(phases)}  {desc}")
            first = str((phases[0] if phases else {}).get("micros"))
            if first in ("0", "0.0"):
                zero.append(o)
            elif len(phases) > 1:
                discounted.append(o)

    print(f"\nzero-priced: {len(zero)} | discounted intro: {len(discounted)}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"appoffer-{args.package.replace('.', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "package": args.package,
        "candidates": candidates,
        "offers": offers,
        "errors": errors,
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



