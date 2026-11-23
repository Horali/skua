"""g1_snapshot — capture Google One's offer/campaign state, and diff two snapshots.

Purpose: if a partner activation lands on an account (carrier vendor, device bundle),
the campaign id and entitlement details appear *somewhere* client-side afterwards.
This tool records every place that could show them, so a before/after diff exposes
what the activation actually did — including ids to replay.

Captures:
  * the SQLite RPC cache (CTA configs, URLs, campaign strings)
  * partner offer eligibility cache, if a check has ever run
  * shared_prefs keys/values mentioning campaign/offer/referrer/perk
  * current plan state as the app renders it

Read-only. No billing interaction.

Usage:
    python g1_snapshot.py --out reports/snap-before.json
    python g1_snapshot.py --out reports/snap-after.json
    python g1_snapshot.py --diff reports/snap-before.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

import ultra0

PKG = "com.google.android.apps.subscriptions.red"
DBDIR = f"/data/data/{PKG}/databases"
PREFDIR = f"/data/data/{PKG}/shared_prefs"


def adb(*a, timeout=120):
    return subprocess.run([ultra0.ADB, "-s", ultra0.SERIAL, *a],
                          capture_output=True, text=True, timeout=timeout).stdout


def pull(path: str) -> Path | None:
    tmp = Path(tempfile.gettempdir()) / Path(path).name
    if tmp.exists():
        tmp.unlink()
    adb("pull", path, str(tmp))
    return tmp if tmp.exists() else None


def rpc_cache() -> dict:
    out = {"databases": [], "rows": []}
    listing = adb("shell", f"ls {DBDIR} 2>/dev/null")
    for line in listing.splitlines():
        name = line.strip()
        if not name or name.endswith(("-wal", "-shm", "-journal")):
            continue
        out["databases"].append(name)
        if not name.startswith("g1_sdk_database"):
            continue
        local = pull(f"{DBDIR}/{name}")
        if not local:
            continue
        try:
            con = sqlite3.connect(local)
            for key, blob, typ in con.execute("select cacheKey, data, cacheType from rpc_cache"):
                txt = " ".join(s.decode("latin1") for s in re.findall(rb"[ -~]{5,200}", blob or b""))
                out["rows"].append({"db": name, "key": key, "type": typ, "strings": txt[:400]})
            con.close()
        except Exception as exc:
            out["rows"].append({"db": name, "error": f"{type(exc).__name__}: {exc}"})
    return out


def partner_cache() -> dict:
    out = {"exists": False, "tables": {}, "raw_strings": []}
    listing = adb("shell", f"ls {DBDIR} 2>/dev/null | grep -i partner")
    if not listing.strip():
        return out
    out["exists"] = True
    for line in listing.splitlines():
        name = line.strip()
        local = pull(f"{DBDIR}/{name}")
        if not local:
            continue
        blob = local.read_bytes()
        out["raw_strings"] = sorted({s.decode("latin1") for s in re.findall(rb"[ -~]{5,120}", blob)})[:200]
        try:
            con = sqlite3.connect(local)
            tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            for t in tabs:
                rows = list(con.execute(f'select * from "{t}" limit 20'))
                out["tables"][t] = [str(r)[:300] for r in rows]
            con.close()
        except Exception:
            pass
    return out


def prefs_hits() -> dict:
    keys = ("campaign", "offer", "referrer", "perk", "eft", "partner", "promo")
    out = {}
    for k in keys:
        raw = adb("shell", f"grep -rhao '[A-Za-z0-9_.:=%/-]*{k}[A-Za-z0-9_.:=%/-]*' {PREFDIR} 2>/dev/null | sort -u | head -40")
        vals = [v.strip() for v in raw.splitlines() if v.strip()]
        if vals:
            out[k] = vals
    return out


def render_state() -> str:
    adb("shell", f"uiautomator dump /sdcard/snap.xml")
    xml = adb("shell", "cat /sdcard/snap.xml") or ""
    return " | ".join(t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip())[:600]


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot Google One offer/campaign state (read-only)")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--out", default=None)
    ap.add_argument("--diff", default=None, help="compare against a previous snapshot json")
    args = ap.parse_args()

    ultra0.ADB = os.environ.get(
        "ADB_EXE",
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
    ultra0.SERIAL = args.serial
    ultra0.ensure_root()

    snap = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rpc": rpc_cache(),
        "partner": partner_cache(),
        "prefs": prefs_hits(),
        "screen": render_state(),
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(snap, indent=2), encoding="utf-8")
        print(f"snapshot: {args.out}")

    print(f"rpc rows      : {len(snap['rpc']['rows'])}")
    print(f"partner cache : {'present' if snap['partner']['exists'] else 'absent'}")
    print(f"pref groups   : {list(snap['prefs'].keys()) or 'none'}")

    if args.diff:
        old = json.loads(Path(args.diff).read_text(encoding="utf-8"))
        old_keys = {(r.get('db'), r.get('key')) for r in old["rpc"]["rows"]}
        new_rows = [r for r in snap["rpc"]["rows"] if (r.get('db'), r.get('key')) not in old_keys]
        print(f"\n=== diff vs {args.diff} ===")
        print(f"new/changed rpc rows: {len(new_rows)}")
        for r in new_rows[:10]:
            print("  +", r.get("type"), "|", r.get("strings", "")[:160])
        po, pn = old["partner"], snap["partner"]
        if pn["exists"] and not po["exists"]:
            print("partner eligibility cache APPEARED — an eligibility check ran")
            for s in pn["raw_strings"][:15]:
                print("   ", s)
        if old.get("screen") != snap.get("screen"):
            print("screen changed:")
            print("  was:", old.get("screen", "")[:200])
            print("  now:", snap.get("screen", "")[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
