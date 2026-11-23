"""sheetwalk — walk Google One to Play's purchase sheet, then read the sheet's payload.

One process, one run: no attach/tap races. Steps:
  1. launch Google One, land on the plans screen
  2. tap the card's Upgrade, confirm the "How it works" dialog
  3. wait until Play's SheetUiBuilderHostActivity has focus
  4. attach Play and run assets/frida/sheetprobe.js (bounded reflection over the
     live sheet + its Intent)
  5. back out — never a slider gesture, nothing confirmed

Read-only in the billing sense: the sheet opens and is discarded.

Usage:
    python sheetwalk.py                 # full walk, capture, back out
    python sheetwalk.py --stop-at plans # stop before opening the sheet
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
import playsniff as ps

PKG = "com.google.android.apps.subscriptions.red"
PLAY = "com.android.vending"
FRIDA_PORT = 27042


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def tap_text(label: str, size, scrolls: int = 6, exact: bool = True) -> bool:
    """Find a control by its visible text inside the viewport, then tap its centre.

    Off-screen nodes carry bounds [0,0][0,0] (or bounds past the viewport); tapping
    those hits the clamped pixel instead of the control, so they are filtered out
    and the list is scrolled until a real one appears.
    """
    want = label.lower()
    for attempt in range(scrolls + 1):
        nodes = ps.on_screen(ps.dump_screen(), size)
        for n in nodes:
            text = (n["text"] or n["desc"]).strip().lower()
            if (text == want) if exact else (want in text):
                x, y = n["center"]
                print(f"    tap '{n['text'] or n['desc']}' at ({x},{y})")
                ps.tap(n)
                return True
        if attempt < scrolls:
            ps.scroll_down(size)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk to the Play sheet and read its payload")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--stop-at", choices=["plans", "sheet"], default="sheet")
    ap.add_argument("--settle", type=float, default=7.0)
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

    # Arm Play BEFORE the sheet exists: Play stays alive, only Google One is
    # bounced. Hooking after the sheet appears is too late (the activity map is
    # already empty and onCreate never re-runs).
    ultra0.sh("shell", f"monkey -p {PLAY} -c android.intent.category.LAUNCHER 1")
    time.sleep(4)
    pid = int((ultra0.sh("shell", f"pidof {PLAY}") or "0").split()[0])
    print(f"play pid : {pid}")

    hits: list[dict] = []
    log: list[dict] = []
    sheets: list[str] = []
    lock = threading.Lock()
    ready = threading.Event()

    def on_msg(m, d):
        p = m.get("payload") or {}
        with lock:
            log.append(p)
        ev = p.get("ev")
        if ev == "hit":
            with lock:
                hits.append(p)
            print(f"  + HIT {p.get('src')} = {p.get('value')}")
        elif ev == "sheet_open":
            with lock:
                sheets.append(p.get("cls") or "")
            print(f"  [sheet] onCreate {p.get('cls')}")
        elif ev in ("phase", "hooked", "hook_err", "ready", "armed"):
            line = f"  [{ev}] {p.get('target') or ''} {p.get('m') or ''}".rstrip()
            if ev != "phase" or "visited" in str(p.get("m")):
                print(line)
            if ev == "armed":
                ready.set()

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / "sheetprobe.js").read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    ready.wait(timeout=25)
    time.sleep(1)

    # Now bounce Google One only, and walk.
    ultra0.sh("shell", f"am force-stop {PKG}")
    ultra0.launch_app()
    time.sleep(6)
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    size = ps.display_size()
    print(f"display {size[0]}x{size[1]}  focus {focus().strip()[:80]}")

    # --- 1. home -> plans ---------------------------------------------------
    if "get offer" in ps.visible_text(ps.on_screen(ps.dump_screen(), size)).lower():
        tap_text("Get offer", size)
        time.sleep(args.settle)
    print(f"  after entry: {focus().strip()[:90]}")
    print(f"  screen: {ps.visible_text(ps.on_screen(ps.dump_screen(), size))[:160]}")

    if args.stop_at == "plans":
        print("stopping at plans")
        return 0

    # --- 2. open the card's upgrade + confirm the dialog ---------------------
    if not tap_text("Upgrade", size):
        print("could not find an Upgrade control")
        return 1
    time.sleep(args.settle)

    # The "How it works" dialog sits between the card and Play's sheet.
    if tap_text("Continue to subscribe", size, scrolls=1):
        print("    passed 'How it works' dialog")
    else:
        print("    no dialog — sheet may be direct")
    time.sleep(args.settle)

    # --- 4. wait for the hooked onCreate to fire ----------------------------
    deadline = time.time() + 20
    while time.time() < deadline:
        with lock:
            if sheets or hits:
                break
        time.sleep(1)
    time.sleep(2)
    print(f"  sheet focus: {focus().strip()[:130]}")

    # --- 5. back out, leave nothing pending ---------------------------------
    for _ in range(3):
        f = focus()
        if PKG in f and PLAY not in f:
            break
        ultra0.sh("shell", "input keyevent 4")
        time.sleep(2)
    print(f"  final focus: {focus().strip()[:120]}")
    ultra0.sh("shell", "screencap -p /sdcard/final.png")
    ultra0.sh("pull", "/sdcard/final.png", str(Path("tmpui/final.png").resolve()))

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    sheet_up = bool(sheets)
    skus = sorted({h["value"] for h in hits if h["value"].startswith("g1.")})
    toks = sorted({h["value"] for h in hits if h["value"].startswith("AYrTWi")})
    print(f"\n=== {len(skus)} sku(s), {len(toks)} token(s), {len(hits)} hit(s), "
          f"{len(sheets)} onCreate ===")
    for s in skus:
        print("  sku  ", s)
    for t in toks:
        print("  token", t[:70], f"({len(t)} chars)")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"sheetwalk-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "sheet_up": sheet_up,
        "skus": skus,
        "tokens": toks,
        "hits": hits,
        "log": log[-400:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
