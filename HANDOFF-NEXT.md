# Handoff — session of 2026-11-23 (evening)

Read this first; `HANDOFF-DISCOVERY.md` holds the detailed findings and `PROMO-CODES.md` the
carrier/device-offer mechanics.

**This document does not ask you to start anything.** Nothing is mid-run, no job is queued, and no
purchase should be made without the operator saying so in chat. Treat every item under "Open threads"
as a question to ask about, not a task to begin.

---

## 1. State at handoff

| Thing | State |
|---|---|
| Repo | `C:\Users\child\PROJECTS\RootTest` → https://github.com/Horali/skua (private), 40 commits, clean |
| MuMu emulator | **shut down at handoff** (`MuMuManager.exe control -v 0 shutdown`) |
| Emulator identity | Android 15, SM-G9980 spoof, rooted via `adb root`, serial `127.0.0.1:16384` |
| Google account on emulator | `horalixscripts4@gmail.com` only — `scripts5` was removed (see §4) |
| S25+ phone | `RRCY1032Y6F`, reachable over Wi-Fi (`192.168.1.17:38337` wireless-debugging, `:5555` tcpip) |
| Phone root | **ON and working** — KernelSU "Working [Jailbreak mode]", LKM. Ephemeral: gone on reboot |
| Phone root apps | `df.root`, `com.snothin.ghostsam`, `me.weishu.kernelsu` installed → **BRImo will crash until `tools\root-mode.ps1 -Off`** |
| Infinix phone | `192.168.1.8:5555`, on Wi-Fi, untouched |
| Purchases | **none anywhere.** No trial claimed, no subscription started, no vendor paid |

---

## 2. Verified offer findings (what is actually claimable)

| Product | Offer | First phase | Renewal | Status |
|---|---|---|---|---|
| `g1.2tb.ai.18months_eft` | `eft-18months` | **Free / P1Y6M** | Rp 309.000/mo | **verified claimable**, sheet read, not claimed |
| `g1.2tb.ai.12months_eft` | `eft-12months` | Free / P1Y | Rp 309.000/mo | claimable |
| `g1.2tb.ai.{1,2,3,4,6}months_eft` | `eft-Nmonths` | Free | Rp 309.000/mo | claimable |
| `g1.2tb.{1,3,6}months_eft` | `freetrial` | Free (P4W3D–P26W2D) | Rp 158.000/mo | claimable |
| `g1.100gb.{1,2,3,9}months_eft` | `freetrial` | Free | Rp 32.000/mo | claimable |
| `g1.2tb.ai.subs_variant` | `12months-eft`/`6months-eft*` | Free | Rp 309.000/mo | **stack path — do not use** |
| `g1.2tb.ai.3months_ip_75p.acq` etc. | `introprice` | Rp 77.000/mo ×3 | Rp 309.000/mo | claimable; also rendered in-app |
| ChatGPT Go | `2k8d9f8u1pmw6` | **Free / P6M** | Rp 75.000/mo | verified claimable |
| ChatGPT Plus | `1-month-10-dollars` | Rp 149.500 | Rp 299.000/mo | claimable |
| Duolingo | — | 7-day free trial | Rp 600.000/yr | claimable, UI-visible |
| Spotify | — | 3 mo at list price via Play | Rp 59.900/mo | Play path; Spotify-direct is cheaper |
| Claude / Perplexity / Mistral / Replit | — | **none** | — | real negatives, ids enumerated |

The **in-app intro page** is `one.google.com/ai` (app claims `/ai`). It shows prices the home screen
hides. That is the fastest way to see what a given account is offered.

---

## 3. Mechanisms learned the hard way (do not re-derive)

1. **Campaign SKUs** are `<core>.<N>months_ip_<P>p.acq` → offer id `introprice`; and
   `<core>.<N>months_eft` → `eft-Nmonths`. `offerwatch.py` generates both families now (581 candidates).
2. **Billing attribution follows the AccountManager primary account, not the app UI.** Two Google
   accounts on one device produced `ITEM_ALREADY_OWNED` on a provably clean account until the other
   account was removed. Keep one account per device.
3. **Offer tokens are issued by Play per account**; nothing can be minted client-side.
4. **Device/OEM and carrier offers are not Play SKUs.** They resolve through a partner-eligibility
   call keyed on CPID, or through a one-time activation token at
   `serviceactivation.google.com/activate-plan/subscription/new/<token>`. Spoofing `Build` on the
   emulator changed nothing and no eligibility check even ran (§11.1).
5. **Add-on offers** (e.g. “$1.99/mo for 12 months”) are gated on an existing Google One membership;
   `COMMERCE_BUYFLOW_FOR_ADDONS` + `NOT_ELIGIBLE_EXISTING_MEMBER_WITH_ADDON`. A free account never
   sees them, on any storefront tested.
6. **`Java.choose` is broken on this ART build** (`EnsurePluginLoaded` export missing). Enumerate
   classes or hook loaders instead.
7. **Hooking billing classes only works on apps that use the stock SDK.** Duolingo, Mistral, Replit
   and Spotify open a Play sheet while instrumented hooks stay silent — do not spend a session there.
   RevenueCat apps leak their catalogue in `shared_prefs` (`offeringsResponse`), which is far cheaper.
8. **Chromium is installed but was disabled** (`enabled=0`). Enabled now. `web_read.py` drives it over
   `chrome_devtools_remote` (CDP) — the only way to read rendered page text, since `uiautomator` sees
   just the address bar and `web_fetch` gets login redirects.
9. **`web_search` is broken in the agent config** (HTTP 401 on the search endpoint). Use `web_read.py`
   through the device browser instead. This is a settings issue only the operator can fix.

---

## 4. Tools (all read-only unless stated)

| Tool | Purpose |
|---|---|
| `offerwatch.py` | enumerate Play offers for a generated SKU grid; `--diff`, `--extra-file` |
| `campaign_claim.py` | open a checkout for one SKU; **stops at the sheet**, no buy flag |
| `appoffer.py` | generic: any installed package → dex-discovered ids → in-process query |
| `billing_watch.py` | hook an app's own billing calls (`--lazy`, `--multiloader`, `--spawn`) |
| `g1_snapshot.py` | snapshot/diff Google One campaign state (`--diff`) — catches activations landing |
| `redeem_watch.py` | open an offer link and classify the outcome (REDEEMABLE/UNAVAILABLE/NO_ELIGIBLE/NO-OP) |
| `web_read.py` | read the device browser's page text/links over CDP |
| `spoof_boot.py` + `assets/frida/spoof_build.js` | spawn an app with a spoofed `Build` identity (negative result) |
| `gpt_skus.py`, `gpt_claim.py`, `gpt_trial_watch.py` | ChatGPT-side enumeration, checkout, cohort detector |
| `claude_probe.py`, `claude_skus.py` | Claude-side ids and offers |
| `tools\phone-connect.ps1` | re-attach phones over Wi-Fi via mDNS |
| `tools\root-mode.ps1` | `-On` / `-Off` / `-Status` for the S25+ root apps (see §1 for BRImo) |

`scripts5` account data was deleted from the device; its old SDK database files sit untracked in
`google-ai/` and are gitignored. Do not commit them.

---

## 5. Open threads — ask before doing any of these

1. **Claim the 18-month trial** on a clean account (`g1.2tb.ai.18months_eft` / `eft-18months`). The
   operator has deferred this repeatedly. Nothing is claimed.
2. **Add-on experiment**: fresh burner + cheapest base plan (Plus 400 GB intro Rp 19.000/mo) → check
   whether member add-on offers (the `$1.99 × 12mo` class) become visible. Do **not** run this on an
   account holding unclaimed trials.
3. **Carrier/device route**: `redeem_watch.py` is ready but needs a live unclaimed link. The Jio token
   in hand was claimed and expired (404); Xiaomi's official bundle is only **3 months** and requires an
   eligible device — worse than the Play offer, so it was closed on evidence.
4. **ChatGPT Plus trial cohort**: `gpt_trial_watch.py --repeat N` on other accounts. 15/15 attempts on
   one account were identical — eligibility is account-sticky, not per request.
5. **Cheap-reseller question** (Claude 200k etc.) was analysed but not testable: prices below annual
   list imply shared seats, promo grants, carrier bundles or stolen instruments. Nothing actionable
   without buying from a vendor.

---

## 6. Do not

- Do not claim, subscribe, slide, or pay for anything without an explicit instruction in chat.
- Do not root or install root packages on the physical phones for this work; the S25+ already has them
  from the operator's own request, and `-Off` is the cleanup.
- Do not put two Google accounts on the emulator at once (billing attribution).
- Do not commit `reports/`, `tmpdb/`, `tmpui/`, SDK databases, or anything containing account emails or
  tokens — `.gitignore` covers them, keep it that way.
- Do not treat a listed offer as permission to stack. Single claims only.
