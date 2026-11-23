"""idcapture â€” harvest the real Play product IDs by tapping through Google One's UI.

Static scraping does not work: the APK hardcodes exactly one product id
(`g1.100gb`); everything else is delivered by Google's server. The only reliable
way to learn the catalogue is to watch what the app *asks for* while a human (or
this script) walks the plans screens.

How it works:
  1. attach to Google One, install `assets/frida/id_sniffer.js`
     (hooks JSONObject.put / Bundle.putString / Intent.putExtra)
  2. dump the view tree with uiautomator, find plan-related controls
  3. tap them one by one, pausing so the sniffer can record ids
  4. print every product id seen, with the screen that produced it

Read-only: taps navigation and logs strings. No checkout is opened.

Usage:
    python idcapture.py                     # full sweep
    python idcapture.py --max-taps 12
    python idcapture.py --settle 4
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

# Controls worth tapping, in rough navigation order. Matched case-insensitively
# against uiautomator `text` and `content-desc`.
TAP_HINTS = [
    "upgrade", "see more plans", "see all plans", "more plans", "view plans",
    "get discount", "get offer", "google ai", "ai pro", "ai ultra", "pro",
    "ultra", "plans", "manage", "change plan", "explore",
]
SKIP_HINTS = ["cancel", "cancel subscription", "delete", "sign out", "remove"]


def parse_nodes(xml: str) -> list[dict]:
    nodes = []
    for m in re.finditer(r"<node\b[^>]*>", xml):
        raw = m.group(0)
        text = re.search(r'text="([^"]*)"', raw)
        desc = re.search(r'content-desc="([^"]*)"', raw)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', raw)
        clickable = re.search(r'clickable="(true|false)"', raw)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in (1, 2, 3, 4))
        nodes.append({
            "text": (text.group(1) if text else "").strip(),
            "desc": (desc.group(1) if desc else "").strip(),
            "clickable": (clickable.group(1) == "true") if clickable else False,
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            "bounds": [x1, y1, x2, y2],
        })
    return nodes


def dump_screen() -> list[dict]:
    ultra0.sh("shell", "uiautomator dump /sdcard/idc.xml")
    xml = ultra0.sh("shell", "cat /sdcard/idc.xml")
    return parse_nodes(xml)


def candidates(nodes: list[dict]) -> list[dict]:
    out = []
    for n in nodes:
        label = (n["text"] or n["desc"]).lower()
        if not label:
            continue
        if any(s in label for s in SKIP_HINTS):
            continue
        if any(h in label for h in TAP_HINTS):
            out.append(n)
    # de-duplicate by label
    seen, uniq = set(), []
    for n in out:
        key = (n["text"] or n["desc"]).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)
    return uniq


def ensure_forward(serial: str) -> None:
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest product IDs from the Google One UI (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--max-taps", type=int, default=18)
    ap.add_argument("--settle", type=float, default=3.0, help="seconds to wait after each tap")
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
    ultra0.launch_app()
    time.sleep(4)
    ensure_forward(ultra0.SERIAL)

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    pid = 0
    for p in dev.enumerate_processes():
        if "subscriptions.red" in p.name or p.name == "Google One":
            pid = p.pid
            break
    if not pid:
        raise SystemExit("Google One not running")

    captured: dict[str, str] = {}
    log: list[dict] = []
    lock = threading.Lock()

    def on_msg(m, data):
        payload = m.get("payload") or {}
        ev = payload.get("ev")
        if ev == "id":
            with lock:
                if payload["value"] not in captured:
                    captured[payload["value"]] = payload.get("src", "")
            print(f"  + id {payload['value']}   ({payload.get('src')})")
        elif ev in ("hooked", "ready", "hook_err", "sniffer_start"):
            print(f"  [{ev}] {payload.get('target') or payload.get('hooked') or ''} {payload.get('m') or ''}".rstrip())
        log.append(payload)

    # create_script lives on a Session, not on the Device.
    sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / "id_sniffer.js").read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    time.sleep(2)

    taps = 0
    visited: set[str] = set()
    while taps < args.max_taps:
        nodes = dump_screen()
        todo = [n for n in candidates(nodes)
                if (n["text"] or n["desc"]).lower() not in visited]
        if not todo:
            # Nothing new: go back one screen and retry a couple of times.
            ultra0.sh("shell", "input keyevent 4")
            time.sleep(1.5)
            nodes = dump_screen()
            todo = [n for n in candidates(nodes)
                    if (n["text"] or n["desc"]).lower() not in visited]
            if not todo:
                print("no further plan controls found")
                break
        n = todo[0]
        label = (n["text"] or n["desc"])
        visited.add(label.lower())
        x, y = n["center"]
        print(f"tap {taps + 1}: '{label}' at ({x},{y})")
        ultra0.sh("shell", f"input tap {x} {y}")
        taps += 1
        time.sleep(args.settle)

    try:
        script.unload()
    except Exception:
        pass

    print(f"\n=== {len(captured)} product id(s) captured ===")
    for v in sorted(captured):
        print(f"  {v}")
    if not captured:
        print("  (none â€” the UI may not emit product ids until a checkout starts)")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"idcapture-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "taps": taps,
        "ids": captured,
        "log": log[-400:],
    }, indent=2), encoding="utf-8")
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

