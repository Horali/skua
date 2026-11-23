"""gpt_trial_watch â€” is THIS account in the ChatGPT trial cohort?

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


def attempt() -> tuple[bool, list[str], list[str], str]:
    """One paywall read: force-stop Play (clear any sheet), relaunch, tap, dump."""
    sh("shell", "am force-stop com.android.vending")
    time.sleep(1)
    ultra0.sh("shell", f"am force-stop {PKG}")
    sh("shell", f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
    time.sleep(7)
    focus = sh("shell", "dumpsys window | grep mCurrentFocus") or ""
    if "vending" in focus:
        print(f"  a Play billing sheet is focused, skipping this attempt: {focus.strip()[:80]}")
        return False, [], [], ""

    if not find_and_tap("Get Plus"):
        for alt in ("Upgrade", "See plans", "Compare plans"):
            if find_and_tap(alt):
                break
    time.sleep(7)

    paywall = dump_text()
    low = paywall.lower()
    trial_hits = [m for m in TRIAL_MARKERS if m in low]
    price_hits = [m for m in PRICE_MARKERS if m in low]
    return bool(trial_hits), trial_hits, price_hits, paywall


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect ChatGPT trial cohort membership (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--keep-open", action="store_true")
    ap.add_argument("--repeat", type=int, default=1,
                    help="open the paywall N times; distinguishes a per-request roll from an account-sticky flag")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    ultra0.ensure_root()

    runs = []
    winner = None
    total = max(1, args.repeat)
    for i in range(total):
        if total > 1:
            print(f"\n--- attempt {i + 1}/{total} ---")
        eligible, trial_hits, price_hits, paywall = attempt()
        runs.append({"n": i + 1, "eligible": eligible,
                     "trial_markers": trial_hits, "price_markers": price_hits,
                     "paywall_text": paywall[:400]})
        if total > 1:
            print(f"  trial={trial_hits or 'none'}  price={price_hits or 'none'}")
        if eligible and total > 1:
            winner = i + 1
            print(f"  -> trial surfaced on attempt {winner}")
            break

    eligible = any(r["eligible"] for r in runs)
    trial_hits = runs[-1]["trial_markers"] if runs else []
    price_hits = runs[-1]["price_markers"] if runs else []
    paywall = runs[-1]["paywall_text"] if runs else ""

    if total > 1:
        print(f"\n=== {sum(1 for r in runs if r['eligible'])}/{len(runs)} attempt(s) showed trial UI ===")
        if winner:
            print(f"    -> per-request or per-session variation: eligible on attempt {winner}")
        else:
            print("    -> account-sticky: re-opening the paywall never changed the verdict")
    else:
        print(f"paywall: {paywall[:600]}\n")

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
        "attempts": len(runs),
        "runs": runs,
        "paywall_text": paywall,
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())

