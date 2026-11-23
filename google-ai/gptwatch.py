"""gptwatch — capture ChatGPT's real product identifiers (RevenueCat + Play Billing).

The app is Flutter with RevenueCat over Google Play Billing. This attaches and logs:
  * product ids handed to Play's queryProductDetailsAsync
  * offer tokens handed to launchBillingFlow
  * every package in every RevenueCat offering, including ones the paywall hides

No purchase is ever initiated here: it only observes what the app itself asks for.

Usage:
    python gptwatch.py --watch 90        # attach, then drive the app by hand
    python gptwatch.py --no-launch       # attach to the running app only
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

PKG = "com.openai.chatgpt"
FRIDA_PORT = 27042


def pkg_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PKG}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Observe ChatGPT billing identifiers (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--watch", type=float, default=90)
    ap.add_argument("--no-launch", action="store_true", help="do not bring the app to front")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    print(f"serial : {ultra0.SERIAL}")
    ultra0.ensure_root()
    ultra0.ensure_frida_client()
    ultra0.ensure_frida_server()
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    if not args.no_launch:
        ultra0.sh("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
        time.sleep(5)

    pid = pkg_pid()
    if not pid:
        raise SystemExit(f"{PKG} is not running")
    print(f"pid    : {pid}")
    print(f"focus  : {focus().strip()[:110]}")

    events: list[dict] = []
    skus: set[str] = set()
    tokens: set[str] = set()
    rc: list[dict] = []
    lock = threading.Lock()
    ready = threading.Event()

    def on_msg(msg, data):
        p = msg.get("payload") or {}
        ev = p.get("ev")
        with lock:
            events.append(p)
        if ev == "sku":
            with lock:
                skus.add(p["value"])
            print(f"  SKU     {p['value']}   <- {p.get('src')}")
        elif ev == "token":
            with lock:
                tokens.add(p["value"])
            print(f"  TOKEN   {p['value'][:60]}... ({len(p['value'])}) <- {p.get('src')}")
        elif ev in ("offering", "package"):
            with lock:
                rc.append(p)
            print(f"  {ev.upper():8s} {p['value']}   <- {p.get('src')}")
        elif ev == "odd":
            print(f"  ODD     {p['value']}")
        elif ev in ("hooked", "hook_err", "ready", "armed", "class_ok", "class_missing",
                    "rc_err", "rc_hook_err", "dump_err"):
            detail = p.get("target") or ""
            print(f"  [{ev}] {detail} {p.get('overloads') or ''} {p.get('m') or ''}".rstrip())
            if ev == "armed":
                ready.set()

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / "gpt_probe.js").read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    ready.wait(timeout=20)
    time.sleep(1)

    print(f"\nwatching {args.watch:.0f}s — open the paywall now")
    deadline = time.time() + args.watch
    last = 0
    while time.time() < deadline:
        time.sleep(2)
        with lock:
            n = len(skus) + len(tokens)
        if n != last:
            print(f"  ({len(skus)} sku, {len(tokens)} token)")
            last = n

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    print(f"\n=== {len(skus)} product id(s), {len(tokens)} offer token(s) ===")
    for s in sorted(skus):
        print("  ", s)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"gptwatch-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "skus": sorted(skus),
        "tokens": sorted(tokens),
        "revenuecat": rc,
        "events": events[-400:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
