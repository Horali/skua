# skua — offer discovery & injection harness (handoff)

Scope: **this repo only** — enumerating Play Billing offers, and the Frida injections used to reach
them. Nothing here is about device rooting, carrier bundles' operational side, or unrelated tooling.

Repo: `C:\Users\child\PROJECTS\RootTest` → `github.com/Horali/skua` (private).
Work continues from commit `784fccb` (41 commits).

---

## 1. What the project is

Google Play returns subscription offers that the app UI never shows. Three distinct shapes have been
found and are now reproduced by tooling:

| Shape | Example product | Offer id | Phases |
|---|---|---|---|
| Zero-price trial, duration in the product name | `g1.2tb.ai.18months_eft` | `eft-18months` | Free/P1Y6M → Rp 309.000/P1M |
| Zero-price trial on a plain product | `g1.2tb.6months_eft` | `freetrial` | Free/P26W2D → Rp 158.000/P1M |
| Discounted intro (campaign) | `g1.2tb.ai.3months_ip_75p.acq` | `introprice` | Rp 77.000/P1M ×3 → Rp 309.000/P1M |
| Stackable variant namespace | `g1.2tb.ai.subs_variant` | `12months-eft`, `6months-eft*` | Free → paid, **do not use** |

Everything is read through a real `BillingClient` driven inside the target app's process, because Play
only answers for the calling package.

---

## 2. Setup (fresh machine)

```powershell
cd C:\Users\child\PROJECTS\RootTest\google-ai
python -m venv .venv --without-pip
python -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt
python -m pip --python .\.venv\Scripts\python.exe install zstandard websocket-client

$env:PATH="$env:LOCALAPPDATA\Android\Sdk\platform-tools;$env:PATH"
```

Dependencies beyond the upstream list: `zstandard` (decompress `.valdimodule` bundles),
`websocket-client` (`web_read.py` CDP).

Emulator: MuMu 12, instance 0, `adb connect 127.0.0.1:16384`, then `adb root`. The harness needs root
+ frida-server + `module_521.apk` staged at `/data/local/tmp/`; `ultra0.ensure_*` helpers do all three.

Smoke test, read-only:

```powershell
.\.venv\Scripts\python.exe offerwatch.py --serial 127.0.0.1:16384
```

Expected on a healthy account: ~581 candidates, 20+ offers, zero-price count > 0, no errors.

---

## 3. Tool reference

| Command | What it does | Notes |
|---|---|---|
| `offerwatch.py` | generates both SKU families, queries in 20-SKU chunks, prints every phase | `--diff reports/x.json`, `--extra-file`, `--progress` |
| `campaign_claim.py` | opens the checkout sheet for one SKU | **stops at the sheet**; no buy flag by design |
| `appoffer.py --package <pkg>` | any installed package: dex scan → candidate ids → in-process query | how Claude/Mistral/Replit/Perplexity were done |
| `billing_watch.py --package <pkg>` | hooks the *app's own* billing calls | `--lazy` (late classes), `--multiloader`, `--spawn` (hook before startup) |
| `g1_snapshot.py` | snapshots Google One campaign state | `--diff` catches an offer/entitlement landing |
| `redeem_watch.py --url <url>` | opens an offer link, classifies outcome | REDEEMABLE / UNAVAILABLE / NOT ELIGIBLE / NO-OP |
| `web_read.py` | reads the device browser's rendered page text | Chrome DevTools over `chrome_devtools_remote` |
| `gpt_skus.py`, `gpt_claim.py`, `gpt_trial_watch.py` | ChatGPT enumeration / checkout / cohort detector | `--repeat N` distinguishes per-request vs sticky |
| `claude_probe.py`, `claude_skus.py` | Claude ids and offers | |
| `spoof_boot.py` | spawn an app with spoofed `Build` | documented negative result |

Injected scripts live in `google-ai/assets/frida/`:

```
sku_probe.js           read-only query against product list (the workhorse)
sku_probe_iso.js       same, module loaded with the system classloader parent
campaign_launch.js     launch a checkout with a chosen offer token
billing.js             upstream: query + launch, zero-price preference
billing_watch*.js      hook an app's own calls (plain / lazy / multiloader)
gpt_launch.js          ChatGPT variant of campaign_launch
sheetprobe.js          read Play's purchase sheet activity
```

---

## 4. Verified results (do not redo)

| Target | Result |
|---|---|
| Google One (`scripts4`) | 21 zero-price offers; `g1.2tb.ai.18months_eft` → **free 18 months**, sheet-verified |
| Google One intro page | `one.google.com/ai` renders 75% intro pricing the home screen hides (see §5) |
| ChatGPT | 10 offers incl. Go `2k8d9f8u1pmw6` = **free 6 months**, sheet-verified |
| Duolingo | 7-day free trial, sheet-verified |
| Spotify | Play path = 3 months at list price; Spotify-direct cheaper (channel split is deliberate) |
| Claude | 4 products, **full price only**, 43 candidate ids |
| Perplexity | RevenueCat config lists `pro-trial-1w`, but Play grants base plans only |
| Mistral / Replit | Play-billed, **no offers** |
| ChatGPT Plus trial | account-sticky, 15/15 identical attempts — not per-request |

---

## 5. Mechanics that cost time (read before touching SKUs)

- **Campaign naming**: `<core>.<N>months_ip_<P>p.acq` → `introprice`. Durations 1/2/3/4 exist; percent
  values 50/75/85/90/95 exist. Ultra cores carry **no** offers at all.
- **Direct-trial naming**: `<core>.<N>months_eft` → `eft-Nmonths` (AI cores, offer id includes duration)
  or `freetrial` (base cores). This family was missed by an early sweep and then found via a
  third-party screenshot — the lesson: a generated grid covers one convention, not the catalogue.
- **The in-app intro page is `one.google.com/ai`** (the app claims `/ai`; it opens in-app, not a
  browser). It shows discounted plans the home screen hides. First thing to open on a new account.
- **Eligibility is account-state, not model**: billing attribution follows the AccountManager *primary*
  account, not the app UI. Two accounts on one device produced `ITEM_ALREADY_OWNED` on a clean account
  until the other was removed. Keep one account per device.
- **`Build` spoofing does not move eligibility** — the app never even runs the eligibility check.
- **Add-on offers** (`Get add-on`, e.g. $1.99/mo ×12) require an existing Google One membership
  (`COMMERCE_BUYFLOW_FOR_ADDONS`, `NOT_ELIGIBLE_EXISTING_MEMBER_WITH_ADDON`). Invisible to free accounts.
- **Partner/carrier offers are not Play SKUs**: one-time activation tokens
  (`serviceactivation.google.com/activate-plan/subscription/new/<token>`) or install-referrer
  campaigns carrying a `campaignId`. Neither is derivable client-side.
- **Hooking works only on stock-SDK apps.** Duolingo, Mistral, Replit, Spotify open a Play sheet while
  instrumented hooks stay silent. RevenueCat apps (ChatGPT, Perplexity) leak the whole catalogue in
  `shared_prefs` → `offeringsResponse`; read that instead of hooking.
- **`Java.choose` is broken on this ART build** (`EnsurePluginLoaded` export missing). Use class
  loader enumeration, not heap enumeration.

---

## 6. Operating rules

1. Read-only first. `--list` / query before anything that opens a sheet.
2. Never confirm a purchase. `campaign_claim.py --launch` stops at the sheet; nothing slides it.
3. One account, one device, one instrument per test. No stacking (`--stack`, `6months-eft*`).
4. No storefront games: an ID account stays ID. Region changes need a payment profile in that country.
5. Never commit `reports/`, `tmpdb/`, `tmpui/`, SDK databases, or anything with account emails/tokens —
   `.gitignore` covers them.
6. Conventional commits, no AI attribution. Push to `main` on `Horali/skua`.

---

## 7. Closed avenues (evidence in `handoff-discovery/`)

| Avenue | Why closed |
|---|---|
| Hooking Play's purchase sheet | payload is protobuf/native; all Java hooks silent (`HANDOFF-DISCOVERY` §10.3) |
| Hooking native-wrapper apps | Duolingo/Spotify bypass the stock SDK entirely |
| Device/OEM bundles (Xiaomi/Oppo/Pixel) | partner entitlement + CPID; model spoof tested, nothing fired |
| Carrier tokens (Jio) | one-time, account-bound, already-claimed and expired; also a weaker tier |
| Promo-code generation | server-issued rows; client has no key, no local validation |
| ChatGPT student/postdoc grants | verification-side, not in the app or Play catalogue |

---

## 8. Open questions — do not start these unprompted

1. **Claim the 18-month trial** on a clean account (`campaign_claim.py --product g1.2tb.ai.18months_eft
   --offer eft-18months --launch`). Operator has deferred every time.
2. **Add-on offer visibility**: burner + cheapest base plan, then check whether member add-on offers
   appear. Never on an account holding unclaimed trials.
3. **Cohort hunt**: `gpt_trial_watch.py --repeat` on other accounts.
4. **Live campaign links**: `redeem_watch.py` is ready; needs a fresh unclaimed URL.
5. **Broader app sweep**: RevenueCat-heavy consumer apps (Notion, Grammarly, Canva, Headspace) are the
   highest-yield untouched targets, because their cache hands over ids for free.

---

## 9. Environment notes

- `web_search` in the agent config is **broken** (HTTP 401 on the search endpoint). Workaround:
  `web_read.py` through the device's Chromium, which is installed but was shipped disabled — it is
  `enabled=1` now. Google's offer pages need that session-bearing browser; `web_fetch` gets redirects.
- You now have shell access on the host; none of these tools need a daemon — they are plain CLI.
- Emulator state at handoff: **shut down**. Start with
  `& "$env:ProgramFiles\Netease\MuMuPlayer\nx_main\MuMuManager.exe" control -v 0 launch`, wait for
  `is_android_started: true`, then `adb connect` + `adb root`.
- One Google account on the emulator: `horalixscripts4@gmail.com`.

---

## 10. Definition of done for this workstream

- [x] Enumerate every purchasable product for an account without a hardcoded list
- [x] Capture offer tokens per product, including campaign discounts
- [x] A diff mode that flags new zero-price or discounted offers between runs
- [x] Document which account state is required to see intro offers
- [ ] One successful claim recorded end-to-end with receipt + renewal date (operator decision)
