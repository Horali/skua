"""offerwatch â€” enumerate every Google Play Billing offer for Google AI / One SKUs.

Read-only. No checkout is opened and no offer token is used for a purchase; the
tool answers one question: *which products does Play return, and do any of them
carry a zero-priced introductory phase right now?*

Why this exists: the promotional offers live on product IDs the Google One UI
never queries (g1.2tb.ai.subs_variant, g1.play.*), and Google renames them. A
hardcoded SKU list goes stale; this rediscovers instead.

Usage:
    python offerwatch.py                       # discover + query + report
    python offerwatch.py --extra g1.foo.bar    # add candidate SKUs
    python offerwatch.py --diff reports/last.json   # show what changed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import frida

import ultra0

PKG = "com.google.android.apps.subscriptions.red"
DB_REMOTE = f"/data/data/{PKG}/databases/StoragePlansDataCache.db"
FRIDA_PORT = 27042

# Seed candidates. Discovery adds anything the device itself mentions.
SEED_SKUS = [
    "g1.2tb.ai.subs_variant",
    "g1.play.20tb.ai",
    "g1.20tb.ai",
    "g1.play.30tb",
    "g1.30tb.ai",
    "g1.ultra",
    "g1.play.ultra",
    "g1.ai.ultra",
    "g1.play.ai.ultra",
    "g1.20tb.subs_variant",
    "g1.30tb.subs_variant",
    "g1.play.2tb.ai.subs_variant",
    "g1.2tb.ai",
    "g1.2tb",
    "g1.play.ai.pro",
    "g1.play.20tb",
    "g1.play.2tb.ai",
    "g1.play.2tb.ai.subs_variant",
    "g1.ai.pro",
    "g1.30tb",
    "g1.20tb",
    "g1.2tb.ai.12months",
    # Confirmed by query on 2026-11-23 (found via the UI walk, missed by ROOTS).
    "g1.5tb",
    "g1.10tb",
    "g1.100gb",
]

# Roots used to generate extra candidates when the seed misses.
ROOTS = ["g1", "g1.play", "g1.2tb", "g1.2tb.ai", "g1.play.2tb", "g1.play.2tb.ai", "g1.20tb", "g1.30tb", "g1.20tb.ai", "g1.30tb.ai", "g1.ultra", "g1.play.ultra"]
LEAVES = ["", ".subs_variant", ".subs", ".ai", ".ai.subs_variant", ".pro", ".play"]

# Campaign SKUs. Google's promo naming is <core>.<N>months_ip_<P>p.acq and the
# offer id is "introprice" (not "eft-*"). These carry the Black Friday style
# discounts and are invisible to the app UI entirely — 2026-11-23 sweep returned
# 17 of them, e.g. g1.2tb.ai.1month_ip_95p.acq = Rp 15.000 then Rp 309.000.
CAMPAIGN_CORES = [
    "g1.100gb", "g1.2tb", "g1.2tb.ai", "g1.2tb.subs_variant",
    "g1.2tb.ai.subs_variant", "g1.20tb", "g1.10tb", "g1.play.2tb.ai",
]
CAMPAIGN_DURATIONS = ["1month", "2months", "3months", "4months", "6months", "12months"]
CAMPAIGN_DISCOUNTS = ["50p", "60p", "70p", "75p", "80p", "85p", "90p", "95p"]

# Second naming family, found 2026-11-23 from a third-party report: the duration is part
# of the PRODUCT id and the offer is bare, e.g.
#   g1.2tb.ai.12months_eft -> offer "eft-12months" (Free/P1Y)   [direct purchase]
#   g1.2tb.6months_eft     -> offer "freetrial"     (Free/P26W2D)
# These are the "ready direct free" products: they do not need the --stack path that
# g1.2tb.ai.subs_variant requires. Missing them made an earlier sweep look exhaustive
# when it was not.
DIRECT_EFT_CORES = [
    "g1.2tb", "g1.2tb.ai", "g1.play.2tb.ai", "g1.5tb", "g1.10tb", "g1.20tb",
    "g1.100gb", "g1.ai.pro", "g1.play.ai.pro", "g1.2tb.ai.pro",
]
DIRECT_EFT_DURATIONS = ["1month", "2months", "3months", "4months", "6months",
                        "9months", "12months", "18months", "24months"]

# .v2 product revisions and family-tier guesses.
V2_CORES = ["g1.20tb", "g1.30tb", "g1.2tb", "g1.2tb.ai", "g1.10tb", "g1.5tb",
            "g1.play.20tb", "g1.ai.pro", "g1.play.ai.pro"]
FAMILY_IDS = ["g1.family", "g1.family.2tb", "g1.family.5tb", "g1.family.ai"]


def direct_eft_candidates() -> set[str]:
    out = set()
    for core in DIRECT_EFT_CORES:
        for dur in DIRECT_EFT_DURATIONS:
            out.add(f"{core}.{dur}_eft")
    return out


def revision_candidates() -> set[str]:
    out = set(FAMILY_IDS)
    for core in V2_CORES:
        out.add(f"{core}.v2")
        out.add(f"{core}.family")
    return out


def campaign_candidates() -> set[str]:
    out = set()
    for core in CAMPAIGN_CORES:
        for dur in CAMPAIGN_DURATIONS:
            for disc in CAMPAIGN_DISCOUNTS:
                out.add(f"{core}.{dur}_ip_{disc}.acq")
    return out


def sh(*args, timeout=60):
    return ultra0.sh(*args, timeout=timeout)


def discover_from_device() -> set[str]:
    """Pull Google One's plan cache and scrape every g1.* product id it mentions."""
    found: set[str] = set()
    r = sh("shell", f"ls {DB_REMOTE} 2>/dev/null")
    if r:
        tmp = Path(tempfile.gettempdir()) / "StoragePlansDataCache.db"
        sh("pull", DB_REMOTE, str(tmp), timeout=120)
        if tmp.exists():
            try:
                # The file may be locked/WAL; copy to a scratch name before reading.
                scratch = tmp.with_suffix(".copy.db")
                scratch.write_bytes(tmp.read_bytes())
                con = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
                blob = []
                for (name,) in con.execute(
                        "select name from sqlite_master where type='table'"):
                    try:
                        for row in con.execute(f"select * from {name}"):
                            blob.append(" ".join(str(c) for c in row))
                    except sqlite3.DatabaseError:
                        continue
                con.close()
                found |= set(re.findall(r"g1\.[A-Za-z0-9_.]+", " ".join(blob)))
            except sqlite3.DatabaseError:
                # Fall back to a raw scrape of the file bytes.
                found |= set(re.findall(rb"g1\.[A-Za-z0-9_.]+",
                                        tmp.read_bytes()))
                found = {x.decode() if isinstance(x, bytes) else x for x in found}

    # Shared prefs and any other small text file the app keeps product ids in.
    raw = sh("shell",
             f"grep -rhoE 'g1\\.[A-Za-z0-9_.]+' /data/data/{PKG}/shared_prefs "
             f"/data/data/{PKG}/files 2>/dev/null | sort -u")
    if raw:
        found |= set(x.strip() for x in raw.splitlines() if x.strip().startswith("g1."))
    return {x for x in found if 3 < len(x) < 64}


def generate_candidates(found: set[str]) -> list[str]:
    cands = (set(SEED_SKUS) | found | campaign_candidates()
             | direct_eft_candidates() | revision_candidates())
    for root in ROOTS:
        for leaf in LEAVES:
            cands.add(root + leaf)
    # Anything the device mentioned gets .subs_variant / .play variants too.
    for pid in list(found):
        base = re.sub(r"\.(subs_variant|subs|play)$", "", pid)
        for leaf in LEAVES:
            cands.add(base + leaf)
    out = sorted(c for c in cands if re.fullmatch(r"g1\.[A-Za-z0-9_.]{1,48}", c))
    return out


def ensure_frida_forward(serial: str) -> None:
    sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")


def attach_and_probe(candidates: list[str], ids: dict[str, str], progress: bool = False) -> list[dict]:
    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    pid = 0
    for p in dev.enumerate_processes():
        if "subscriptions.red" in p.name or p.name == "Google One":
            pid = p.pid
            break
    if not pid:
        # Fall back to the engine's launch + ADB pid.
        pid = ultra0.launch_app()
        time.sleep(4)
    if not pid:
        raise SystemExit("Google One process not found (is the app installed and running?)")

    js = (Path(__file__).parent / "assets" / "frida" / "sku_probe.js").read_text("utf-8")
    js = js.replace("var PRODUCTS = __PRODUCTS__;", "var PRODUCTS = " + json.dumps(candidates) + ";", 1)

    sess = dev.attach(pid)
    done = threading.Event()
    offers: list[dict] = []
    products: list[dict] = []
    errors: list[str] = []
    chunks = [0]

    def on_msg(m, data):
        payload = m.get("payload") or {}
        ev = payload.get("ev")
        if ev == "offer":
            offers.append(payload)
        elif ev == "product":
            products.append(payload)
        elif ev == "done":
            done.set()
        elif ev in ("boot_err", "query_err", "parse_err"):
            errors.append(f"{ev}: {payload.get('m')}")
        elif ev == "setup":
            if payload.get("code") != 0:
                errors.append(f"billing setup code {payload.get('code')}")
        elif ev == "pd" and progress:
            # 20 SKUs per chunk; a wide sweep is hundreds of chunks.
            chunks[0] += 1
            n = chunks[0]
            if n % 10 == 0:
                print(f"  .. {n} chunk(s), {min(n * 20, len(candidates))}/{len(candidates)} SKUs, "
                      f"{len(offers)} offer(s)", flush=True)

    script = sess.create_script(js)
    script.on("message", on_msg)
    script.load()
    # Roughly 1s per 20-SKU chunk; scale the deadline with the candidate count.
    budget = max(90, int(len(candidates) / 20) * 4)
    done.wait(timeout=budget)
    time.sleep(1)
    try:
        sess.detach()
    except Exception:
        pass
    return [{"offers": offers, "products": products, "errors": errors, "pid": pid}]


def render(result: dict, candidates: list[str]) -> str:
    lines = []
    offers = result["offers"]
    products = result["products"]
    lines.append(f"queried {len(candidates)} candidate SKU(s), Google One pid {result['pid']}")
    if result["errors"]:
        lines.append("errors: " + "; ".join(result["errors"][:5]))

    by_product: dict[str, list[dict]] = {}
    for o in offers:
        by_product.setdefault(o["product"], []).append(o)

    for pid in sorted(by_product):
        lines.append("")
        lines.append(f"{pid}")
        for o in sorted(by_product[pid], key=lambda x: str(x.get("id"))):
            phases = o.get("phases") or []
            first = phases[0] if phases else {}
            micros = str(first.get("micros"))
            flag = "  <== ZERO PRICE" if micros in ("0", "0.0") else ""
            price = first.get("formatted") or micros
            lines.append(f"    offer id={o.get('id')!s:24s} first={price:>14s} "
                         f"{first.get('period')}  phases={len(phases)}{flag}")
    if not offers:
        lines.append("")
        lines.append("no offers returned for any candidate (account ineligible, or SKUs renamed)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Enumerate Play Billing offers (read-only)")
    ap.add_argument("--serial", default=None, help="ADB serial; default: the MuMu emulator")
    ap.add_argument("--extra", nargs="*", default=[], help="extra SKU candidates")
    ap.add_argument("--extra-file", default=None,
                    help="file of newline-separated extra SKU candidates (for grids too big for argv)")
    ap.add_argument("--progress", action="store_true", help="print sweep progress every 10 chunks")
    ap.add_argument("--out", default="reports", help="report directory")
    ap.add_argument("--no-device-discovery", action="store_true",
                    help="skip pulling the app cache; seed + generation only")
    ap.add_argument("--diff", default=None, help="compare against a previous report json")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial or "127.0.0.1:16384"

    print(f"serial : {ultra0.SERIAL}")
    ultra0.ensure_root()
    ultra0.ensure_frida_client()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()
    ultra0.ensure_network()
    ultra0.launch_app()
    time.sleep(3)
    ensure_frida_forward(ultra0.SERIAL)

    found = set() if args.no_device_discovery else discover_from_device()
    extras = set(args.extra)
    if args.extra_file:
        raw = Path(args.extra_file).read_text(encoding="utf-8")
        extras |= {line.strip() for line in raw.splitlines() if line.strip()}
        print(f"loaded {len(extras)} extra candidate(s) from {args.extra_file}")
    # Explicit extras are already-rendered names: do NOT run them through the
    # variant generator, or a 6k grid becomes 40k candidates.
    given = set(generate_candidates(found))
    given |= {c for c in extras if re.fullmatch(r"g1\.[A-Za-z0-9_.]{1,48}", c)}
    candidates = sorted(given)
    print(f"discovered {len(found)} id(s) on device, {len(candidates)} candidate(s) total")

    result = attach_and_probe(candidates, {"serial": ultra0.SERIAL}, progress=args.progress)[0]
    print()
    print(render(result, candidates))

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = outdir / f"offerwatch-{stamp}.json"
    payload = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "candidates": candidates,
        "device_ids": sorted(found),
        "offers": result["offers"],
        "products": result["products"],
        "errors": result["errors"],
        "zero_price": [o for o in result["offers"]
                       if (o.get("phases") or [{}])[0].get("micros") in ("0", "0.0")],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nreport: {path}")
    print(f"zero-priced offers: {len(payload['zero_price'])}")

    if args.diff:
        try:
            old = json.loads(Path(args.diff).read_text(encoding="utf-8"))
            old_keys = {(o["product"], str(o.get("id"))) for o in old.get("offers", [])}
            new_keys = {(o["product"], str(o.get("id"))) for o in payload["offers"]}
            gained = sorted(new_keys - old_keys)
            lost = sorted(old_keys - new_keys)
            print(f"\ndiff vs {args.diff}")
            print(f"  new offers : {gained or 'none'}")
            print(f"  gone       : {lost or 'none'}")
        except Exception as exc:
            print(f"diff failed: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


