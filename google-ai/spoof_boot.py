"""Spawn Google One suspended, apply the Build spoof, resume, then hold.

Lets the app boot with a spoofed device identity so any startup-time device check
sees the Pixel identity rather than Samsung.
"""
import json
import os
import time

import frida

import ultra0

ultra0.ADB = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
ultra0.SERIAL = "127.0.0.1:16384"
PKG = "com.google.android.apps.subscriptions.red"

ultra0.sh("forward", "tcp:27042", "tcp:27042")
ultra0.sh("shell", f"am force-stop {PKG}")
time.sleep(2)

dev = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
pid = dev.spawn([PKG])
print("spawned", pid, flush=True)
sess = dev.attach(pid)
sc = sess.create_script(open("assets/frida/spoof_build.js").read())
sc.on("message", lambda m, d: print(" ", json.dumps(m.get("payload") or {})[:150], flush=True))
sc.load()
time.sleep(3)
dev.resume(pid)
print("resumed with spoof", flush=True)
time.sleep(90)
