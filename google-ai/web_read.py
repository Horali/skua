"""web_read â€” read the text of the page open in the device's Chromium, over CDP.

Chromium renders web content outside the accessibility tree, so `uiautomator` only
returns the address bar. This talks to Chrome DevTools instead, which gives the real
page text â€” and works on pages that need the device's signed-in session.

Prerequisites (handled here): adb forward tcp:9222 localabstract:chrome_devtools_remote

Usage:
    python web_read.py                       # read whatever tab is open
    python web_read.py --url https://...     # navigate that tab first
    python web_read.py --links               # also list page links
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

import websocket

import ultra0

DEVTOOLS_PORT = 9222


def adb(*a, timeout=90):
    return subprocess.run([ultra0.ADB, "-s", ultra0.SERIAL, *a],
                          capture_output=True, text=True, timeout=timeout).stdout


def targets() -> list[dict]:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json", timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        print(f"devtools not reachable: {exc}")
        return []


def cdp_eval(ws_url: str, expr: str, timeout: float = 60.0) -> str:
    for attempt in (1, 2):
        try:
            return _cdp_eval_once(ws_url, expr, timeout)
        except Exception as exc:
            print(f"  (cdp attempt {attempt} failed: {type(exc).__name__})")
    return ""


def _cdp_eval_once(ws_url: str, expr: str, timeout: float) -> str:
    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True}}))
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {}).get("result", {})
                return str(res.get("value", ""))
        return ""
    except Exception as exc:
        print(f"  (cdp eval failed: {type(exc).__name__})")
        return ""
    finally:
        try:
            ws.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Read the device browser's page text via CDP")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--url", default=None, help="navigate the active tab here first")
    ap.add_argument("--links", action="store_true", help="also print page links")
    ap.add_argument("--max", type=int, default=4000)
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    adb("forward", f"tcp:{DEVTOOLS_PORT}", "localabstract:chrome_devtools_remote")
    pages = [t for t in targets() if t.get("type") == "page"]
    if not pages:
        raise SystemExit("no page target â€” open Chromium on the device first")
    page = pages[0]
    ws_url = page.get("webSocketDebuggerUrl")
    print(f"page: {page.get('title','')[:80]} | {page.get('url','')[:100]}")

    if args.url:
        cdp_eval(ws_url, f"location.href = {json.dumps(args.url)}; 'nav'")
        time.sleep(6)

    text = cdp_eval(ws_url, "document.body ? document.body.innerText : '(no body)'")
    print("\n=== page text ===")
    print(text[:args.max] if text else "(empty)")

    if args.links:
        raw = cdp_eval(ws_url,
                       "JSON.stringify(Array.from(document.querySelectorAll('a')).slice(0,200)"
                       ".map(a => a.href))")
        try:
            links = json.loads(raw) if raw else []
        except Exception:
            links = []
        print(f"\n=== {len(links)} link(s) ===")
        for l in links[:60]:
            print("  ", l[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


