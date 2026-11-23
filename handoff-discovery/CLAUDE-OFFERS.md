# Claude offers — Play catalogue and the referral path

Session 2026-11-23 09:35. Account: `scripts4`, Play storefront **ID** (IDR).
App: `com.anthropic.claude` from Play, signed in.

## Verdict

**No Play offers of any kind.** Four products, every one a single full-price phase. No trial, no
introductory discount, no campaign namespace. Unlike ChatGPT, there is no RevenueCat layer caching a
hidden catalogue — the ids are plain dex strings and Play returns exactly those.

| Product | Offer | Phases | Price |
|---|---|---|---|
| `com.anthropic.claude.pro` | null | 1 | Rp 349.000 / P1M |
| `com.anthropic.claude.pro` | null | 1 | Rp 3.769.200 / P1Y |
| `com.anthropic.claude.max` | null | 1 | Rp 2.181.250 / P1M (5x) |
| `com.anthropic.claude.max` | null | 1 | Rp 4.362.500 / P1M (20x) |

43 candidate ids were queried inside the app process, including
`.team .business .enterprise .edu .student .free .pro.trial .trial .pro_monthly .max5x .max.5x
priority .api` — all returned nothing. The dex also carries legacy ids `claude-pro-monthly`,
`claude-pro-annual`, `claude_pro`, `claude_max` which are **not** live Play products.

## Billing stack

| Marker | Count in dex |
|---|---|
| `com.android.billingclient` | 18 |
| `billingclient` | 3 |
| revenuecat | **0** |
| stripe | 12 |

So Claude bills through Play directly (no RevenueCat indirection), which is why the product ids can
be read straight out of the dex instead of recovered from a cache. The presence of
`discountAmount` / `discountDisplayInfo` / `percentageDiscount` / `formattedDiscountAmount` strings
means the build *can* render discounted Play offers — Anthropic simply ships none for this account.

## The actual promo: referrals, not trials

There is no trial concept in this app at all. Keyword sweep over 169,734 dex strings:

```
"trial":        17 hits, all unrelated (nativeSetFieldTrials, tcpTrialPercent,
                trialSeconds, "trials_and_tribulations_of_high_school_football")
"student/edu":  30 hits, all Plaid account subtypes / speech education
```

What does exist is a referral / guest-pass programme:

```
"Invite a friend — if they subscribe you both get a bonus month."
"Give Claude Pro for free"
claudeai.referral.guest_pass.viewed / guest_pass.share_tapped
com.anthropic.claude.api.referral.ReferralEligibility     <- eligibility comes from the server
claudeai_guest_pass_referral_enabled                      <- remote flag
```

Plus gift codes, partly unsupported on this store:

```
"Current Play Store version doesn't support gift code purchase."
```

So the only free-Pro mechanism Claude ships is **invite a friend, both get a bonus month**, gated by
`ReferralEligibility` from the backend. Same class as the ChatGPT Plus trial: account-level, not a
SKU, not injectable — but unlike ChatGPT there is no "no payment trial" store offer to wait for.

## Tooling

```
claude_probe.py   dex + app-data scan for product ids; exits with an install hint if absent
claude_skus.py    query candidate ids through Play from inside the Claude process
```

Both read-only. `claude_skus.py` is the tool to re-run if Anthropic ever ships an offer: the moment
a product gains a second phase, it shows up as `phases=2`.
