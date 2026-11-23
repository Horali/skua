# ChatGPT offers â€” what is actually available

Session 2026-11-23 08:50â€“09:00. Account: clean burner, Play storefront **ID** (Indonesia, IDR).
App: `com.openai.chatgpt` from Play, signed in, free plan.

## How it was done

The app is Flutter with **RevenueCat over Google Play Billing**. Two paths were needed:

1. **Product ids are cached in plaintext** by RevenueCat â€” no injection:
   `/data/data/com.openai.chatgpt/shared_prefs/com_revenuecat_purchases_preferences.xml`
   (`offeringsResponse` key). Same JSON also in `cache/RevenueCat/etag_payloads/<sha>`.
2. **Query Play from inside the app's process**: Play only returns products belonging to the calling
   package, so the query must run in `com.openai.chatgpt`. The app's own billing classes are
   **R8-obfuscated** (only `ProxyBillingActivity` and `Purchase` keep their names â€” verified by parsing
   `class_defs` out of every dex: 97,341 classes, 3 billingclient hits, 11 revenuecat hits). So the
   toolkit injects its own BillingClient module instead.

### The loader trap

`module_521.apk` loaded with the app loader throws:

```
java.lang.IllegalAccessError: Interface com.google.android.gms.internal.play_billing.zzdf
implemented by class com.google.android.gms.internal.play_billing.zzak is inaccessible
(declaration ... appears in /data/local/tmp/module_521.apk)
```

The app ships its own copy of those classes and parent-first delegation collides. Loading with a `null`
parent fails the other way (`ClassNotFoundException: [Ljava/lang/Class;`). Working parent:

```java
DexClassLoader.$new("/data/local/tmp/module_521.apk",
    cacheDir, null,
    Java.use('java.lang.ClassLoader').getSystemClassLoader())
```

That sees the framework, not the app's colliding copy. Implemented as
`assets/frida/sku_probe_iso.js`.

## Catalogue (offerings, from RevenueCat cache)

| Product | Offering | Base plan / plan id |
|---|---|---|
| `oai.chatgpt.plus` | default, plus_annual_monthly | `oai-chatgpt-plus-1m-1999`, `oai-chatgpt-plus-1y-20000` |
| `oai.chatgpt.pro` | pro | `oai-chatgpt-pro-1m-20000` |
| `oai.chatgpt.go` | go | `oai-chatgpt-go-1m-1000` |
| `oai.chatgpt.prolite` | pro_lite | `oai-chatgpt-pro-1m-10000` |
| `oai.chatgpt.promax` | pro_max | `oai-chatgpt-promax-1m-50000` |
| â€” | credits_standard, credit_standard_v2 | empty |

`custom_web_checkout_enabled: true` â€” the app can also send users to web checkout.

## Play offers as returned (2026-11-23, storefront ID)

| Product | Offer id | Phases | Detail |
|---|---|---|---|
| `oai.chatgpt.go` | `2k8d9f8u1pmw6` | 2 | **Free / P6M** â†’ Rp 75.000/P1M |
| `oai.chatgpt.go` | `2a4xfuo8l6i6e` | 2 | **Free / P3M** â†’ Rp 75.000/P1M |
| `oai.chatgpt.go` | `2f5b7r49c7mj` | 2 | **Free / P1M** â†’ Rp 75.000/P1M |
| `oai.chatgpt.go` | `3y8r7e1mj2c1o` | 2 | **Free / P1M** â†’ Rp 75.000/P1M |
| `oai.chatgpt.go` | `null` | 1 | Rp 75.000/P1M |
| `oai.chatgpt.plus` | `1-month-10-dollars` | 2 | Rp 149.500/P1M â†’ Rp 299.000/P1M (50% off first month) |
| `oai.chatgpt.plus` | `null` | 1 | Rp 299.000/P1M |
| `oai.chatgpt.pro` | `null` | 1 | Rp 3.499.000/P1M |
| `oai.chatgpt.prolite` | `null` | 1 | Rp 1.689.000/P1M |
| `oai.chatgpt.promax` | `null` | 1 | Rp 8.445.000/P1M |

**ChatGPT Go carries zero-priced trials: 6 months, 3 months and 1 month.** None of these are rendered
in the app's paywall, which showed only "Get ChatGPT Plus" with no trial. Pro, Pro Lite and Pro Max
carry no offers at all.

This is the same class of finding as the Google One `eft-*` case: the offers exist in Play Billing and
are invisible in the product UI.

## Not yet tested

- **Claimability.** Opening the checkout for `2k8d9f8u1pmw6` (Free/P6M) and reading the sheet has not
  been done. That requires launching billing flow from inside the ChatGPT process with an Activity â€”
  the module loads, but `launchBillingFlow` against a Flutter activity is untested.
- Whether the Go trial is account-gated (the UI omits it, which is weak evidence of suppression) or
  simply unrendered.
- Region: storefront is `ID`. The community VPN-to-Japan reports are consistent with region-specific
  offers, but nothing here proves a different storefront yields different phases.

## Files

```
gpt_skus.py                      query ChatGPT products from its own process (read-only)
gptwatch.py                      observe the app's own billing calls (blocked: classes obfuscated)
assets/frida/sku_probe_iso.js    billing probe with system-classloader parent
assets/frida/gpt_probe.js        name-based hooks (kept: shows why they cannot work)
```
