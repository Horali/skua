"""gpt_claim — open a checkout for a ChatGPT Play offer, and never confirm it.

Same contract as campaign_claim.py: every mode stops at an open sheet. There is no
flag that subscribes.

The app's own billing classes are R8-obfuscated, so this injects the toolkit's
BillingClient module into ChatGPT's process with the system classloader as parent
(the app's copy of com.google.android.gms.internal.play_billing collides otherwise).

Usage:
    python gpt_claim.py --list
    python gpt_claim.py --offer 2k8d9f8u1pmw6 --launch --keep-open
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

PKG = "com.openai.chatgpt"
FRIDA_PORT = 27042
DEFAULT_PRODUCT = "oai.chatgpt.go"
DEFAULT_OFFER = "2k8d9f8u1pmw6"   # Free / P6M on ChatGPT Go


def pkg_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PKG}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def screen_text() -> str:
    ultra0.sh("shell", "uiautomator dump /sdcard/gc.xml >/dev/null 2>&1")
    xml = ultra0.sh("shell", "cat /sdcard/gc.xml") or ""
    return " | ".join(t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="ChatGPT offer checkout (opens sheet, never confirms)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--product", default=DEFAULT_PRODUCT)
    ap.add_argument("--offer", default=DEFAULT_OFFER)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--keep-open", action="store_true")
    ap.add_argument("--settle", type=float, default=9.0)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    if not args.launch:
        args.list = True
        mode = "LIST"
    else:
        mode = "LAUNCH"

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    print(f"serial  : {ultra0.SERIAL}")
    print(f"mode    : {mode}")
    print(f"product : {args.product}")
    print(f"offer   : {args.offer}")

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
    print(f"pid     : {pid}")

    js = (Path(__file__).parent / "assets" / "frida" / "gpt_launch.js").read_text("utf-8")
    js = js.replace("__PRODUCTS__", json.dumps([args.product]), 1)
    js = js.replace("__OFFER_ID__", json.dumps(args.offer), 1)
    js = js.replace("__LIST_ONLY__", "true" if args.list else "false", 1)

    events: list[dict] = []
    offers: list[dict] = []
    chosen: dict = {}
    launched: dict = {}
    done = threading.Event()

    def on_msg(msg, data):
        p = msg.get("payload") or {}
        ev = p.get("ev")
        events.append(p)
        if ev == "offer":
            offers.append(p)
            ph = (p.get("phases") or [{}])[0]
            print(f"  offer {p.get('id')!s:20s} first={ph.get('formatted')!s:>12s} {ph.get('period')} "
                  f"phases={len(p.get('phases') or [])}")
        elif ev == "chosen":
            chosen.update(p)
            print(f"  chosen : {p.get('product')} / {p.get('id')} first={p.get('first')} "
                  f"({p.get('period')}, {p.get('phases')} phases)")
        elif ev == "launched":
            launched.update(p)
            print(f"  launched: code={p.get('code')} msg={p.get('msg')}")
            done.set()
        elif ev in ("boot_err", "query_err", "no_product", "no_campaign", "no_offers",
                    "launch_err", "launch_outer_err", "no_activity", "no_activity_launch"):
            print(f"  [{ev}] {p.get('m') or p.get('code') or ''}")
            if ev in ("boot_err", "query_err", "no_product", "no_campaign", "no_offers"):
                done.set()
        elif ev in ("activity", "activity_selected", "pd", "setup"):
            if ev == "activity":
                print(f"  activity: {p.get('a')}")

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(js)
    script.on("message", on_msg)
    script.load()
    done.wait(timeout=40)
    time.sleep(1.5)

    verdict = "unknown"
    text = ""
    if args.launch and launched:
        code = str(launched.get("code"))
        print(f"\n  sheet focus: {focus().strip()[:120]}")
        if code == "0":
            time.sleep(args.settle)
            text = screen_text()
            print(f"\n  --- screen text ---\n  {text[:900]}\n")
            verdict = "SHEET OPEN"
            ultra0.sh("shell", "screencap -p /sdcard/gc.png")
            outdir = Path(args.out)
            outdir.mkdir(parents=True, exist_ok=True)
            ultra0.sh("pull", "/sdcard/gc.png",
                      str((outdir / f"gptclaim-{time.strftime('%Y%m%d-%H%M%S')}.png").resolve()))
        else:
            verdict = f"LAUNCH FAILED code={code}"
        print(f"  verdict: {verdict}")

    if args.launch and not args.keep_open:
        for _ in range(3):
            f = focus()
            if PKG in f and "vending" not in f:
                break
            ultra0.sh("shell", "input keyevent 4")
            time.sleep(2)
        print(f"  final focus: {focus().strip()[:120]}")

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"gptclaim-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": mode,
        "product": args.product,
        "offer_id": args.offer,
        "offers": offers,
        "chosen": chosen,
        "launched": launched,
        "verdict": verdict,
        "screen_text": text,
        "events": events[-200:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
