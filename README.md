# skua

Tooling for discovering what a Google Play Billing account is *actually* offered, and for opening
checkouts on those offers without confirming them.

A skua is a seabird that makes its living taking what other birds leave behind. Fitting.

Built on top of the [google-ai](https://github.com/hoangsvit/google-ai) toolkit
(upstream: [gylive/google-ultra](https://github.com/gylive/google-ultra)), vendored here at
`google-ai/` pinned to commit `5e07e5fd61ffd46ba8dfb539513fe31db653ff45`.

## What this actually does

Play returns subscription offers that the Google One UI never shows. Some are zero-priced trials
(`eft-*`), some are discounted intro pricing on a separate campaign namespace
(`<core>.<N>months_ip_<P>p.acq` → offer id `introprice`). This repo enumerates both by driving a real
`BillingClient` inside the app process, and reports every pricing phase.

Discovery is brute force by design: product IDs are server-delivered and **never persisted client-side**
(verified — a `grep -rao "g1\.[A-Za-z0-9_.]*"` over Play's and Google One's databases and shared_prefs
returns zero matches, even after thousands of queries). Play silently ignores invalid IDs, so the only
enumeration channel is asking for plausible names.

## Layout

```
HANDOFF.md                     setup, claim flow, risk model
handoff-discovery/HANDOFF-DISCOVERY.md
                               campaign catalogue, verified traps, sweep results
google-ai/                     vendored upstream toolkit (pinned) + this repo's tools
  offerwatch.py                enumerate offers for a generated SKU set
  campaign_claim.py            open a checkout sheet for a campaign/trial offer, never confirm
  sheetwalk.py                 walk the plans UI to Play's purchase sheet
  playsniff.py, gosniff.py     billing-payload sniffers (kept for the negative result)
  assets/frida/                injected probes
  assets/modules/module_521.b64   the billing SDK module, base64
data/sweep-grid-20261123.txt  6,384-candidate grid used for the exhaustive sweep
```

## Usage

```powershell
cd google-ai
python -m venv .venv --without-pip
python -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt

$env:PATH="$env:LOCALAPPDATA\Android\Sdk\platform-tools;$env:PATH"

# read-only: what is this account offered?
.\.venv\Scripts\python.exe offerwatch.py --serial 127.0.0.1:16384

# read-only: query one SKU, print its offer tokens
.\.venv\Scripts\python.exe campaign_claim.py --product g1.2tb.ai.1month_ip_95p.acq --list

# opens the checkout sheet and STOPS. nothing is confirmed.
.\.venv\Scripts\python.exe campaign_claim.py --product g1.2tb.ai.subs_variant --offer 12months-eft --launch
```

## Findings, in short

- Zero-priced trials live on `g1.2tb.ai.subs_variant`, `g1.2tb.subs_variant`, `g1.play.2tb.ai`.
  They remain visible even on an account that already holds a subscription — visibility is not permission.
- Campaign discounts live on `<core>.<N>months_ip_<P>p.acq` with offer id `introprice`. Only N ∈
  {1,2,3,4} months and P ∈ {50,75,85,90,95} exist. Ultra tiers carry no intro offers at all.
- An active Google One subscription removes intro offers from the checkout, but not from the query.
- Billing resolves to the **AccountManager primary** account, not to whichever account the app UI shows.
  Multiple Google accounts on one device will get you `ITEM_ALREADY_OWNED` on a provably clean account.
- The purchase sheet is Play's `SheetUiBuilderHostActivity`, but the SKU is not reachable as Java data in
  either process — the payload moves in Play's protobuf layer. Hooking is a dead end; querying is not.

Details, exact error strings, and every trap are in `handoff-discovery/HANDOFF-DISCOVERY.md`.

## Conventions

Conventional Commits. No vendored history: `google-ai/.git.bak` keeps the upstream clone locally; the
pinned SHA above is the record.

## Note

Reading offers is harmless. Completing a checkout is not, and this repo deliberately has no flag to do
it — every tool stops at an open sheet. What you do at that sheet is your call and your account.
