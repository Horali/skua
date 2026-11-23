# Perplexity offers — catalogue recovered, campaigns not granted

Session 2026-11-23 10:04–10:18. Account `scripts4`, storefront **ID** (IDR).
App: `ai.perplexity.app.android`, installed and **signed in** (Google SSO as scripts4).

## Two-layer structure

Perplexity, like ChatGPT, is **RevenueCat over Play Billing**. That matters because the two
layers disagree:

- **RevenueCat config** knows a dozen campaign names, including a weekly trial.
- **Play** returns only base plans to this account — every `offerId` came back `null`, every
  product had exactly one phase.

### Recovered from the app's own RevenueCat cache

Read from `/data/data/ai.perplexity.app.android/shared_prefs/com_revenuecat_purchases_preferences.xml`
(the `offeringsResponse` key), no hooks needed:

| offering | package | product | plan id |
|---|---|---|---|
| max_2023-09-22 | $rc_annual | `max` | max-2000-y |
| max_2023-09-22 | $rc_monthly | `max` | max-200-m |
| **pro_trial-1w** | $rc_annual | `pro` | **pro-trial-1w-200-y** |
| **pro_trial-1w** | $rc_monthly | `pro` | **pro-trial-1w-20-m** |
| pro_25p-off-1y_annual-only | $rc_annual | `pro` | pro-25p-off-1y-200-y |
| pro_30p-off-1y_annual-only | $rc_annual | `pro` | pro-30p-off-1y-200-y |
| pro:pro-10p-off-1y-200-y | $rc_annual | `pro` | pro-10p-off-1y-200-y |
| pro_5-1m | $rc_annual / $rc_monthly | `pro` | pro-5-1m-200-y / pro-5-1m-20-m |
| paywall-new-user | both | `pro`, `max` | pro-200-y-1w, pro-20-m, max-200-m |
| win-back.monthly-only | $rc_monthly | `pro_back_to_school` | pro-5-m |
| ubb-credits | 6 packages | `pplx_usage_based_billing_{5,10,25,50,100,250}` | — (consumables) |

### What Play actually returns

```
max   Rp 3.390.000 / P1M     Rp 33.490.000 / P1Y
pro   Rp   339.000 / P1M     Rp   309.000 / P1M
pro   Rp 3.390.000 / P1Y     Rp 3.090.000 / P1Y     (several base plans)
pro_back_to_school   not returned
```

**Zero offers, zero trials, zero discounts.** `pro-trial-1w` is configured and advertised by
RevenueCat but Play will not return it to this account.

## Why the hooks kept failing

`billing_watch.py` could never resolve `com.android.billingclient.*` in the Perplexity process,
even with the Play sheet on screen. The dex explains it:

```
revenuecat    285 string references
billingclient  25
$rc_annual / $rc_monthly   present
IInAppBillingService        2
com.android.vending.billing 7
```

So RevenueCat's *own* store implementation drives Play directly — no app-side BillingClient
classes to hook. The purchase sheet still opens (`SheetUiBuilderHostActivity`), which is how we
confirmed Play billing is in use at all.

## Claim check

Sheet readings, both real and back-out-able:

```
Perplexity Max   Starting today  Rp 33.490.000/year  GoPay **** 8271
Perplexity Pro   Starting today  Rp  3.090.000/year  GoPay **** 8271
```

Single phase, no trial line. Nothing claimed.

## Tooling used

```
appoffer.py --package ai.perplexity.app.android --max 2 --extra pro max pro_back_to_school
billing_watch.py --package ai.perplexity.app.android     (negative: no local BillingClient)
```

Product ids were **not** discoverable from dex or from a scan of app data before sign-in; they
came from the RevenueCat offerings cache once the app had fetched it.
