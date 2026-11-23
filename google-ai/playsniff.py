"""playsniff — capture the product ID + offer token Play carries into its purchase sheet.

Experiment A from HANDOFF-DISCOVERY.md §4. Hooks com.android.vending (Play Store),
not Google One: the billing SDK classes are absent from both processes, but Play
builds the sheet Intent and that Intent carries the SKU + offer token as plain data.

Flow:
  1. root + frida + billing module (reuses ultra0 helpers)
  2. launch Google One, attach Play by real pid (`pidof com.android.vending`)
  3. load assets/frida/playsniff.js
  4. walk the plans UI, tap "Get offer" / "Get discount" per card
  5. back out of every sheet — never slide, never subscribe
  6. print + save every id/token captured, with the screen that produced it

Read-only in the billing sense: the sheet opens, nothing is confirmed.

Usage:
    python playsniff.py                          # attach + walk, taps enabled
    python playsniff.py --no-tap                 # attach only, verify hooks
    python playsniff.py --taps 3 --settle 6
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
PLAY = "com.android.vending"
FRIDA_PORT = 27042

# Controls that open a sheet but do not confirm anything. "Switch" is deliberately
# excluded: it is a same-tier billing-period change, not an offer surface.
TAP_HINTS = ["get offer", "get discount", "upgrade", "see all plans", "explore plans",
             "view plans", "change plan"]
NEVER_TAP = ["switch", "subscribe", "slide", "buy", "confirm", "pay"]


def play_pid() -> int:
    out = ultra0.sh("shell", f"pidof {PLAY}") or ""
    pids = [int(x) for x in out.split() if x.isdigit()]
    return pids[0] if pids else 0


def focus() -> str:
    return ultra0.sh("shell", "dumpsys window | grep -E 'mCurrentFocus'") or ""


def parse_nodes(xml: str) -> list[dict]:
    nodes = []
    for m in re.finditer(r"<node\b[^>]*>", xml):
        raw = m.group(0)
        text = re.search(r'text="([^"]*)"', raw)
        desc = re.search(r'content-desc="([^"]*)"', raw)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', raw)
        if not bounds:
            continue
        x1, y1, x2, y2 = (int(bounds.group(i)) for i in (1, 2, 3, 4))
        if x2 <= x1 or y2 <= y1:          # off-screen / zero-size node
            continue
        nodes.append({
            "text": (text.group(1) if text else "").strip(),
            "desc": (desc.group(1) if desc else "").strip(),
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            "bounds": [x1, y1, x2, y2],
        })
    return nodes


def dump_screen() -> list[dict]:
    ultra0.sh("shell", "uiautomator dump /sdcard/ps.xml >/dev/null 2>&1")
    xml = ultra0.sh("shell", "cat /sdcard/ps.xml") or ""
    return parse_nodes(xml)


def display_size() -> tuple[int, int]:
    """Actual on-screen pixel size in the *current* rotation.

    uiautomator reports coordinates in the rotated space while `wm size` reports
    the unrotated physical size, so neither alone is trustworthy for clamping.
    A screenshot is exact: parse the PNG IHDR.
    """
    ultra0.sh("shell", "screencap -p /sdcard/ps_size.png")
    local = Path("tmpui") / "size.png"
    local.parent.mkdir(parents=True, exist_ok=True)
    ultra0.sh("pull", "/sdcard/ps_size.png", str(local.resolve()), timeout=60)
    try:
        head = local.read_bytes()[:33]
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a png")
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        if w > 0 and h > 0:
            return w, h
    except Exception as exc:
        print(f"  display_size fallback ({type(exc).__name__}); assuming 1920x1080")
    return 1920, 1080


def on_screen(nodes: list[dict], size: tuple[int, int]) -> list[dict]:
    """Keep only nodes fully inside the viewport.

    uiautomator happily returns bounds past the screen edge (e.g. y2=1195 on a
    1080-tall display); a tap on one of those lands on whatever is at the
    clamped pixel. See HANDOFF §6.4.
    """
    w, h = size
    out = []
    for n in nodes:
        x1, y1, x2, y2 = n["bounds"]
        if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
            continue
        out.append(n)
    return out


def visible_text(nodes: list[dict]) -> str:
    return " | ".join((n["text"] or n["desc"]) for n in nodes if (n["text"] or n["desc"]))


def find_taps(nodes: list[dict], seeds: list[str]) -> list[dict]:
    out = []
    for n in nodes:
        label = (n["text"] or n["desc"]).lower()
        if not label:
            continue
        if any(bad in label for bad in NEVER_TAP):
            continue
        if any(h in label for h in seeds):
            out.append(n)
    return out


def scroll_down(size: tuple[int, int], times: int = 1) -> None:
    # Compose lists do not always expose off-screen nodes; swipe is the way in.
    w, h = size
    ultra0.sh("shell", f"input swipe {w // 2} {int(h * 0.80)} {w // 2} {int(h * 0.30)} 400")
    time.sleep(1.5 * times)


def find_after_scroll(seeds: list[str], size: tuple[int, int],
                      max_scrolls: int = 8) -> list[dict]:
    found = find_taps(on_screen(dump_screen(), size), seeds)
    if found:
        return found
    for _ in range(max_scrolls):
        scroll_down(size)
        found = find_taps(on_screen(dump_screen(), size), seeds)
        if found:
            return found
    return []


def tap(node: dict) -> None:
    x, y = node["center"]
    ultra0.sh("shell", f"input tap {x} {y}")


def back(times: int = 1, pause: float = 2.0) -> None:
    for _ in range(times):
        ultra0.sh("shell", "input keyevent 4")
        time.sleep(pause)


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture Play-side product IDs (sheet opens, nothing buys)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--no-tap", action="store_true", help="attach and verify hooks only")
    ap.add_argument("--watch", type=float, default=0,
                    help="attach, then sit for N seconds while the UI is driven externally")
    ap.add_argument("--no-restart", action="store_true",
                    help="attach to the running Play process without bouncing it")
    ap.add_argument("--taps", type=int, default=6, help="max offer cards to open")
    ap.add_argument("--settle", type=float, default=5.0)
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

    # Play must be alive before we can attach; start it, then Google One on top.
    if not args.no_restart:
        ultra0.sh("shell", f"am force-stop {PLAY}")
        ultra0.sh("shell", f"am force-stop {PKG}")
        ultra0.sh("shell", f"monkey -p {PLAY} -c android.intent.category.LAUNCHER 1")
        time.sleep(4)
    print(f"play pid : {play_pid()}")
    if not args.no_restart:
        ultra0.launch_app()
        time.sleep(5)
    ultra0.sh("forward", f"tcp:{FRIDA_PORT}", f"tcp:{FRIDA_PORT}")

    pid = play_pid()
    if not pid:
        raise SystemExit("Play is not running — cannot attach")

    hits: list[dict] = []
    log: list[dict] = []
    sheet_events: list[str] = []
    play_classes: list[str] = []
    lock = threading.Lock()
    ready = threading.Event()

    def on_msg(msg, data):
        payload = msg.get("payload") or {}
        ev = payload.get("ev")
        with lock:
            log.append(payload)
        if ev in ("sku", "token", "kv"):
            # focus() is an adb round-trip; record the sequence only.
            with lock:
                hits.append({**payload, "at": time.strftime("%H:%M:%S")})
            print(f"  + {ev:5s} {payload.get('src')} key={payload.get('key')!r} value={payload.get('value')}")
        elif ev == "classes":
            with lock:
                play_classes.extend(payload.get("names") or [])
            print(f"  [classes] {payload.get('count')} finsky billing/purchase class(es) loaded")
        elif ev == "sheet_open":
            with lock:
                sheet_events.append(time.strftime("%H:%M:%S"))
            print(f"  [sheet] {PLAY} purchase sheet opened")
        elif ev in ("hooked", "hook_err", "ready", "armed"):
            detail = payload.get("target") or ""
            extra = payload.get("overloads", "")
            err = payload.get("m", "")
            print(f"  [{ev}] {detail} {extra} {err}".rstrip())
            if ev == "armed":
                ready.set()
        elif ev == "sheet_dump":
            print(f"  [sheet_dump] {payload}")

    dev = frida.get_device_manager().add_remote_device(f"127.0.0.1:{FRIDA_PORT}")
    sess = dev.attach(pid)
    script = sess.create_script(
        (Path(__file__).parent / "assets" / "frida" / "playsniff.js").read_text("utf-8"))
    script.on("message", on_msg)
    script.load()
    ready.wait(timeout=25)
    time.sleep(1)

    if args.watch:
        print(f"\nwatching for {args.watch:.0f}s — drive the UI externally now")
        deadline = time.time() + args.watch
        last = 0
        while time.time() < deadline:
            time.sleep(2)
            with lock:
                n = len(hits)
                sh = len(sheet_events)
            if n != last:
                print(f"  ({n} hit(s), {sh} sheet open(s))")
                last = n
        _save(args, hits, log, sheet_events, 0, play_classes)
        try:
            sess.detach()
        except Exception:
            pass
        return 0

    if args.no_tap:
        print("\n--no-tap: hooks loaded, no UI interaction")
        time.sleep(2)
        try:
            sess.detach()
        except Exception:
            pass
        _save(args, hits, log, sheet_events, 0, play_classes)
        return 0

    # --- walk the plans UI -------------------------------------------------
    opened = 0
    visited: set[str] = set()

    size = display_size()
    print(f"display: {size[0]}x{size[1]}")
    nodes = on_screen(dump_screen(), size)
    print(f"\nscreen: {visible_text(nodes)[:300]}")
    # Step onto the plans screen if we are still on home.
    if "get offer" in visible_text(nodes).lower():
        entry = find_taps(nodes, ["get offer", "see all plans", "explore plans", "view plans"])
        if entry:
            target = entry[0]
            label = target["text"] or target["desc"]
            print(f"tap entry: '{label}' at {target['center']}")
            tap(target)
            time.sleep(args.settle)
            print(f"screen: {visible_text(on_screen(dump_screen(), size))[:400]}")

    while opened < args.taps:
        cards = find_after_scroll(TAP_HINTS, size)
        cards = [n for n in cards
                 if (n["text"] or n["desc"]).lower() not in visited]
        if not cards:
            print("no further offer controls")
            break
        card = cards[0]
        label = card["text"] or card["desc"]
        visited.add(label.lower())
        print(f"\ntap card {opened + 1}: '{label}' at {card['center']}")
        tap(card)
        time.sleep(args.settle)

        f = focus()
        where = "sheet" if PLAY in f else ("detail" if PKG in f else "other")
        print(f"  focus[{where}]: {f.strip()[:150]}")
        opened += 1

        # Back out of whatever opened (sheet or plan detail). Never a slider gesture.
        for _ in range(3):
            if PKG in focus():
                break
            back(1, 2.0)
        time.sleep(1.5)

    # Leave the device on Google One home, nothing pending.
    ultra0.sh("shell", f"am force-stop {PLAY}")
    time.sleep(1)
    ultra0.launch_app()
    time.sleep(3)
    print(f"\nfinal focus: {focus().strip()[:160]}")

    try:
        script.unload()
    except Exception:
        pass
    try:
        sess.detach()
    except Exception:
        pass

    _save(args, hits, log, sheet_events, opened, play_classes)
    return 0


def _save(args, hits, log, sheet_events, opened, play_classes=None) -> None:
    skus = sorted({h["value"] for h in hits if h["ev"] == "sku"})
    toks = sorted({h["value"] for h in hits if h["ev"] == "token"})
    print(f"\n=== {len(skus)} product id(s), {len(toks)} offer token(s), "
          f"{len(sheet_events)} sheet open(s), {opened} card(s) tapped ===")
    for s in skus:
        print(f"  sku   {s}")
    for t in toks:
        print(f"  token {t[:60]}...({len(t)} chars)")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"playsniff-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "serial": ultra0.SERIAL,
        "cards_opened": opened,
        "sheet_opens": sheet_events,
        "skus": skus,
        "tokens": toks,
        "hits": hits,
        "play_classes": play_classes or [],
        "log": log[-500:],
    }, indent=2), encoding="utf-8")
    print(f"report: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
