"""claude_probe — find Claude's Play product ids from the installed app.

Two passes, both read-only, neither needs the app running:

  1. APK/dex scan — pull every split, parse dex strings for product-id shaped
     identifiers (monthly/annual/pro/max/subscription). Claude, like ChatGPT,
     may keep SKUs in a config/cache rather than hardcode them.
  2. App data scan — shared_prefs and files for RevenueCat/Play product ids,
     the way ChatGPT's offerings JSON was recovered from
     com_revenuecat_purchases_preferences.xml.

If pass 1 finds ids, they get queried through Play from inside the app's own
process by claude_skus.py (Play only returns products for the calling package).

Usage:
    python claude_probe.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path

import ultra0

PKG = "com.anthropic.claude"
WORK = Path("tmpdb/claude_apks")

# Product-id shaped: lowercase, dots/underscores, containing a plan word.
RE_CANDIDATE = re.compile(r"^[a-z][a-z0-9_.]{2,48}$")
PLAN_WORDS = ("month", "annual", "year", "pro", "max", "plus", "sub", "tier", "plan", "credit")
NOISE = ("android", "google", "androidx", "com.google", "kotlin", "okhttp", "retrofit",
         "firebase", "crashlytics", "gms", "play", "support", "material")


def adb(*args: str, timeout: int = 120) -> str:
    return subprocess.run([ultra0.ADB, "-s", ultra0.SERIAL, *args],
                          capture_output=True, text=True, timeout=timeout).stdout


def pull_splits() -> list[Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    out = []
    for line in adb("shell", f"pm path {PKG}").splitlines():
        p = line.strip().replace("package:", "")
        if not p:
            continue
        local = WORK / Path(p).name
        if not local.exists():
            adb("pull", p, str(local))
        if local.exists():
            out.append(local)
    return out


def uleb128(buf: bytes, off: int):
    result = shift = 0
    while True:
        b = buf[off]
        off += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, off
        shift += 7


def dex_strings(blob: bytes) -> list[str]:
    if blob[:4] != b"dex\n":
        return []
    size, off = struct.unpack_from("<II", blob, 0x38)
    out = []
    for i in range(size):
        try:
            sidx = struct.unpack_from("<I", blob, off + i * 4)[0]
            _, so = uleb128(blob, sidx)
            end = blob.index(b"\x00", so)
            out.append(blob[so:end].decode("utf-8", "replace"))
        except Exception:
            continue
    return out


def scan_apks(apks: list[Path]) -> dict[str, list[str]]:
    hits: dict[str, set[str]] = {}
    for apk in apks:
        try:
            z = zipfile.ZipFile(apk)
        except Exception:
            continue
        for name in z.namelist():
            if not name.endswith(".dex"):
                continue
            try:
                strings = dex_strings(z.read(name))
            except Exception:
                continue
            for s in strings:
                low = s.lower()
                if not RE_CANDIDATE.match(low):
                    continue
                if any(n in low for n in NOISE):
                    continue
                if any(w in low for w in PLAN_WORDS):
                    hits.setdefault(s, set()).add(f"{apk.name}:{name}")
    return {k: sorted(v) for k, v in hits.items()}


def scan_appdata() -> list[str]:
    found = []
    for d in ("shared_prefs", "files", "databases"):
        out = adb("shell", f"ls /data/data/{PKG}/{d} 2>/dev/null")
        for line in out.splitlines():
            n = line.strip()
            if not n or " " in n:
                continue
            for f in ("shared_prefs", "files", "databases"):
                pass
        # grep the directory for id-shaped tokens
        raw = adb("shell",
                  f"grep -rhoE '[a-z][a-z0-9_.]{{3,40}}' /data/data/{PKG}/{d} 2>/dev/null | sort -u")
        for tok in raw.splitlines():
            low = tok.strip().lower()
            if any(w in low for w in ("month", "annual", "pro_", "_pro", "max", "subscription")):
                found.append(low)
    return sorted(set(found))[:200]


def main() -> int:
    ap = argparse.ArgumentParser(description="Locate Claude Play product ids (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial
    ultra0.ensure_root()

    if not adb("shell", f"pm path {PKG}").strip():
        raise SystemExit(f"{PKG} is not installed — install it from Play and sign in first")

    apks = pull_splits()
    print(f"splits: {[a.name for a in apks]}")
    hits = scan_apks(apks)
    print(f"\n=== {len(hits)} product-id-shaped string(s) in dex ===")
    for s in sorted(hits)[:80]:
        print(f"  {s}")

    print("\n=== app-data candidates ===")
    data = scan_appdata()
    for s in data[:60]:
        print(f"  {s}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "claude-probe.json"
    path.write_text(json.dumps({"dex": hits, "appdata": data}, indent=2), encoding="utf-8")
    print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
