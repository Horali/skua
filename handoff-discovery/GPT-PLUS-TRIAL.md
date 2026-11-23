# ChatGPT Plus trial — why it cannot be reached by injection

Follow-up to `GPT-OFFERS.md`. Question was whether the Plus trial (or the "random
1-month trial" people report) can be found and injected the way the Google One
`eft-*` offers were.

## Short answer

No. It is not a Play Billing offer, so there is no token to capture and no SKU to
enumerate. It is a **backend-issued "no payment trial" grant** that the app renders when
the server says the account is in the cohort.

## Evidence 1 — Play has no Plus trial, verified by enumeration

`gpt_skus.py` against `oai.chatgpt.plus`, plus 37 hand-built candidate product ids
(`oai.chatgpt.plus.trial`, `.intro`, `.promo`, `.student`, `.free`, `plustrial`,
`chatgpt.plus`, …). Result: only the five real products exist, and Plus carries exactly
two entries — `1-month-10-dollars` and the null base plan.

```
oai.chatgpt.plus   offer=1-month-10-dollars   phases=2   Rp 149.500/P1M | Rp 299.000/P1M
oai.chatgpt.plus   offer=null                phases=1   Rp 299.000/P1M
```

Offer tokens are issued by Play per account. There is no code path that mints a token
for an offer Play will not return; `launchBillingFlow` validates it. Injection is not a
matter of effort here, it is a matter of cryptography the client does not hold.

## Evidence 2 — the app has Plus-trial UI, gated by the backend

`assets/chatgpt_subscription_pricing.valdimodule` (506 KB, zstd-compressed, 11.4 MB
decompressed) contains the pricing flow's message catalogue. Trial keys present:

```
subscriptions_promo_trial_intro_title / _body / _ready_title / _ready_body
subscriptions_promo_trial_intro_try_plus / _try_go / _get_started / _later
subscriptions_no_payment_trial_plus_title / _subtitle
subscriptions_store_offer_trial_title / _renewal
subscriptions_compare_offer_free_trial / _trial_terms
subscriptions_offer_claim_offer
subscriptions_checkout_skip_offer
```

Descriptions in the same catalogue confirm the semantics:

- "Headline announcing an available ChatGPT Plus trial offer. **The user still needs to
  claim it; access has not started.**"
- "ChatGPT Plus trial introduction. Opens the eligible offer's next purchase step; does
  not itself start the trial."
- "…shown before a user opens pricing for **an eligible free trial**"

So the feature exists in the shipped binary and is driven by an eligibility payload. Our
account receives nothing, which is why the paywall rendered no trial.

## Evidence 3 — the web surface is not reachable from this device

Attempted the obvious interception routes; all are closed on this build:

| Route | Result |
|---|---|
| Browser + DevTools | no browser package installed at all (`pm list packages \| grep -E 'chrome\|browser'` → empty) |
| App WebView DevTools | no `webview_devtools_remote` socket; `setWebContentsDebuggingEnabled` not set |
| Replay API from host | tokens are `DPoP` (`com.auth0.token_type = DPoP`); proof-of-possession signed by a device-bound key, so a stolen JWT is not a credential |
| TLS interception | app is Valdi/native (C++), not Flutter; no Java HTTP stack to hook |

The app's API base is `https://android.chat.openai.com/public-api/` and its Valdi bundle
is delivered from `persistent.oaistatic.com/valdi-dil/...`; both were recovered from
`valdi_dynamic_delivery_endpoint_policies.xml`.

## What actually controls this

The trial is assigned server-side per account. The only variables under our control are
**which account** (cohort) and **which storefront**. For this account, storefront `ID`:

- Plus: `1-month-10-dollars` only (50% off first month)
- Go: zero-priced trials of 6, 3 and 1 months

## Cheap next experiment

Per account, the signal is a single UI string. Open the paywall and dump the view tree:

- trial present → `subscriptions_promo_trial_intro_*` text renders ("Try Plus" / "Claim offer")
- trial absent → plain price list

`gpt_trial_watch.py` targets exactly that: open paywall, dump text, grep for the markers,
report eligible / not eligible. It is a cohort detector, not a claim tool.
