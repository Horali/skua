"""gpt_skus â€” query ChatGPT's Play products from inside its own process.

Product ids come from RevenueCat's cached offerings (see
reports/gpt-dex-classes.json and the app's shared_prefs):
    oai.chatgpt.plus    oai.chatgpt.pro   oai.chatgpt.go
    oai.chatgpt.prolite oai.chatgpt.promax

Play only returns products that belong to the calling package, so the query must
run inside com.openai.chatgpt. The app's own billing classes are R8-obfuscated,
which is why this injects our own BillingClient module instead of hooking theirs.

Read-only: queries product details, never launches a purchase.

Usage:
    python gpt_skus.py
    python gpt_skus.py --extra oai.chatgpt.foo
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import frida

import ultra0

PKG = "com.anthropic.claude"
FRIDA_PORT = 27042

SKUS = [
    "claude-pro-monthly",
    "claude-pro-annual",
    "claude_pro",
    "claude_max",
    "com.anthropic.claude.pro",
    "com.anthropic.claude.max",
    "claude_max_5x",
    "claude_max_20x",
    "default_claude_max_5x",
    "default_claude_max_20x",
    "claude_pro_monthly",
    "claude_pro_annual",
    "claude.pro.monthly",
    "claude.pro.annual",
    "claude-max-monthly",
    "claude-max-annual",
    "claude-plus",
    "claude-team",
    "claudeai.pro.monthly",
    "claudeai.pro.annual",
    "claude-pro",
    "claude-pro-yearly",
]

def pkg_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PKG}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Query ChatGPT Play products (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    ultra0.ensure_root()
    ultra0.ensure_frida_client()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()
    ultra0.sh("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
    time.sleep(5)
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    pid = pkg_pid()
    if not pid:
        raise SystemExit(f"{PKG} not running")
    candidates = sorted(set(SKUS) | set(args.extra))
    print(f"pid {pid} | {len(candidates)} candidate product(s)")

    # sku_probe_iso loads the module with a null parent: inside ChatGPT the app's
    # own copy of com.google.android.gms.internal.play_billing collides with the
    # module's, and parent-first delegation throws IllegalAccessError.
    js = (Path(__file__).parent / "assets" / "frida" / "sku_probe_iso.js").read_text("utf-8")
    js = js.replace("var PRODUCTS = __PRODUCTS__;",
                    "var PRODUCTS = " + json.dumps(candidates) + ";", 1)

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    done = threading.Event()
    offers: list[dict] = []
    errors: list[str] = []

    def on_msg(m, data):
        p = m.get("payload") or {}
        ev = p.get("ev")
        if ev == "offer":
            offers.append(p)
            ph = p.get("phases") or [{}]
            print(f"  offer {p['product']} id={p.get('id')} first={ph[0].get('formatted')} "
                  f"{ph[0].get('period')} phases={len(ph)}")
        elif ev == "done":
            done.set()
        elif ev in ("boot_err", "query_err", "parse_err"):
            errors.append(f"{ev}: {p.get('m')}")
            print(f"  [{ev}] {p.get('m')}")
        elif ev == "setup":
            print(f"  setup code={p.get('code')}")

    script = sess.create_script(js)
    script.on("message", on_msg)
    script.load()
    done.wait(timeout=90)
    time.sleep(1)
    try:
        sess.detach()
    except Exception:
        pass

    print(f"\n=== {len(offers)} offer(s), {len(errors)} error(s) ===")
    by_product: dict[str, list[dict]] = {}
    for o in offers:
        by_product.setdefault(o["product"], []).append(o)
    for pid_name in sorted(by_product):
        print(f"\n{pid_name}")
        for o in by_product[pid_name]:
            phases = o.get("phases") or []
            desc = " | ".join(f"{ph.get('formatted')}/{ph.get('period')}" for ph in phases)
            print(f"  offer={o.get('id')!s:22s} phases={len(phases)}  {desc}")
    if not offers:
        print("no products returned â€” ids wrong, or not sold in this storefront")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"gptskus-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "candidates": candidates,
        "offers": offers,
        "errors": errors,
    }, indent=2), encoding="utf-8")
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


