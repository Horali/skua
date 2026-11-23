"""gpt_trial_watch — is THIS account in the ChatGPT trial cohort?

The ChatGPT Plus trial is a backend-issued "no payment trial", not a Play offer
(see handoff-discovery/GPT-PLUS-TRIAL.md). The only client-side signal is whether
the pricing screen renders trial copy. This opens the paywall, dumps the view tree
and looks for the markers taken from the app's own pricing catalogue.

Read-only: opens the paywall screen, never a checkout.

Usage:
    python gpt_trial_watch.py
    python gpt_trial_watch.py --keep-open
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import ultra0

PKG = "com.openai.chatgpt"

# Markers from assets/chatgpt_subscription_pricing.valdimodule.
TRIAL_MARKERS = [
    "try plus", "try go", "claim offer", "free trial", "start free trial",
    "no payment", "your free trial", "trial ends",
]
PRICE_MARKERS = ["rp", "per month", "/month", "monthly", "annual"]


def sh(*a, timeout=60):
    return ultra0.sh(*a, timeout=timeout)


def dump_text() -> str:
    sh("shell", "uiautomator dump /sdcard/tw.xml")
    xml = sh("shell", "cat /sdcard/tw.xml") or ""
    return " | ".join(t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip())


def find_and_tap(label: str) -> bool:
    sh("shell", "uiautomator dump /sdcard/tw.xml")
    xml = sh("shell", "cat /sdcard/tw.xml") or ""
    pat = re.compile(r'<node[^>]*text="' + re.escape(label) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
    m = pat.search(xml)
    if not m:
        return False
    x = (int(m.group(1)) + int(m.group(3))) // 2
    y = (int(m.group(2)) + int(m.group(4))) // 2
    if x == 0 and y == 0:
        return False
    print(f"  tap '{label}' at ({x},{y})")
    sh("shell", f"input tap {x} {y}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect ChatGPT trial cohort membership (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--keep-open", action="store_true")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    ultra0.ensure_root()
    # A live Play billing sheet renders "free trial" copy that has nothing to do
    # with cohort membership. Dismiss it before reading the paywall.
    sh("shell", "am force-stop com.android.vending")
    time.sleep(1)
    ultra0.sh("shell", f"am force-stop {PKG}")
    sh("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
    time.sleep(7)
    focus = sh("shell", "dumpsys window | grep mCurrentFocus") or ""
    if "vending" in focus:
        raise SystemExit(f"a Play billing sheet is still focused, aborting: {focus.strip()[:100]}")
    print(f"focus: {focus.strip()[:100]}")

    text = dump_text()
    print(f"home: {text[:160]}")

    if not find_and_tap("Get Plus"):
        # Flutter may label it differently; try the paywall via the upgrade row.
        for alt in ("Upgrade", "Get Plus", "See plans", "Compare plans"):
            if find_and_tap(alt):
                break
        else:
            print("could not find a paywall entry control")
    time.sleep(7)

    paywall = dump_text()
    print(f"\npaywall: {paywall[:600]}\n")

    low = paywall.lower()
    trial_hits = [m for m in TRIAL_MARKERS if m in low]
    price_hits = [m for m in PRICE_MARKERS if m in low]

    eligible = bool(trial_hits)
    print(f"trial markers : {trial_hits or 'none'}")
    print(f"price markers : {price_hits or 'none'}")
    print(f"VERDICT       : {'TRIAL COHORT' if eligible else 'NO TRIAL (price list only)'}")

    if not args.keep_open:
        sh("shell", "input keyevent 4")
        time.sleep(1)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"gpt-trial-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "trial_markers": trial_hits,
        "price_markers": price_hits,
        "verdict": "TRIAL_COHORT" if eligible else "NO_TRIAL",
        "paywall_text": paywall,
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
