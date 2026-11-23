# Google AI Pro 12-Month Offer â€” Operator Handoff

Everything needed to reproduce **one successful claim** of the hidden `12months-eft` Google AI Pro (5 TB) trial through the Play Billing path, using a rooted Android emulator on Windows.

Written from a session that actually completed: trial granted 2026-11-23, Rp 0 today, Rp 309.000/month from 2027-11-23. All error strings below are real, captured from that run.

> **Read this first.** This is a ToS violation on Google Play. Google has been formally asked (2026-11-10 and 2026-11-18, on Google's own developer forum) to revoke these memberships and suspend accounts that abuse the flow. Outcomes observed in the wild range from the trial being clawed back, to refunds, to full account bans and blocked Cloud services. Use a **burner account**, never a primary one. Nothing here is Google-sanctioned.

---

## 1. What the exploit actually is (so you can adapt when it changes)

Not a memory-corruption exploit. There is no kernel bug, no privilege escalation.

Google Play Billing returns **subscription offers that the Google One UI never displays**. Those offers include zero-priced introductory phases (`eft-1month` â€¦ `eft-12month`). They live on a *different product ID* than the one the app's own "Upgrade" button requests.

```
g1.ai.pro                 full price only   <- what the app UI actually queries
g1.play.ai.pro            carries eft-*     <- promotional namespace
g1.2tb.ai.subs_variant    carries 12months-eft / 6months-eft / 6months-eft-2
                                              / 6months-eft-ss-2026
```

So the "exploit" is: attach to the Google One process, load a real `BillingClient` into it, query the **promotional SKU**, read the offer tokens Play hands back, and call `launchBillingFlow()` with the $0 offer's token.

**This means:** if Google renames the SKU, the tool keeps working as long as you query the *right* SKU. If Google stops returning zero-phase offers for ineligible accounts, nothing client-side helps. Eligibility is decided server-side.

---

## 2. Prerequisites

### Host (Windows)

| Item | Version used | Notes |
|---|---|---|
| Python | 3.12.6 | `python` on PATH |
| Git | 2.48+ | |
| Android Platform-Tools | 37.0.1+ | `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` |
| MuMuPlayer 12 (NX) | 6.8.16 / engine MUMU15 | Android 15 image, `SM-G9980` spoof, root toggle |
| VT-x / Hyper-V | enabled | MuMu needs it; Hypervisor present is fine |

### Account (this is where most attempts fail)

The Play account must satisfy **all** of these or Play simply returns no `eft-*` offers:

- [ ] **Payment method attached in Play** â€” required. A brand-new account without one gets full-price only. GoPay worked (Indonesia); a card also works.
- [ ] **No active Google One / AI Pro subscription** on that account (an existing sub removes trial offers from the query response).
- [ ] **Play country** where the promo exists â€” verified working: **Indonesia (IDR)**.
- [ ] Account signed into **Play Store AND Google One** on the emulator (same account).
- [ ] You can receive the account's email (renewal reminder + receipt land there).

### What you do NOT need

- Physical rooted phone. This runs entirely on the emulator.
- Unlocked bootloader, Magisk, KernelSU.
- The account password unless Play asks for re-auth at purchase time (it often does).
- Stacking. One claim is the safe play; stacking is what got the reported accounts banned.

---

## 3. Repo

```powershell
git clone https://github.com/hoangsvit/google-ai.git
```

- Upstream: `gylive/google-ultra` (original technique)
- This repo: Windows TUI + CLI wrapper, Frida billing hook, docs
- **Pin used in the successful run:** `5e07e5fd61ffd46ba8dfb539513fe31db653ff45` (2026-11-22)
- Known-good archived copy: `google-ai-backup-<date>.zip` alongside this document

Key files:

| File | Role |
|---|---|
| `ultra0.py` | engine: ADB, root, frida deploy, offer query, checkout, account handling |
| `assets/frida/billing.js` | the injected script: `DexClassLoader` â†’ `BillingClient` â†’ offers â†’ `launchBillingFlow` |
| `query_sku.py` | standalone read-only query |
| `tui.py`, `tui_core.py`, `run-all.ps1` | dashboard + Windows launcher (optional; CLI is enough) |
| `docs/DETAILED-GUIDE.md`, `docs/ORIGINAL-STEPS.md` | upstream docs |

---

## 4. Host setup (exact, including the traps)

### 4.1 Python venv â€” the sandbox trap

`python -m venv .venv` may fail with `ensurepip` PermissionError when temp dirs are restricted. Use:

```powershell
python -m venv .venv --without-pip
python -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt -r requirements-tui.txt
```

`requirements.txt` = `frida==16.5.9`, `requirements-tui.txt` = `textual==8.2.8`.

If the 33 MB frida wheel stalls (PyPI can crawl), use a mirror:

```powershell
python -m pip --python .\.venv\Scripts\python.exe install --no-cache-dir `
  -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt -r requirements-tui.txt
```

Verify:

```powershell
.\.venv\Scripts\python.exe -c "import frida,textual;print(frida.__version__, textual.__version__)"
# expect: 16.5.9 8.2.8
```

### 4.2 ADB

The engine looks for `adb` on PATH and **will not find it otherwise**:

```powershell
$env:PATH="$env:LOCALAPPDATA\Android\Sdk\platform-tools;$env:PATH"
```

When driving it from a script that imports `ultra0`, `ultra0.ADB` resolves to `None` â€” set it explicitly:

```python
import ultra0 as u, os
u.ADB    = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
u.SERIAL = "127.0.0.1:16384"
```

### 4.3 MuMuPlayer

Install from the official site. Then, **before first launch**:

```powershell
$mm = "C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe"
& $mm setting -v 0 -k root_permission -val true
& $mm control -v 0 launch     # ~40 s to boot
& $mm info -v 0               # wait for "is_android_started": true
```

Then root the adb session:

```powershell
adb connect 127.0.0.1:16384
adb -s 127.0.0.1:16384 root
adb -s 127.0.0.1:16384 shell id     # must show uid=0(root)
```

`adb root` is all the engine needs â€” it does not require `su`.

### 4.4 MuMu startup failure â€” `VERR_OLE_FAILURE` (very common)

Symptom, in `vms\MuMuPlayerGlobal-15.0-0\logs\vboxmanager.log`:

```
UUID {caaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaac} of the medium
  ...nx_device\15.0\vms\MuMuPlayerGlobal-15.0-base\system.vdi
does not match the value {f3c5580a-4edb-517c-0000-100000000000}
stored in the media registry ('C:\Users\<you>\.MUMUNX\VirtualBox.xml')
```

"Repair" fixes it for one launch, then MuMu regenerates the `.nemu` and it breaks again. Editing the `.nemu` does not stick.

Working fix â€” rewrite the image header UUID, elevated, with the hypervisor service stopped:

```powershell
# 1. stop service + kill players (needs admin)
Get-Service MuMuNxSup | Stop-Service -Force
Get-Process | ? { $_.Name -match "MuMu|nemu|VBox" } | % { try { $_.Kill() } catch {} }

# 2. rewrite the vdi UUID
& "C:\Program Files\MuMuNxVbox\Hypervisor\VBoxManage.exe" internalcommands sethduuid `
    "C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\vms\MuMuPlayerGlobal-15.0-base\system.vdi" `
    "f3c5580a-4edb-517c-0000-100000000000"

# 3. clear the stale registry, restart service
Remove-Item "$env:USERPROFILE\.MUMUNX" -Recurse -Force
Start-Service MuMuNxSup
```

Then `MuMuManager.exe control -v 0 launch` boots normally.

### 4.5 Google apps inside the emulator

- Play Store is preinstalled.
- **Google One is not** â€” install `com.google.android.apps.subscriptions.red` from Play.
- Sign into both with the burner, then confirm from the host:

```powershell
adb -s 127.0.0.1:16384 shell "dumpsys account | grep 'Account {'"
```

---

## 5. The run

### 5.1 Read-only first (mandatory)

```powershell
cd google-ai
$env:PATH="$env:LOCALAPPDATA\Android\Sdk\platform-tools;$env:PATH"
.\.venv\Scripts\python.exe ultra0.py --list --plan pro12 --serial 127.0.0.1:16384
```

**`--plan pro12` is not optional.** Without it the engine queries the Ultra SKUs and reports `no_trial` even when the Pro trial is available:

```python
# ultra0.py build_js()
default     : PRODUCTS=["g1.play.20tb","g1.play.ai.pro","g1.30tb"]      # Ultra
--plan pro12: PRODUCTS=["g1.2tb.ai.subs_variant"]; PREFER="12months-eft"
```

Healthy output:

```
offer 12months-eft        â†’ 0 (P1Y)
offer 6months-eft         â†’ 0 (P6M)
offer 6months-eft-2       â†’ 0 (P6M)
offer 6months-eft-ss-2026 â†’ 0 (P6M)
offer null                â†’ 309000000000 (P1M)
Selected Google Play offer ID: 12months-eft
```

What failure looks like:

```
offer null â†’ 1579000000000 (P1M)      # only base plans
errors: [{ "ev": "no_trial" }]        # -> account ineligible or wrong SKU
```

Rule out the SKU first (are you on `--plan pro12`?), then the account (payment method? active sub? country?).

### 5.2 Checkout

```powershell
.\.venv\Scripts\python.exe ultra0.py --plan pro12 `
  --account "burner@example.com" --no-add --serial 127.0.0.1:16384
```

- `--account` + `--no-add` = do not add a new account, verify/switch to this one.
- The engine opens Play's sheet, then validates today's total and trial duration.
- If it cannot verify both, it **leaves the sheet open and does not tap Subscribe** and returns `today_price_unverified`. That is correct behaviour â€” verify by eye, then complete it manually.

Expected sheet:

```
Google AI Pro (5 TB) Â· Google One
Starting today          â†’ 12-month free trial
Starting 23 Nov 2027    â†’ Rp 309.000/month + tax
You won't be charged if you cancel before 23 Nov 2027
GoPay: â€¢â€¢â€¢â€¢8271
[ Slide to subscribe ]
```

Complete it: slide right on the pill. Then:

1. Google may ask for the **account password** ("Enter your password for â€¦"). The red "No internet connection" text on that screen is usually the auth call failing, not real connectivity â€” retry once, and if it repeats: `adb shell am force-stop com.android.vending`, reopen and slide again.
2. Device clock skew breaks this auth. Check `adb shell date` against host time.
3. After success: **"Payment successful"** then a "purchase verification" dialog â†’ choose **All payment methods** â†’ OK. It only affects future purchases, but you want verification on an account holding a live sub.

### 5.3 Verify (do not trust the UI alone)

- Google One home flips from `0 GB of 5 GB` to a plan card.
- Gemini opens with the Pro model picker (Gemini 4 Neon, Claude Opus, etc.).
- Play sends the receipt email: subject "Thank you", item `Google AI Pro (5 TB)`, total `Rp 0`, first charge date.
- Re-running `--list --plan pro12` should no longer select `12months-eft` for that account.

---

## 6. Problems encountered, and what they actually mean

| Symptom | Cause | Fix |
|---|---|---|
| `ADB not found` | adb not on PATH | prepend platform-tools to PATH |
| `device not found` / wrong device | multiple devices online (phone + emulator) | always pass `--serial 127.0.0.1:16384` |
| `no_trial` with base prices | queried Ultra SKUs, not the Pro SKU | use `--plan pro12` |
| `no_trial` on the right SKU | account ineligible: no payment method / active sub / wrong country | fix account, not code |
| `Root is unavailable` | `u.ADB` is `None`, or adbd not root | set `u.ADB`, run `adb root`, check `shell id` |
| `Google One did not start` | app force-stopped or sheet left open | `am force-stop` both Play + Google One, relaunch |
| `today_price_unverified` | engine could not parse total/duration | inspect sheet manually, then slide |
| sheet goes black after slide | GoPay/Play auth handoff | wait, re-open Play â†’ Subscriptions to see state |
| `uiautomator dump` â†’ `null root node` | Compose-based apps | use screenshots + pixel math instead |
| Taps land on the wrong element | Compose renders scaled vs dump coordinates | derive factor from a known-hit control; screenshot and measure |
| Frida `Java.choose` / `EnsurePluginLoaded` error on API 35 x86_64 | known ART issue | `--activity-method thread` |
| Google Play install verification blocks sideloads | Play Protect | `settings put global verifier_verify_adb_installs 0` (restore to 1 after) |
| Banking app crashes after rooting the *phone* | app scans installed packages (KSU/root APKs) | out of scope here â€” use the emulator |

---

## 7. Hard rules for any agent running this

1. **Never run without `--list` until the read-only step shows a `micros == 0` offer.** Otherwise you are opening a paid checkout.
2. **Never use `--force`.** It bypasses account checks and does not create eligibility.
3. **Do not stack** (`--stack`, `6months-eft*`, steps 3â€“5) on a fresh claim. Reported stackers were banned; single claims were at most clawed back.
4. **One account, one device, one payment instrument.** Multiple accounts on the same emulator share one GSF/Android ID â€” that is the clustering signal Google asked to be allowed to act on.
5. **Do not enable wireless/other adb surfaces** you do not need.
6. **Restore anything you changed on a physical phone**: animation scales, `verifier_verify_adb_installs`, root packages.
7. **Keep the burner's recovery email reachable.** If the account is lost, the subscription cannot be cancelled and will bill at renewal.

---

## 8. Risk model (what "banned" means, in order of likelihood)

1. **Trial revoked / reverted to free tier** â€” most common. No account damage. Refund line may appear.
2. **Account disabled** â€” sign-in returns *"Your Google Account has been disabled"*; Gmail/Drive/Photos/Play library all die; appeal-only recovery. Reserved for pattern abuse (many accounts, shared card, scripted registration).
3. **Account disabled + other services blocked** â€” observed once; the account's Google Cloud access was cut separately.

Observed timeline from a public case: banned â†’ appeal â†’ restored â†’ clawed back two days later.

Mitigation is structural, not technical: burner identity, isolated device, payment instrument used nowhere else, no batch runs.

---

## 9. If this path dies â€” legitimate alternatives that still exist

- **Coursera**: enroll in any Google Career Certificate â†’ 3 months AI Pro free (reported working on existing accounts, Nov 2026).
- **Student verification** (SheerID): 12 months free, requires real student status.
- **Xiaomi 17T / 17T Pro**: official 3-month trial, redeemed in the Gemini/Google One app on the device. The public offer slug `one.google.com/offer/xiaomi_3month_aip_trial` is **per-account and reports "no longer available"** for accounts that never activated a device â€” spoofing `ro.product.*` does **not** work; the entitlement is server-side.
- **Hardware bundles**: Pixel / Chromebook / ASUS laptop / Jio (India).

---

## 10. Command cheat-sheet

```powershell
# emulator lifecycle
& $mm control -v 0 launch
& $mm info -v 0 | findstr android_started
& $mm main close
& $mm control -v 0 shutdown

# adb
adb connect 127.0.0.1:16384
adb -s 127.0.0.1:16384 root
adb -s 127.0.0.1:16384 shell id
adb -s 127.0.0.1:16384 shell "dumpsys account | grep 'Account {'"

# read-only offers (the important one)
.\.venv\Scripts\python.exe ultra0.py --list --plan pro12 --serial 127.0.0.1:16384

# checkout
.\.venv\Scripts\python.exe ultra0.py --plan pro12 --account "burner@example.com" --no-add --serial 127.0.0.1:16384

# reports
type ultra0-report\current.json
```

---

## 11. Notes for a DeepSeek-driven agent

- The single highest-value instruction: **`--plan pro12` = `g1.2tb.ai.subs_variant`.** The default query path cannot find the Pro trial. Dozens of runs concluded "no offers" before this was found.
- Do not invent SKUs. If the offer disappears, enumerate: hook `JSONObject.put` / `Bundle.putString` for `productId`, dump `/data/data/com.android.apps.subscriptions.red/databases/StoragePlansDataCache.db`, and batch-probe name variants â€” Play ignores invalid IDs and returns only real ones.
- Treat `launchBillingFlow` code `0` as "sheet opened", never as "subscribed".
- Verify everything from three sources: Play receipt email, Google One plan state, and a fresh `--list` (the offer should stop being selected).
- Eligibility failures are not code failures. Do not "fix" them by forcing, stacking, or retrying with other accounts on the same device.

---

## 12. offerwatch â€” the discovery harness

Read-only enumerator that keeps working when Google renames SKUs.

```powershell
cd google-ai
.\.venv\Scripts\python.exe offerwatch.py --serial 127.0.0.1:16384
.\.venv\Scripts\python.exe offerwatch.py --diff reports\offerwatch-<older>.json
```

What it does:
1. root + frida-server + billing module + Google One launch (reuses ultra0 helpers)
2. scrapes `g1.*` ids out of `/data/data/com.android.apps.subscriptions.red/databases/StoragePlansDataCache.db`
   and `shared_prefs`, then generates name variants around those roots
3. injects `assets/frida/sku_probe.js`: real `BillingClient` inside Google One, batched
   `queryProductDetailsAsync` (20 SKUs per call; Play ignores invalid IDs)
4. prints every offer with all pricing phases, flags `micros == 0`, saves JSON to `reports/`

Output from the first working run (2026-11-23, account already holding the 12-month trial):

```
g1.2tb.ai.subs_variant
    id=12months-eft            first=Free  P1Y        phases=2   <== ZERO PRICE
    id=6months-eft             first=Free  P6M        phases=2   <== ZERO PRICE
    id=6months-eft-2           first=Free  P6M        phases=2   <== ZERO PRICE
    id=6months-eft-ss-2026     first=Free  P6M        phases=2   <== ZERO PRICE
    id=null                    first=Rp 309.000 P1M   phases=1

g1.2tb.subs_variant
    id=3months-eft             first=Free  P13W1D     phases=2   <== ZERO PRICE
    id=6months-eft             first=Free  P6M        phases=2   <== ZERO PRICE
    id=null                    first=Rp 158.000 P1M   phases=1

g1.play.2tb.ai
    id=eft-3mo                 first=Free  P3M        phases=2   <== ZERO PRICE
    id=null                    first=Rp 309.000 P1M   phases=1
```

Two things that run proved:
- **`g1.play.2tb.ai` carries `eft-3mo`** â€” a 3-month zero-price offer that is *not* the
  Xiaomi device entitlement (that slug is per-account and reports "no longer available").
- `g1.2tb.subs_variant` carries `3months-eft` (P13W1D) alongside its own 6-month offers.

Notes and limits:
- Zero-priced offers stay visible even after a subscription exists â€” **do not treat a listed
  offer as permission to stack.** `--stack` is the step that got reported accounts banned.
- Device-side discovery returned 0 ids on this build (DB path/lock); seed + generated
  variants covered it. If discovery keeps returning 0, extend `SEED_SKUS`/`ROOTS` in the script.
- `setProductList()` needs a `java.util.ArrayList`, not a Java array â€” that was the one
  non-obvious bug in the probe.

### 12.1 idcapture â€” UI sweep + ID sniffer (partial)

`python idcapture.py --serial 127.0.0.1:16384 --max-taps 12`

Attaches `assets/frida/id_sniffer.js`, walks the plans UI with uiautomator + taps, and logs
any product id it sees on the way.

What it proved:
- The plans screen lists **Google AI Pro (5 TB)**, **Google AI Pro (10 TB)** and **Google AI Ultra**,
  plus a live banner: *"Member exclusive: Save up to 50% off Google AI plans"* /
  *"Get our best Black Friday deal on selected plans."*
- New SKUs confirmed by querying afterwards: **`g1.10tb`** (Rp 790.000/mo) and
  **`g1.5tb`** (Rp 309.000/mo).

What it did **not** do: capture ids from the UI. Hooking `JSONObject.put`, `Bundle.putString`,
`Intent.putExtra` yields nothing, and the `BillingClient` builder classes are **not on Google One's
own classpath** â€” that SDK only exists in the copy injected via `DexClassLoader`
(`ClassNotFoundException` for `QueryProductDetailsParams$Product$Builder` from the app loader).

Conclusion: the app hands the SKU to Play through **Play services / protobuf**, not through in-app
JSON or Builder calls. To capture ids properly the next iteration must hook inside
`com.google.android.gms` (or the AIDL/Intent that carries the request), not inside Google One.

Practical fallback that already works: brute-force name variants with `offerwatch.py`.
