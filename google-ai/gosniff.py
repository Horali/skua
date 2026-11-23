"""gosniff — capture SKU + offer token at Google One's own billing sheet.

Companion to playsniff.py. Play-side hooks stayed silent on 2026-11-23 because the
sheet is GoogleOneSdkActivity (in-app), so this attaches to Google One instead and
watches the sheet's Intent plus any billing classes the app lazily loads.

Read-only: the sheet may open; nothing is confirmed, nothing is slid.

Usage:
    python gosniff.py --watch 90        # attach, then drive the UI by hand
    python gosniff.py --no-tap          # hooks only, verify arming
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from pathlib import Path

import frida

import ultra0

PKG = "com.google.android.apps.subscriptions.red"
FRIDA_PORT = 27042


def pkg_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PKG}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture Google One-side billing payload (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--watch", type=float, default=0)
    ap.add_argument("--no-tap", action="store_true")
    ap.add_argument("--drive", action="store_true",
                    help="navigate to the plans screen and open ONE upgrade sheet")
    ap.add_argument("--no-restart", action="store_true",
                    help="attach to the running app without bouncing it (keeps current screen)")
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
    ultra0.ensure_module_apk()
    ultra0.ensure_network()
    if not args.no_restart:
        ultra0.launch_app()
        time.sleep(4)
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    pid = pkg_pid()
    if not pid:
        raise SystemExit("Google One is not running")
    print(f"google one pid : {pid}")

    hits: list[dict] = []
    log: list[dict] = []
    classes: list[str] = []
    sheets: list[str] = []
    lock = threading.Lock()
    ready = threading.Event()

    def on_msg(msg, data):
        payload = msg.get("payload") or {}
        ev = payload.get("ev")
        with lock:
            log.append(payload)
        if ev in ("sku", "token", "kv", "cls_load"):
            with lock:
                hits.append({**payload, "at": time.strftime("%H:%M:%S")})
            print(f"  + {ev:8s} {payload.get('src')} key={payload.get('key')!r} {payload.get('value')}")
        elif ev == "classes":
            with lock:
                classes.extend(payload.get("names") or [])
        elif ev == "sheet_open":
            with lock:
                sheets.append(time.strftime("%H:%M:%S"))
            print(f"  [sheet] {payload.get('cls')} opened @ {sheets[-1]}")
        elif ev in ("hooked", "hook_err", "ready", "armed"):
            print(f"  [{ev}] {payload.get('target') or ''} {payload.get('overloads') or ''} "
                  f"{payload.get('m') or ''}".rstrip())
            if ev == "armed":
                ready.set()

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / "gosniff.js").read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    ready.wait(timeout=25)
    time.sleep(1)

    if args.drive:
        # Navigation happens in-process: launching by hand after attach would slow
        # the walk down and risk dragging the app out from under the hooks.
        import playsniff as ps

        ultra0.sh("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
        time.sleep(6)
        size = ps.display_size()
        print(f"\ndisplay {size[0]}x{size[1]}  focus: {focus().strip()[:90]}")

        nodes = ps.on_screen(ps.dump_screen(), size)
        text = ps.visible_text(nodes).lower()
        if "get offer" in text:
            entry = ps.find_taps(nodes, ["get offer"])
            if entry:
                print(f"tap entry '{entry[0]['text']}' {entry[0]['center']}")
                ps.tap(entry[0])
                time.sleep(8)
                nodes = ps.on_screen(ps.dump_screen(), size)
                print(f"  screen: {ps.visible_text(nodes)[:200]}")

        target = None
        for i in range(6):
            cand = [n for n in ps.on_screen(ps.dump_screen(), size)
                    if (n["text"] or n["desc"]).strip().lower() == "upgrade"]
            if cand:
                target = cand[0]
                break
            ps.scroll_down(size)
        if not target:
            print("no Upgrade control found")
        else:
            print(f"tap Upgrade at {target['center']}")
            ps.tap(target)
            time.sleep(10)
            print(f"  focus: {focus().strip()[:140]}")
            ultra0.sh("shell", "screencap -p /sdcard/sheet.png")
            ultra0.sh("pull", "/sdcard/sheet.png", str(Path("tmpui/sheet.png").resolve()))
            # Leave clean: back out, never a slider gesture.
            for _ in range(3):
                if PKG in focus():
                    break
                ultra0.sh("shell", "input keyevent 4")
                time.sleep(2)
            print(f"  final focus: {focus().strip()[:140]}")

    if args.watch:
        print(f"\nwatching {args.watch:.0f}s — drive the UI now (focus: {focus().strip()[:80]})")
        deadline = time.time() + args.watch
        last = 0
        while time.time() < deadline:
            time.sleep(2)
            with lock:
                n = len(hits)
            if n != last:
                print(f"  ({n} event(s))")
                last = n
    else:
        time.sleep(3)

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    skus = sorted({h["value"] for h in hits if h["ev"] == "sku"})
    toks = sorted({h["value"] for h in hits if h["ev"] == "token"})
    print(f"\n=== {len(skus)} sku(s), {len(toks)} token(s), {len(sheets)} sheet open(s) ===")
    for s in skus:
        print(f"  sku   {s}")
    for t in toks:
        print(f"  token {t[:60]}...({len(t)})")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"gosniff-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "skus": skus,
        "tokens": toks,
        "sheet_opens": sheets,
        "hits": hits,
        "log": log[-500:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
