# Coding-agent apps — Play offer sweep

Session 2026-11-23 11:47–12:05. Account `scripts4`, storefront **ID** (IDR).
Goal: apps whose product is a coding agent / coding-capable Pro plan, swept with `appoffer.py`.

## Availability in the ID storefront

| Package | Play install here | Billing stack | Offers |
|---|---|---|---|
| `com.replit.app` | ✅ installed | stock BillingClient (265 refs), no RevenueCat | not yet enumerated (needs sign-in) |
| `ai.mistral.chat` | ✅ installed, signed in | stock BillingClient (352 refs), no RevenueCat | **none** — see below |
| `ai.x.grok` | ❌ "available only for your other devices" | — | — |
| `com.poe.android` | ❌ same | — | — |
| `com.you.android` | ❌ not in storefront | — | — |
| `com.blackboxai.blackbox` | ❌ not in storefront | — | — |
| `com.codesandbox.android` | ❌ not in storefront | — | — |

Grok and Poe both render an Install button bound to the physical phone (`SM-S936B`), not the emulator
(`SM-G9980`); installing there was not attempted.

## Mistral (Vibe Pro)

Plan screen, verified by screenshot:

```
Monthly   Rp 269.000/mo          Yearly  Rp 2.590.000/yr  [20% off]
"All-day coding in the CLI, on web or in the app."
```

Both checkouts, read from Play's own sheet:

```
Vibe Pro  Starting today  Rp   269.000/month   + tax   GoPay **** 8271
Vibe Pro  Starting today  Rp 2.590.000/year    + tax   GoPay **** 8271
```

**Single phase in both.** No trial, no intro discount. The "20% off" badge is arithmetic baked into the
yearly base plan (269.000 × 12 = 3.228.000 → 2.590.000), not a Play offer phase.

## Detection notes

- Neither app carries product ids in its dex, and neither uses RevenueCat, so the two shortcuts that
  worked on Claude (dex strings) and ChatGPT/Perplexity (RevenueCat `offeringsResponse`) do not apply.
- `billing_watch --multiloader` instrumented both builder classes in both loaders on Mistral, and still
  captured no `setProductId`. Same shape as Duolingo: Play sheet opens, hooks stay silent. Warning for
  the next attempt: these apps appear to query through a path that bypasses the Java builders we hook.
- Phase information is therefore taken from the Play sheet, which is authoritative for what would be
  charged but does not yield the SKU id.

## Next

- Replit: sign in, open its Pro screen, repeat the sheet read. It is the only remaining true coding
  agent available on this storefront.
- If SKU ids ever become necessary, the remaining avenue is native-level interception, which is a much
  larger build and has not been attempted.
