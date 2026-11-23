"""campaign_claim — open (and verify) a checkout for a CAMPAIGN offer.

The campaign namespace (`<core>.<N>months_ip_<P>p.acq`, offerId `introprice`) is not
reachable from `ultra0.py --plan pro12`, which points at `g1.2tb.ai.subs_variant`.
This tool queries one campaign product and launches billing flow with that offer's
token directly.

Safety model:
  * default mode is --list: query + report, never opens a sheet
  * --launch opens the sheet and STOPS there. Nothing is slid, nothing is confirmed;
    the sheet is dismissed with a BACK keyevent unless --keep-open
  * there is no --buy flag on purpose. Completing a purchase stays a human action.

Usage:
    python campaign_claim.py --list
    python campaign_claim.py --launch --expect-first "Rp 15.000"
    python campaign_claim.py --product g1.2tb.ai.1month_ip_90p.acq --launch
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

DEFAULT_PRODUCT = "g1.2tb.ai.1month_ip_95p.acq"
DEFAULT_OFFER = "introprice"


def pkg_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PKG}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def screen_text() -> str:
    ultra0.sh("shell", "uiautomator dump /sdcard/cc.xml >/dev/null 2>&1")
    xml = ultra0.sh("shell", "cat /sdcard/cc.xml") or ""
    return " | ".join(t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Campaign offer checkout (opens sheet, never confirms)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--product", default=DEFAULT_PRODUCT)
    ap.add_argument("--offer", default=DEFAULT_OFFER, help="offerId to select, default introprice")
    ap.add_argument("--list", action="store_true", help="read-only: query and report (default)")
    ap.add_argument("--launch", action="store_true", help="open the checkout sheet, do not confirm")
    ap.add_argument("--expect-first", default=None,
                    help='assert the sheet shows this price, e.g. "Rp 15.000"')
    ap.add_argument("--keep-open", action="store_true", help="leave the sheet open for manual review")
    ap.add_argument("--settle", type=float, default=9.0)
    ap.add_argument("--activity-method", default="auto", choices=["auto", "choose", "thread"])
    ap.add_argument("--probe-activity", action="store_true",
                    help="only test whether launchBillingFlow's Activity lookup works (opens nothing)")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    if not args.launch:
        args.list = True
        mode = "LIST"
    else:
        mode = "LAUNCH"
    if args.probe_activity:
        mode = "PROBE-ACTIVITY"

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
    ultra0.ensure_network()
    ultra0.launch_app()
    time.sleep(4)
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    pid = pkg_pid()
    if not pid:
        raise SystemExit("Google One is not running")
    print(f"pid     : {pid}")

    if args.probe_activity:
        # Validates the only fragile part of the launch path without opening a sheet.
        probe = r"""
function usable(a) {
  try {
    if (!a || a.isFinishing()) return false;
    try { if (a.isDestroyed()) return false; } catch (_) {}
    return true;
  } catch (e) { return false; }
}
Java.perform(function () {
  var found = null;
  try {
    Java.choose("android.app.Activity", {
      onMatch: function (a) { if (!found && usable(a)) found = a; },
      onComplete: function () {}
    });
  } catch (e) { send({ ev: "choose_err", m: String(e).slice(0, 160) }); }
  if (found) {
    send({ ev: "activity", method: "choose", name: String(found.getClass().getName()) });
    return;
  }
  try {
    var T = Java.use("android.app.ActivityThread");
    var cur = T.currentActivityThread();
    var recs = cur.mActivities.value;
    var R = Java.use("android.app.ActivityThread$ActivityClientRecord");
    for (var i = 0; i < recs.size(); i++) {
      var rec = Java.cast(recs.valueAt(i), R);
      var a = rec.activity.value;
      if (usable(a)) { send({ ev: "activity", method: "thread", name: String(a.getClass().getName()) }); return; }
    }
  } catch (e) { send({ ev: "thread_err", m: String(e).slice(0, 160) }); }
  send({ ev: "no_activity" });
});
"""
        got: list[dict] = []
        dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
        sess = dev.attach(pid)
        script = sess.create_script(probe)
        script.on("message", lambda m, d: got.append(m.get("payload") or {}))
        script.load()
        time.sleep(4)
        for g in got:
            print(f"  {g}")
        ok = any(g.get("ev") == "activity" for g in got)
        print(f"  activity lookup: {'OK' if ok else 'FAILED'}")
        try:
            sess.detach()
        except Exception:
            pass
        return 0 if ok else 1

    js = (Path(__file__).parent / "assets" / "frida" / "campaign_launch.js").read_text("utf-8")
    js = js.replace("__PRODUCTS__", json.dumps([args.product]), 1)
    js = js.replace("__OFFER_ID__", json.dumps(args.offer), 1)
    js = js.replace("__LIST_ONLY__", "true" if args.list else "false", 1)
    js = js.replace('var ACTIVITY_METHOD = "auto";',
                    f'var ACTIVITY_METHOD = "{args.activity_method}";', 1)

    events: list[dict] = []
    offers: list[dict] = []
    chosen: dict = {}
    launched: dict = {}
    lock = threading.Lock()
    done = threading.Event()

    def on_msg(msg, data):
        p = msg.get("payload") or {}
        ev = p.get("ev")
        with lock:
            events.append(p)
        if ev == "offer":
            with lock:
                offers.append(p)
            first = (p.get("phases") or [{}])[0]
            print(f"  offer id={p.get('id'):14s} first={first.get('formatted'):>14s} "
                  f"{first.get('period')}  phases={len(p.get('phases') or [])}")
        elif ev == "chosen":
            with lock:
                chosen.update(p)
            print(f"  chosen  : {p.get('product')} / {p.get('id')}  first={p.get('first')} "
                  f"({p.get('period')}, {p.get('phases')} phases)")
        elif ev == "launched":
            with lock:
                launched.update(p)
            print(f"  launched: code={p.get('code')} msg={p.get('msg')}")
            done.set()
        elif ev in ("no_product", "no_offers", "no_campaign", "boot_err", "query_err",
                    "launch_err", "launch_outer_err", "no_activity", "no_activity_launch"):
            print(f"  [{ev}] {p.get('m') or p.get('code') or p.get('offer_id') or ''}")
            if ev in ("no_product", "no_offers", "no_campaign", "boot_err", "query_err"):
                done.set()
        elif ev in ("pd", "setup", "connecting", "query_sent", "activity", "activity_selected"):
            if ev == "pd":
                print(f"  product details: code={p.get('code')} n={p.get('n')}")
            elif ev == "activity":
                print(f"  activity: {p.get('a')}")

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(js)
    script.on("message", on_msg)
    script.load()

    # Query completes in a couple of seconds; a launch adds the sheet animation.
    timeout = 45 if args.launch else 25
    done.wait(timeout=timeout)
    time.sleep(1.5)

    verdict = "unknown"
    sheet_ok = False
    text = ""
    if args.launch and launched:
        code = str(launched.get("code"))
        print(f"\n  sheet focus: {focus().strip()[:120]}")
        if code == "0":
            time.sleep(args.settle)
            print(f"  after settle focus: {focus().strip()[:120]}")
            text = screen_text()
            print(f"\n  --- sheet text ---\n  {text[:900]}\n")
            if args.expect_first:
                if args.expect_first in text:
                    verdict = "INTRO HONORED"
                    sheet_ok = True
                elif "309.000" in text or "158.000" in text:
                    verdict = "FULL PRICE ONLY"
                else:
                    verdict = "PRICE NOT ON SCREEN (read text above)"
            else:
                verdict = "SHEET OPEN (no --expect-first given)"
            ultra0.sh("shell", "screencap -p /sdcard/claim.png")
            outdir = Path(args.out)
            outdir.mkdir(parents=True, exist_ok=True)
            ultra0.sh("pull", "/sdcard/claim.png",
                      str((outdir / f"claim-{time.strftime('%Y%m%d-%H%M%S')}.png").resolve()))
        else:
            verdict = f"LAUNCH FAILED code={code}"
        print(f"  verdict: {verdict}")

    # --- leave nothing pending ---------------------------------------------
    if args.launch and not args.keep_open:
        for _ in range(3):
            f = focus()
            if PKG in f and ("vending" not in f):
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
    path = outdir / f"campaign-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "mode": mode,
        "product": args.product,
        "offer_id": args.offer,
        "offers": offers,
        "chosen": chosen,
        "launched": launched,
        "verdict": verdict,
        "sheet_text": text,
        "events": events[-300:],
    }, indent=2), encoding="utf-8")
    print(f"\nreport: {path}")
    return 0 if verdict in ("unknown", "SHEET OPEN (no --expect-first given)", "INTRO HONORED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
