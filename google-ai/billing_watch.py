"""billing_watch â€” log what an installed app asks Play for.

For apps whose product ids are server-delivered, hooking the app's own BillingClient
is the only reliable way to learn them: open the paywall and the app queries the ids
itself. Complements appoffer.py (dex discovery) and gpt_skus/claude_skus (known ids).

Read-only: never calls launchBillingFlow.

Usage:
    python billing_watch.py --package ai.perplexity.app.android --watch 90
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

FRIDA_PORT = 27042


def pkg_pid(pkg: str) -> int:
    out = ultra0.sh("shell", f"pidof {pkg}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Observe an app's own billing calls (read-only)")
    ap.add_argument("--package", required=True)
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--watch", type=float, default=90)
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--spawn", action="store_true",
                    help="spawn the app suspended, hook, then resume — catches queries fired at startup")
    ap.add_argument("--lazy", action="store_true",
                    help="watch class loading too, for apps that load billing classes after attach")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    ultra0.ensure_root()
    ultra0.ensure_frida_server()
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    if not args.no_launch:
        ultra0.sh("shell", f"monkey -p {args.package} -c android.intent.category.LAUNCHER 1")
        time.sleep(6)

    pid = pkg_pid(args.package)
    if not pid:
        raise SystemExit(f"{args.package} not running")
    print(f"pid    : {pid}")
    print(f"focus  : {focus().strip()[:100]}")

    events: list[dict] = []
    skus: list[str] = []
    tokens: list[str] = []
    lock = threading.Lock()
    ready = threading.Event()

    def on_msg(msg, data):
        p = msg.get("payload") or {}
        ev = p.get("ev")
        with lock:
            events.append(p)
        if ev == "sku":
            with lock:
                skus.append(p["value"])
            print(f"  SKU   {p['value']}   <- {p.get('src')}")
        elif ev == "token":
            with lock:
                tokens.append(p["value"])
            print(f"  TOKEN {p['value'][:56]}... ({len(p['value'])})")
        elif ev in ("hooked", "hook_err", "ready", "armed", "instrumented", "inst_err", "loaders_watched", "loader_err"):
            print(f"  [{ev}] {p.get('target') or ''} {p.get('overloads') or ''} {p.get('m') or ''}".rstrip())
            if ev == "armed":
                ready.set()

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    if args.spawn:
        ultra0.sh("shell", f"am force-stop {args.package}")
        time.sleep(1)
        spawn_pid = dev.spawn([args.package])
        pid = spawn_pid
        print(f"spawned suspended: {pid}")
        sess = dev.attach(pid)
    else:
        sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / ("billing_watch_lazy.js" if args.lazy else "billing_watch.js")).read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    ready.wait(timeout=20)
    time.sleep(1)
    if args.spawn:
        dev.resume(pid)
        print("resumed")

    print(f"\nwatching {args.watch:.0f}s â€” open the app's paywall now")
    deadline = time.time() + args.watch
    last = -1
    while time.time() < deadline:
        time.sleep(2)
        with lock:
            n = len(skus) + len(tokens)
        if n != last:
            last = n

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    uniq = sorted(set(skus))
    print(f"\n=== {len(uniq)} product id(s), {len(set(tokens))} token(s) ===")
    for s in uniq:
        print("  ", s)
    if not uniq:
        print("  (none â€” the app may not use Play Billing, or the paywall never opened)")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"billingwatch-{args.package.replace('.', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "package": args.package,
        "skus": uniq,
        "tokens": sorted(set(tokens)),
        "events": events[-300:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


