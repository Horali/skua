"""Batch account sweep for the emulator.

The shipped CLI forces add=False whenever --list is used (ultra0.py:1378), so
`--list --account ...` never actually signs the account in; it just queries
whatever account is already active. This driver calls process() directly with
add=True and list_only=True: sign the account in, then read offers without any
checkout.

Usage:
    python run_accounts.py [serial]
"""
import json
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import ultra0 as u

SERIAL = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:16384"
PASSWORD = "anisikhsafais"
EMAILS = [
    "horalixscripts@gmail.com",
    "horalixscripts4@gmail.com",
    "horalixscripts6@gmail.com",
    "horalixscripts7@gmail.com",
]

u.ADB = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
u.SERIAL = SERIAL
u.ensure_root()
u.ensure_frida_client()
u.ensure_frida_server()

results = []
for email in EMAILS:
    try:
        rec = u.process(email, PASSWORD, add=True, list_only=True, plan="auto")
    except Exception as exc:  # keep the sweep going
        rec = {"email": email, "status": "exception", "error": f"{type(exc).__name__}: {exc}"}
    offers = rec.get("offers") or []
    free = [o for o in offers if str(o.get("micros")) == "0"]
    print(f"\n### {email}: status={rec.get('status')} offers={len(offers)} zero_price={len(free)}")
    for o in offers:
        print(f"    {o.get('product')} id={o.get('id')} micros={o.get('micros')} period={o.get('period')}")
    results.append({"email": email, "status": rec.get("status"),
                    "offers": offers, "errors": rec.get("errors")})

print("\n=== SWEEP SUMMARY ===")
print(json.dumps(results, indent=2, ensure_ascii=False))

