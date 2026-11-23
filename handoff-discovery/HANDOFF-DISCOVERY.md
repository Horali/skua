# Discovery Work â€” Continuation Handoff

**Purpose of this document:** pick up the *offer discovery* work, not the original claim. The 12-month Pro trial is already claimed and working; this file is about finding **what else exists** â€” other tiers, other campaigns, other offers â€” and building a tool that keeps finding them after Google renames things.

Companion document: `HANDOFF.md` (full setup, the claim flow, troubleshooting, risk model). Read that first if the emulator or the toolkit isn't set up yet.

Session date: 2026-11-23, ~01:00â€“03:30 local.

---

## 1. State of play

| Thing | Status |
|---|---|
| Pro 12-month trial (`12months-eft`) | **Claimed and active** on `burner@example.com`, expires 2027-11-23 |
| MuMu emulator | Working, root via `adb root`, boot ~40 s |
| `offerwatch.py` | **Working** â€” sweeps SKUs, prints every offer, saves JSON |
| `assets/frida/sku_probe.js` | Working (the probe injected by offerwatch) |
| `idcapture.py` + `id_sniffer.js` | **Partial** â€” UI walker works, ID capture does not (see Â§6) |
| `ultra0.py` / repo engine | Working, pinned at commit `5e07e5f` |

Key insight already banked: the promotional offers live on product IDs the Google One UI never queries, and the engine's default plan queries the **Ultra** SKUs. `--plan pro12` is the only flag that asks for the Pro SKU. That cost a whole session to find; don't re-learn it.

---

## 2. Verified catalogue (this account, 2026-11-23)

Account holds an active Pro subscription, so intro offers for *other* tiers may be suppressed â€” treat this as a floor, not a ceiling.

| Product | Offer ID | First phase | Period | Phases |
|---|---|---|---|---|
| `g1.100gb` | â€” | (only ID hardcoded in the APK; never returned) | | |
| `g1.2tb` | â€” | Rp 158.000 | P1M | 1 |
| `g1.2tb.ai` | â€” | Rp 309.000 | P1M | 1 |
| `g1.5tb` | â€” | Rp 309.000 | P1M | 1 |
| `g1.10tb` | â€” | Rp 790.000 | P1M | 1 |
| `g1.20tb` | â€” | Rp 1.579.000 | P1M | 1 |
| `g1.play.20tb` | â€” | Rp 1.579.000 | P1M | 1 |
| `g1.ai.pro` | â€” | Rp 3.399.000 | P1M | 1 |
| `g1.play.ai.pro` | â€” | Rp 3.399.000 | P1M | 1 |
| **`g1.2tb.ai.subs_variant`** | `12months-eft` | **free** | P1Y | 2 |
| | `6months-eft` | **free** | P6M | 2 |
| | `6months-eft-2` | **free** | P6M | 2 |
| | `6months-eft-ss-2026` | **free** | P6M | 2 |
| **`g1.2tb.subs_variant`** | `3months-eft` | **free** | P13W1D | 2 |
| | `6months-eft` | **free** | P6M | 2 |
| **`g1.play.2tb.ai`** | `eft-3mo` | **free** | P3M | 2 |

Tiers that exist as *UI cards* but were not found by querying: **Google AI Ultra (20 TB)** and **Ultra 30 TB** â€” only base prices came back, no intro phase.

---

## 3. Campaign found live in the UI (not visible to Billing)

The Google One plans screen currently shows, for this account:

- *"Member exclusive: Save up to 50% off Google AI plans"*
- *"Get our best Black Friday deal on selected plans. Terms apply."*
- Cards: **Google AI Pro (5 TB)**, **Google AI Pro (10 TB)**, **Google AI Ultra**

A screenshot from another account showed **Google AI Ultra (20 TB) at Rp 159.000/month** from today, then **Rp 1.579.000/month from 21 Feb 2027** â€” i.e. ~90% off for ~3 months, with the wording **"intro price"**, not "free trial".

That discount never appeared in any Billing offer response for this account. Conclusion so far: Black Friday is a **campaign applied at the UI/checkout layer**, and/or it is suppressed because this account already holds a subscription. Next session should test the same SKU set on a **clean account** (Â§7).

---

## 4. What to build next, ranked

### A. Hook Play Store (`com.android.vending`), not Google One  â† highest value

`idcapture.py` failed because billing classes aren't on Google One's classpath:

```
ClassNotFoundException: com.android.billingclient.api.QueryProductDetailsParams$Product$Builder
  on path: DexPathList[[zip file ".../com.google.android.apps.subscriptions.red/base.apk"]]
```

The purchase sheet runs in Play's process (`com.android.vending/com.google.android.finsky.billing.acquire.SheetUiBuilderHostActivity` â€” confirmed via `dumpsys window | grep mCurrentFocus`). So the product ID and offer token transit **there**.

Implementation sketch:
1. `frida.get_device_manager().add_remote_device("127.0.0.1:27042")`, find pid whose name contains `com.android.vending`.
2. Attach, hook in that process:
   - `com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder.setProductDetails`
   - `QueryProductDetailsParams$Product$Builder.setProductId`
   - `android.content.Intent.putExtra` (String,String) as a fallback
   - log every string matching `^g1\.[A-Za-z0-9_.]+$`
3. Drive one real checkout: tap **"Get discount"** on a plan card (this opens the sheet but does not purchase). Capture the ID + offer token, then press back.
4. Repeat for each plan card, including Ultra.

Note: GMS may resist attach (protected process). If `attach` throws, try spawning Google One with frida and hooking before Play forks â€” or fall back to (B).

### B. Brute-force with campaign suffixes

Only *product* names have been varied so far. Real promo tokens carry acquisition suffixes â€” the NodeLoc writeup shows `g1.100gb.3months_ip_85p.acq`.

Extend `offerwatch.py` candidate generation:
```
cores  = g1.2tb.ai, g1.5tb, g1.10tb, g1.20tb, g1.30tb, g1.play.20tb, g1.play.2tb.ai
suffix = .subs_variant, .subs, .play, .ai, .ai.subs_variant
campaign = .ip_85p.acq, .ip_90p, .3months_ip_85p.acq, .12months_ip_50p.acq,
           .intro, .promo, .blackfriday, .bf2026
```
Cartesian product stays under Play's 20-per-query limit when chunked (the probe already chunks).

### C. Scrape Play Store's plan page (displayed prices)

Deep link: `am start -a android.intent.action.VIEW -d "https://play.google.com/store/account/subscriptions"`.
`uiautomator dump` on that screen lists plans, prices and intro text **as rendered** â€” catches campaign pricing that Billing hides. Parse text nodes for `Rp`, `/month`, `intro`, and the plan names.

### D. Hook GMS (last resort)

If Play's process blocks attach, the SKU passes through `com.google.android.gms` (billing service). Same hook set, different pid. Expect more resistance.

---

## 5. Account strategy â€” read before testing

**Does the current account work for other plans?**

- **No** for anything with an *intro* offer. An active Google One subscription removes intro offers from the `queryProductDetailsAsync` response â€” documented in the NodeLoc writeup ("the server directly removed the trial Offer list when calculating eligibility") and consistent with everything observed tonight.
- **Yes** for observing *base prices* and *upgrade paths* (subscription updates via `--stack` / `BillingFlowParams.subscriptionUpdateParams`), because those don't need intro eligibility.
- **Current account can still be used** to enumerate the catalogue (which SKUs exist, what they cost) â€” it just won't show you intro pricing that a new subscriber would receive.

**For intro/discount testing you need a clean account:**
- no active Google One / AI Pro subscription
- payment method attached (GoPay worked)
- signed into Play **and** Google One on the emulator
- same Play country (IDR)

Signing a second account into the emulator is the friction point. `ultra0.add_account()` automates email â†’ password but stalls on Google's ToS/consent screens and any 2FA â€” those need a human, or a driver that recognises and taps those specific screens (the texts to match: `I agree`, `Accept`, `Next`, `Not now`, `Close`). Six burners are listed in `HANDOFF.md` Â§... (same password); assume 2â€“3 are dead.

---

## 6. Known traps (do not re-walk these)

1. **`create_script` is on Session, not Device** â†’ `AttributeError: 'Device' object has no attribute 'create_script'`. Attach first.
2. **`setProductList()` needs `java.util.ArrayList`**, not `Java.array(...)` â†’ `argument types do not match any of: .overload('java.util.List')`.
3. **Placeholder replacement order**: `js.replace("__PRODUCTS__", â€¦)` hits the token inside the *comment* first, leaving `var PRODUCTS = __PRODUCTS__;` literal â†’ `ReferenceError: '__PRODUCTS__' is not defined`. Replace the whole assignment.
4. **uiautomator returns off-screen nodes with `bounds="[0,0][0,0]"`** â†’ taps land at (0,0) and do nothing. Scroll first, or filter nodes whose bounds are zero.
5. **Billing classes are not in Google One's loader** â€” only in the injected `module_521.apk` (`DexClassLoader`). Any hook aimed at them must live where they're actually loaded.
6. **Play Store's databases reflect our own probes** â€” grepping `g1.*` there returns the candidate list we just queried. Do not mistake it for the real catalogue.
7. **GMS `shared_prefs` / `databases` contain zero `g1.*` strings** on this build.
8. **APK contains exactly one product ID** (`g1.100gb`); the rest is server-delivered.

---

## 7. Quick start for the next session

```powershell
# 1. emulator up
$mm = "C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe"
& $mm control -v 0 launch
# wait for is_android_started: true

# 2. adb root
adb connect 127.0.0.1:16384
adb -s 127.0.0.1:16384 root

# 3. sweep (the working tool)
cd C:\Users\child\PROJECTS\RootTest\google-ai
.\.venv\Scripts\python.exe offerwatch.py --serial 127.0.0.1:16384

# 4. diff against the previous run
.\.venv\Scripts\python.exe offerwatch.py --diff reports\offerwatch-<older>.json

# 5. UI walk (navigation works, ID capture does not yet)
.\.venv\Scripts\python.exe idcapture.py --serial 127.0.0.1:16384 --max-taps 12
```

---

## 8. Definition of done for this workstream

- [ ] A tool that enumerates **every purchasable product** for the signed-in account, without a hardcoded list.
- [ ] Offer tokens captured **per plan card**, including campaign discounts (Black Friday etc.).
- [ ] A diff mode that flags *new* zero-price or discounted offers between runs, so a future campaign is noticed within a day.
- [ ] Documentation of which account state is required to see intro offers, so nobody re-tests a suppressed account and concludes "no offers".

---

## 9. Files touched

```
google-ai\offerwatch.py                 sweeps SKUs, prints/saves offers      WORKING
google-ai\assets\frida\sku_probe.js     billing query probe (chunked)         WORKING
google-ai\idcapture.py                  UI walker + sniffer orchestration     PARTIAL
google-ai\assets\frida\id_sniffer.js    JSON/Bundle/Intent/builder hooks      PARTIAL
google-ai\reports\                      offerwatch-*.json, idcapture-*.json   data
google-ai\tmpdb\                        pulled APK + Google One db copies     scratch
HANDOFF.md                              setup + claim flow + risk model       keep
HANDOFF-DISCOVERY.md                    this file                             keep
```

---

## 10. Session 2026-11-23 03:28â€“04:10 â€” the campaign SKUs exist, and B found them

**Headline: the Black Friday discounts ARE in Play Billing.** They were never in the UI layer, and
they were never in the `g1.*.subs_variant` namespace either. They live on their own campaign product
IDs, which nobody had guessed until this session:

```
<core>.<N>months_ip_<P>p.acq        offerId = "introprice"       phases = 2
```

- `N` âˆˆ {1, 2, 3, 4, 6, 12} months, `P` âˆˆ {50, 75, 85, 90, 95} percent off
- phase 1 = discounted price for one billing period (P1M), phase 2 = full monthly price
- these are **not** `eft-*` and carry **no zero-price phase** â€” an `introprice` offer is a discount,
  not a free trial. Do not confuse the two when reading a sweep.

### 10.1 Verified campaign catalogue (this account, 2026-11-23 04:06)

| Product | Offer | Phase 1 | Period | Phase 2 | Phases |
|---|---|---|---|---|---|
| `g1.2tb.ai.1month_ip_95p.acq` | introprice | **Rp 15.000** | P1M | Rp 309.000 | 2 |
| `g1.2tb.ai.1month_ip_90p.acq` | introprice | Rp 31.000 | P1M | Rp 309.000 | 2 |
| `g1.2tb.ai.1month_ip_75p.acq` | introprice | Rp 77.000 | P1M | Rp 309.000 | 2 |
| `g1.2tb.ai.2months_ip_50p.acq` | introprice | Rp 154.500 | P1M | Rp 309.000 | 2 |
| `g1.2tb.ai.3months_ip_90p.acq` | introprice | Rp 31.000 | P1M | Rp 309.000 | 2 |
| `g1.2tb.ai.3months_ip_75p.acq` | introprice | Rp 77.000 | P1M | Rp 309.000 | 2 |
| `g1.2tb.1month_ip_95p.acq` | introprice | **Rp 8.000** | P1M | Rp 158.000 | 2 |
| `g1.2tb.1month_ip_90p.acq` | introprice | Rp 16.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.1month_ip_85p.acq` | introprice | Rp 24.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.2months_ip_50p.acq` | introprice | Rp 79.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.3months_ip_50p.acq` | introprice | Rp 79.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.3months_ip_85p.acq` | introprice | Rp 24.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.3months_ip_90p.acq` | introprice | Rp 16.000 | P1M | Rp 158.000 | 2 |
| `g1.2tb.4months_ip_75p.acq` | introprice | Rp 39.500 | P1M | Rp 158.000 | 2 |
| `g1.100gb.1month_ip_85p.acq` | introprice | Rp 5.000 | P1M | Rp 32.000 | 2 |
| `g1.100gb.1month_ip_95p.acq` | introprice | Rp 5.000 | P1M | Rp 32.000 | 2 |
| `g1.100gb.3months_ip_50p.acq` | introprice | Rp 16.000 | P1M | Rp 32.000 | 2 |
| `g1.100gb.3months_ip_85p.acq` | introprice | Rp 5.000 | P1M | Rp 32.000 | 2 |
| `g1.100gb.4months_ip_75p.acq` | introprice | Rp 5.000 | P1M | Rp 32.000 | 2 |

Notes:
- The grid is **sparse** â€” only some `months Ã— percent` combinations exist (e.g. `g1.2tb.ai.3months_ip_85p.acq`
  returns nothing, `..._90p` does). A miss on one combination does not mean the campaign is absent.
- **These are visible on an account that already holds the Pro trial.** That is not permission to claim:
  `introprice` on an active sub is a stacking path (see HANDOFF.md Â§7 rule 3). Eligibility to *see* â‰ 
  eligibility to *claim*.
- No `introprice` variants were found on `g1.20tb`, `g1.10tb`, `g1.5tb`, `g1.play.20tb`, `g1.30tb` or
  `g1.ai.pro` in this session. Only the 100 GB / 2 TB / 2 TB.ai cores carry them.

### 10.2 `offerwatch.py` now finds these without help

`generate_candidates()` unions `campaign_candidates()` (8 cores Ã— 6 durations Ã— 8 percentages â‰ˆ 384)
plus the seed list, which now includes the previously missing `g1.5tb`, `g1.10tb`, `g1.100gb`.
A plain `python offerwatch.py` run reports all of Â§10.1. No `--extra` needed.

Diff mode is what makes this useful:

```powershell
python offerwatch.py --serial 127.0.0.1:16384 --diff reports\offerwatch-<older>.json
```

Run: `reports\offerwatch-20261123-040630.json` (first self-discovering run; 1403 candidates, 20 offers,
7 zero-price, 0 errors).

### 10.3 Experiment A was a dead end â€” evidence, so nobody rebuilds it

Play-side hooking produced **zero** product ids and **zero** offer tokens across every variant tried.
What was actually established:

| Fact | Evidence |
|---|---|
| Sheet is not purely Play's | `mCurrentFocus` goes `GoogleOneSdkActivity` (app) â†’ `com.android.vending/...acquire.SheetUiBuilderHostActivity` (Play) only after *Continue to subscribe* |
| No BillingClient classes in Play | `ClassNotFoundException: com.android.billingclient.api.QueryProductDetailsParams$Product$Builder ... on path: DexPathList[[zip file ".../com.android.vending.../base.apk"]]` |
| No BillingClient classes in Google One | `enumerateLoadedClasses` filtered on `/vending|InAppBilling|billingclient|BuyIntent|ProductDetails|SkuDetails/` â†’ **0 matches**, with the sheet open |
| Sheet Intent carries nothing | `dumpBundle(intent.getExtras())` inside `SheetUiBuilderHostActivity.onCreate` â†’ no billing keys, no `g1.*` |
| Live hooked `putExtra`/`putString`/`JSONObject.put` â†’ nothing | 25 Intent overloads + Bundle + JSON hooked, sheet opened, 0 hits |
| Play `mActivities` is empty when attached | `ActivityThread.currentActivityThread().mActivities` iteration â†’ 0 activities in the Play process, sheet on screen |

Conclusion: the product id / offer token transit **inside Play's protobuf/native layer**, not as Java
strings reachable from these hooks. A would need a BoringSSL/protobuf-level tap inside Play â€” expensive,
and now unnecessary, because B answers the question directly. **Treat A as closed.**

### 10.4 New traps (add to Â§6)

1. **Frida sees Play only by raw pid.** `enumerate_processes()` lists `com.android.vending:background`
   (frozen in `do_freezer_trap`) but **not** the main `com.android.vending`. `attach("com.android.vending")`
   â†’ `ProcessNotFoundError`. Use `pidof com.android.vending` and `attach(int)`.
2. **`enumerateLoadedClassesSync()` inline in `Java.perform` stalls `script.load()`** â†’
   `frida.TransportError: timeout was reached`. Defer it with `setTimeout(..., 1500)`.
3. **Unbounded reflection over Play's object graph wedges the script thread.** Walking fields
   recursively without a cap hangs the attach (observed: 180 s+, job killed). Cap objects (~150) and
   depth (2) or don't do it.
4. **`SheetUiBuilderHostActivity.onCreate` often does not re-fire.** Re-opening the sheet reuses the
   instance, so hooks armed *after* the first open never see it. Arm before, or hook `onNewIntent`/`onResume`.
5. **Rotation flips the uiautomator coordinate space.** `wm size` reports `1080x1920`, `screencap` returns
   `1920x1080`, and dumps alternate between both. Derive the real size from the PNG IHDR
   (`playsniff.display_size()`) and clamp every node to it; a node with `y2 > height` taps the wrong pixel.
6. **Compose merges card labels.** The `text="Upgrade"` node can span the whole card (tap = card body, no
   action) or sit at `[0,0][0,0]` below the fold. Scroll until a node with in-viewport bounds exists,
   then tap its centre.
7. **`ultra0.launch_app()` restarts Google One.** Any attach helper that calls it destroys the state you
   were about to inspect. Attach with `--no-restart` when you need the current screen.
8. **Multiple accounts on one device break billing attribution.** With `horalixscripts5` (holds Pro) and
   `horalixscripts4` (clean) both signed in, Billing resolved to the **AccountManager primary** â€” not to
   the account the Google One UI showed. Symptom, on a provably clean account:

   ```
   Sheet: "You're already subscribed to Google AI Pro (5 TB) (Google One). Manage subscriptions"
   while Play -> Subscriptions for scripts4 shows "Discover subscriptions" (empty)
   ```

   `dumpsys account` listed scripts5 first (added first). Fix: **remove every other Google account from
   the device** before claiming, then `am force-stop com.android.vending` to drop the stale session.
   After removal the same `campaign_claim.py --launch` call returned the correct trial sheet. This also
   satisfies HANDOFF.md Â§7 rule 4 (one account, one device). A shared payment instrument is *not* the
   cause â€” ownership errors are account-level, instrument errors appear at confirm.
9. **No client-side cache of product ids, at all.** `grep -rao "g1\.[A-Za-z0-9_.]*"` over
   `/data/data/com.android.vending/` and `/data/data/com.google.android.apps.subscriptions.red/`
   (databases + shared_prefs) returns **0 matches**, even right after browsing the plans UI and running
   dozens of queries. The SKUs are never persisted, so there is no cache to mine: brute-force naming is
   the only enumeration channel. Don't spend a session looking for a shortcut here.
10. **`offerwatch.py` now takes `--extra-file`.** A wide grid (thousands of SKUs) overflows the Windows
    argv limit, so candidates go in a newline-separated file. `--progress` prints every 10 chunks.
    The probe deadline scales with candidate count (â‰ˆ1 s per 20-SKU chunk).

### 10.5 Tools added this session

```
playsniff.py            Play-process sniffer (intent/bundle/json hooks + sheet hooks)   NEGATIVE RESULT
gosniff.py              Google One-side sniffer (sheet activity, classloader tap)       NEGATIVE RESULT
sheetwalk.py            walk to the Play sheet, bounded payload dump, back out          opens sheet OK
assets/frida/playsniff.js, gosniff.js, sheetprobe.js                                    hooks
reports/offerwatch-20261123-04*.json                                                      campaign data
```

`sheetwalk.py` reliably opens the sheet (Get offer â†’ card Upgrade â†’ Continue to subscribe) and backs
out without confirming anything. Keep it for any future UI-layer question; don't expect ids from it.

### 10.7 Exhaustive sweep â€” the campaign space is mapped, not just sampled

Run 2026-11-23 08:30 (`reports/offerwatch-20261123-083047.json`), on the clean `scripts4` account:

| Axis | Values swept |
|---|---|
| cores | `g1.2tb.ai`, `g1.2tb`, `g1.100gb`, `g1.2tb.subs_variant`, `g1.2tb.ai.subs_variant`, `g1.5tb`, `g1.10tb`, `g1.20tb`, `g1.30tb`, `g1.play.2tb.ai`, `g1.play.20tb`, `g1.ai.pro`, `g1.play.ai.pro` |
| durations | 1â€“12 months, 18, 24 |
| percentages | 10â€“95 in steps of 5 |
| verbs | `ip` (all cores); `fp`, `intro`, `promo`, `bf` on the 3 campaign cores |

**6,384 candidates â†’ 57 offers â†’ 31 unique products â†’ 19 `introprice` SKUs. New vs the 08:12 run: none.**

So the entire grid produced **nothing beyond what Â§10.1 documents**. What that proves is absence, which is
worth as much as a hit:

- Only these durations exist: **1, 2, 3, 4 months**. No 5/6/7/8/9/10/11/12/18/24-month `_ip_` offers.
- Only these percentages exist: **50p, 75p, 85p, 90p, 95p**. Nothing from 10p to 45p, nothing at 55â€“70p,
  nothing at 80p.
- Only `_ip_` is a live verb. `fp_`, `intro_`, `promo_`, `bf_` returned zero at every combination.
- **Ultra carries no intro offers at all** â€” `g1.20tb`, `g1.30tb`, `g1.play.20tb`, `g1.ai.pro`,
  `g1.play.ai.pro` return base price only, in every campaign form tried.
- The discount ladder is coherent: the longer the intro period, the smaller the discount
  (1 mo @ 95p â†’ 2 mo @ 50p â†’ 3 mo @ 90p â†’ 4 mo @ 75p). That is Google's promo structure, not a bug.

Combined with Â§10.4 trap 9 (nothing is cached client-side), this closes the discovery workstream for this
convention: **there is no further SKU to find by naming, and no cache to mine.** Anything new from here
requires either a new campaign Google has not shipped yet, or a different account cohort (Â§10.6).


### 10.6 What is actually left

> Â§10.7 already answered the "are there more SKUs?" question: 6,384 candidates across every plausible
> name produced zero new products. What follows is the claim-side work, not discovery.

1. **Clean burner run** (no active sub, payment method, IDR) to confirm an `introprice` offer is
   *claimable*, not merely listed. Cheapest candidates: `g1.2tb.ai.1month_ip_95p.acq` (Rp 15.000).
   Claim flow: BillingClient `launchBillingFlow` with **that** offer token â€” the `--plan pro12`
   mapping in `ultra0.py` points at `g1.2tb.ai.subs_variant`, so it does **not** reach these SKUs.
2. Verify whether the campaign survives on a fresh account (this session only proves it is visible to
   a subscribed one).
3. Only then decide whether stacking is even a question. It is not recommended (HANDOFF.md Â§7.3).


### 10.8 Second naming family — direct _eft products (found after §10.7)

A third-party report (different storefront, USD) showed products shaped like
`g1.2tb.ai.12months_eft` with a bare `eft-12months` offer. Our generator never produced that
shape: §10.7 had swept only `<core>.<N>months_ip_<P>p.acq` and the `.subs_variant` trials.

Querying that family on the ID storefront returned **8 more products and doubled the zero-price
count from 7 to 21**:

| Product | Offer id | First phase | Period | Then |
|---|---|---|---|---|
| `g1.2tb.ai.18months_eft` | eft-18months | **Free** | **P1Y6M** | Rp 309.000/P1M |
| `g1.2tb.ai.12months_eft` | eft-12months | **Free** | P1Y | Rp 309.000/P1M |
| `g1.2tb.ai.6months_eft` | eft-6months | **Free** | P6M | Rp 309.000/P1M |
| `g1.2tb.ai.4months_eft` | eft-4months | **Free** | P4M | Rp 309.000/P1M |
| `g1.2tb.ai.3months_eft` | eft-3months | **Free** | P3M | Rp 309.000/P1M |
| `g1.2tb.ai.2months_eft` | eft-2months | **Free** | P2M | Rp 309.000/P1M |
| `g1.2tb.ai.1month_eft` | eft-1month | **Free** | P1M | Rp 309.000/P1M |
| `g1.2tb.6months_eft` | freetrial | **Free** | P26W2D | Rp 158.000/P1M |
| `g1.2tb.3months_eft` | freetrial | **Free** | P13W1D | Rp 158.000/P1M |
| `g1.2tb.1month_eft` | freetrial | **Free** | P4W3D | Rp 158.000/P1M |
| `g1.100gb.9months_eft` | freetrial | **Free** | P39W3D | Rp 32.000/P1M |
| `g1.100gb.3months_eft` | freetrial | **Free** | P13W1D | Rp 32.000/P1M |
| `g1.100gb.2months_eft` | freetrial | **Free** | P8W6D | Rp 32.000/P1M |
| `g1.100gb.1month_eft` | freetrial | **Free** | P1M | Rp 32.000/P1M |

Also confirmed: `g1.20tb.v2` exists as an Ultra product revision (base price only).

Why it matters beyond the extra SKUs: the third-party report labels these **READY_DIRECT_FREE** —
directly purchasable — versus the `.subs_variant` trials which they mark NEEDS_BASE_3M_FIRST
(the `--stack` path). If that distinction holds, `g1.2tb.ai.<N>months_eft` is the clean claim
path and stacking was never required.

Still missing: **no family-tier SKU returned** — `g1.family`, `g1.family.2tb`, `g1.family.5tb`,
`g1.family.ai` and `<core>.family` all came back empty on the ID storefront.

`offerwatch.py` now generates both families (`direct_eft_candidates()`, `revision_candidates()`),
581 candidates by default, no `--extra` needed.

**Verified claimable, same session.** `campaign_claim.py --product g1.2tb.ai.18months_eft --offer eft-18months
--launch` returned `launchBillingFlow` code 0 and Play's sheet read:

```
Google AI Pro (5 TB) | Google One | Starting today | 18-month free trial
Starting 23 May 2028 | Rp 309.000/month | + tax
You won't be charged if you cancel before 23 May 2028
GoPay: **** 8271 | Subscribe
```

No `--stack`, no `subscriptionUpdateParams`: a plain first purchase. The "direct free" framing from
the third-party report holds.

---

## 11. Device / OEM bundle offers (Xiaomi, Oppo, Pixel) — what they actually are

Checked 2026-11-23 against the Google One APK (19.3 MB, 67,687 dex strings).

**They are not Play products, and there is no SKU to query.** The app implements a separate
partner-entitlement subsystem:

```
PartnerOfferEligibilityDataService.java
CheckPartnerOfferEligibilityResponse
processAndLogPartnerOfferEligibilityResponse
SqliteKeyValueCache:PartnerOfferEligibilityCache.db
RedeemPartnerOfferFragmentPeer.java
PARTNER_OFFER_ELIGIBLE / PARTNER_OFFER_INELIGIBLE
PARTNER_EFT_DETAILS_PAGE_TAP_REDEEM
CHECK_PARTNER_OFFER_ERROR_NO_CPID
CarrierCpid, &cpid=, fake_cpid
MY_PIXEL_EFT_HOME_UPSELL_CARD / MY_PIXEL_EFT_UPSELL_NOTIFICATION
```

Reading that:

- `EFT` here means *extended free trial* granted through a **partner**, keyed on a **CPID**
  (carrier/partner id), and resolved by a server eligibility call.
- The result is cached in `PartnerOfferEligibilityCache.db`. On this emulator that database does
  **not exist** — no eligibility check has ever run, which is consistent with the device never being
  a partner device.
- Redemption is a UI flow (`PARTNER_OFFER_DETAILS_PAGE_TAP_REDEEM`), not a billing flow.

### Consequences for this toolkit

- `offerwatch.py` cannot see these: it enumerates Play subscriptions, and partner EFTs never appear
  in `queryProductDetailsAsync`.
- Spoofing `ro.product.*` cannot work, which the handoff already reported from the outside. The
  reason is now visible in code: eligibility is not derived from the model string, it is derived from
  a CPID supplied by partner/carrier signals.
- The only client-side artefact would be the eligibility cache, and it does not exist until a check
  runs on an actually-eligible device.

**Conclusion: device-bundle plans are a different subsystem. No further Play-side work will find
them, and nothing client-side manufactures a CPID.**
