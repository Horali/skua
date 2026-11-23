# Spotify — channel-split offer, confirmed on Play

Session 2026-11-23 10:47–10:52. Account `scripts4`, storefront **ID** (IDR).
App: `com.spotify.music`, signed in, Premium tab opened.

## The finding

Spotify runs the same campaign on two channels and **prices them differently**. The checkout
screen says so explicitly, and switching the radio button rewrites the price:

| Channel | Now | After |
|---|---|---|
| Spotify direct | **Rp 29.900 for 3 months** | Rp 59.900/month |
| **Google Play** | **Rp 59.900 for the 3-month period** | Rp 59.900/month |

UI text, verbatim:

```
Listen without limits. Try 3 months of Premium Standard for Rp 29.900 with Spotify.
Rp 29.900 for 3 months, then Rp 59.900 per month after. Offer only available if you
haven't tried Premium before and you subscribe via Spotify.
Offers via Google Play may differ. Terms apply. Offer ends 31 December 2026.

[after selecting Google Play]
Offers are different when you purchase with a Google Play account.
Now: 3 months for Rp 59.900 + tax
Starting on 23 Feb 2027: Rp 59.900 + tax / month
```

Play's own sheet then renders two phases:

```
Premium Standard | Spotify: Music and Podcasts
Today · 3-month period      Rp 59.900 + tax
Starting 23 Feb 2027        Rp 59.900/month + tax
...reminder 7 days before your intro price ends
GoPay: **** 8271 | Subscribe
```

So the Play product carries an **intro-period offer** (phase 1 = one 3-month period, phase 2 =
monthly). It is a real discount versus list (3 × Rp 59.900 = Rp 179.700), just a worse one than
Spotify's own channel — which is likely why they keep the checkout split.

## Why the SKU could not be captured

- `billing_watch.py` never resolves: `ClassNotFoundException` for
  `com.android.billingclient.api.QueryProductDetailsParams$Product$Builder` — **even with the Play
  sheet open**, i.e. the purchase flow live.
- Dex shows `com.spotify.gpb.*` activities (`com.spotify.gpb.choicescreenuc.ChoiceScreenUcActivity`),
  Spotify's own Google-Play-Billing wrapper. The Play integration is native, not the Java SDK.
- `Java.choose` is unusable here anyway (`EnsurePluginLoaded` export missing on this ART build).
- 14 hand-built candidate ids (`spotify_premium*`, `premium_*`, `premium`, …) all returned nothing,
  so the ids are server-delivered.

## Status

Verified by sheet, not by id. Claim path works: Play sheet → Subscribe → Rp 59.900 covers three
months, first monthly renewal 23 Feb 2027. The cheaper route is Spotify direct at Rp 29.900 for the
same three months, which is an in-app PSP checkout rather than Play.

## Contrast worth keeping

| App | Play offer found | Kind |
|---|---|---|
| Google One | 21 offers, up to 18 months free | zero-price |
| ChatGPT Go | 6 / 3 / 1 month free | zero-price |
| Duolingo | 7-day free trial | zero-price |
| **Spotify** | **3-month intro period at list price** | **discounted phase** |
| Claude | none | — |
| Perplexity | none granted (config only) | — |

Spotify is the first non-Google app where Play returns a **discounted** first phase rather than a
free one.
