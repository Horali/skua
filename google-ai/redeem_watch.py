"""redeem_watch â€” open a Google One offer link and report what the campaign says.

Carrier and device bundles distribute *links* (`one.google.com/offer/...`), and the
app resolves them through `campaign_extra_referrer` / `GetEftPromoCodeInfo` â€”
no promo code needed. This opens such a link inside Google One, reads the screen,
and classifies the outcome.

Read-only: it opens the offer page and reports. It does not tap Redeem.

Usage:
    python redeem_watch.py --url https://one.google.com/offer/specialoffer
    python redeem_watch.py --url <link> --keep
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import ultra0

PKG = "com.google.android.apps.subscriptions.red"

# Campaign outcomes, in the app's own wording (EN + ID).
UNAVAILABLE = [
    "no longer available", "not available", "expired", "invalid",
    "tidak tersedia", "tidak berlaku", "kedaluwarsa", "tidak valid",
    "offer has ended", "penawaran berakhir", "can't be applied",
    "already redeemed", "sudah ditukar", "already claimed",
]
NOT_ELIGIBLE = [
    "not eligible", "tidak memenuhi syarat", "isn't eligible", "not eligible for this offer",
    "only available to", "hanya tersedia untuk",
]
REDEEMABLE = [
    "redeem", "tukarkan", "tukar", "claim", "klaim", "activate", "aktifkan",
    "get offer", "dapatkan penawaran", "add to account",
]
SIGNED = ["choose an account", "pilih akun", "sign in", "masuk"]


def sh(*a, timeout=90):
    return ultra0.sh(*a, timeout=timeout)


def dump_text() -> str:
    sh("shell", "uiautomator dump /sdcard/rw.xml")
    xml = sh("shell", "cat /sdcard/rw.xml") or ""
    return " | ".join(t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip())


def focus() -> str:
    return sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve a Google One offer link (read-only)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--keep", action="store_true", help="leave the offer page open")
    ap.add_argument("--settle", type=float, default=8.0)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial

    ultra0.ensure_root()
    print(f"url    : {args.url}")

    # Let the system resolve the URL: Google One claims one.google.com/redeemoffer,\n    # everything else lands in the installed Chromium.
    sh("shell", f"am force-stop {PKG}")
    time.sleep(1)
    sh("shell", f'am start -a android.intent.action.VIEW -c android.intent.category.BROWSABLE -d "{args.url}" -n {PKG}/.deeplink.DeepLink')
    time.sleep(args.settle)

    f = focus()
    print(f"focus  : {f.strip()[:110]}")

    text = dump_text()
    # Deep links often land on a chooser or a shell first; nudge once if empty.
    if not text:
        time.sleep(args.settle / 2)
        text = dump_text()

    # A link that resolves to no campaign launches the gateway and finishes at once,
    # leaving the previous app focused. Distinguish that from a rendered page.
    if PKG not in f and "chromium" not in f.lower() and "chrome" not in f.lower():
        verdict_noop = True
    else:
        verdict_noop = False

    low = text.lower()
    verdict = "UNKNOWN"
    hits: list[str] = []
    if any(k in low for k in UNAVAILABLE):
        verdict = "UNAVAILABLE"
        hits = [k for k in UNAVAILABLE if k in low]
    elif any(k in low for k in NOT_ELIGIBLE):
        verdict = "NOT ELIGIBLE"
        hits = [k for k in NOT_ELIGIBLE if k in low]
    elif any(k in low for k in REDEEMABLE):
        verdict = "REDEEMABLE"
        hits = [k for k in REDEEMABLE if k in low]
    elif any(k in low for k in SIGNED):
        verdict = "NEEDS ACCOUNT PICK"
    elif verdict_noop:
        verdict = "NO-OP (link opened nothing — invalid/expired campaign)"

    print(f"\n--- screen ---\n{text[:800]}\n")
    print(f"markers : {hits or 'none'}")
    print(f"VERDICT : {verdict}")

    sh("shell", "screencap -p /sdcard/rw.png")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    png = outdir / f"redeem-{stamp}.png"
    sh("pull", "/sdcard/rw.png", str(png.resolve()))

    if not args.keep:
        sh("shell", "input keyevent 4")
        time.sleep(1)

    path = outdir / f"redeem-{stamp}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "url": args.url,
        "focus": f.strip(),
        "verdict": verdict,
        "markers": hits,
        "screen_text": text,
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



