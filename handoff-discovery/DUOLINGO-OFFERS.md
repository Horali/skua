# Duolingo â€” first non-Google app with a verified Play trial

Session 2026-11-23 10:33â€“10:45. Account `scripts4`, storefront **ID** (IDR).
App: `com.duolingo`, installed from Play, signed in, subscription page opened by hand.

## What Play's own sheet says

```
Super Duolingo | Duolingo: Languages & Chess
Starting today        â†’ 7-day free trial
Starting 30 Nov 2026  â†’ Rp 600.000/year  + tax
You won't be charged if you cancel before 30 Nov 2026
We'll send you a reminder 2 days before your trial ends
GoPay: **** 8271 | Subscribe
```

Plan screen, before the sheet:

| Plan | Price | Trial |
|---|---|---|
| Individu | Rp 600.000/thn (Rp 50.000/bln) | `Gratis selama 7 hari` |
| Keluarga (up to 6) | Rp 839.000/thn (Rp 69.916/bln) | `Gratis selama 7 hari` |

So this is a genuine Play subscription offer with a zero-priced first phase â€” the first app outside
Google's own family where that has been confirmed in this workstream.

## Billing stack

Unlike ChatGPT/Perplexity (RevenueCat) this app ships the real client:

```
billing_watch.py --package com.duolingo
  [hooked] QueryProduct.setProductId                 1
  [hooked] BillingFlowParams.setOfferToken           1
  [hooked] BillingFlowParams.setProductDetails       1
  [hooked] ProductDetails.getProductId               1
```

Every hook resolved â€” no injection needed, no obfuscation.

## Why the SKU id still wasn't captured

Two separate traps, both already known, that combine badly here:

1. **The app caches `ProductDetails`.** By the time a hook is armed the products are already fetched,
   and re-opening the checkout reuses the cached objects, so `setProductId` never fires.
2. **`Java.choose` is unusable on this ART build** â€”
   `libart.so: unable to find export '_ZN3art7Runtime18EnsurePluginLoadedEPKc...'`
   (the API 35 x86_64 trap from HANDOFF Â§6). So the cached instances cannot be enumerated off the heap.

Ids tried and rejected (all returned nothing, so they are internal enums, not Play products):
`gold_subscription_*`, `gold_subscription_trial14*`, `super_instant`, `super_lite`, `super_annual*`,
`immersive_gold_subscription`.

Dex strings do confirm several trial variants exist in the app's config, even though only the 7-day one
rendered:

```
GOLD_SUBSCRIPTION_TRIAL_14
GOLD_SUBSCRIPTION_TRIAL_14_TWELVE_MONTH
GOLD_SUBSCRIPTION_TRIAL_14_FAMILY_TWELVE_MONTH
GOLD_SUBSCRIPTION_WINBACK_TRIAL_14*
"1-month free trial on Super annual + family"
com.duolingo.immersive_free_trial_subscription
```

So there are **14-day** and **1-month** trial configurations alongside the 7-day one; whether they are
grantable is a cohort question like Perplexity's `pro-trial-1w`.

## Claiming

Does not require the SKU: the sheet is the contract. With the sheet open, Subscribe starts the 7-day
trial and the first charge lands 30 Nov 2026. Cancel any time before that date and nothing is billed.

## Tooling note

`billing_watch.py` works on this app but only if attached **before** the paywall loads product details.
For an app that caches, the practical sequence is: force-stop app â†’ attach â†’ open paywall. If the
classes are not yet loaded at attach time, the hooks fail; on this app they loaded fine on a warm
process.
