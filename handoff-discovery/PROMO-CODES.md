# Google One promo codes — can they be generated?

Checked 2026-11-23 against the Google One APK (67,687 dex strings).

## What the client actually does

The entire code machinery is four names:

```
AssignEftPromoCode        (RPC: submit a code)
GetEftPromoCodeInfo       (RPC: fetch campaign metadata)
ASSIGN_PROMO_CODE         (result enum: success)
INVALID_PROMO_CODE        (result enum: rejected)
```

Supporting evidence that this is server-owned:

```
PROMO_API / PROMO_API_NOTIFICATION
campaign_id, campaignId, campaign_details, campaign_extra_referrer
PROMO_CONDITIONS_EVALUATED, PROMO_TARGETING_EVALUATED
PROMO_NOT_SHOWN_INVALID_PROMOTION
PROMO_NOT_SHOWN_DEVICE_CAPPED
```

There is **no** local validation table, no signing key, no code-generation routine, and no
client-side checksum in the APK. The app submits a string to Google's Promo API and reports the
result; every rule (campaign window, eligible account, device, already-redeemed) is evaluated
server-side.

**Conclusion: codes cannot be derived or manufactured client-side.** A "generated" code is only
valid if it is a row in Google's promo database. Brute-forcing that API is not a realistic path
either — it is rate-limited, tied to the signed-in account, and the failure enum
(`INVALID_PROMO_CODE`) is the only feedback channel, so guessing looks exactly like abuse.

## Where codes legitimately come from

| Source | Carries a code? |
|---|---|
| Device bundles (Xiaomi 17T/17T Pro, Oppo) | yes — issued at purchase, often to the buyer's Google account |
| Carrier bundles (Jio and similar) | yes — carrier-issued |
| Google promo emails / targeted campaigns | yes |
| Public campaign links (`one.google.com/offer/...`) | the link carries `campaign_id` / referrer, not a code |
| Student verification | no code — account entitlement after verification |
| Black Friday "specialoffer" | no code — server-applied pricing |

So a code is a **distribution artefact**: it exists because a partner paid for it and mailed it to a
specific buyer. When campaigns run, they do circulate publicly (forums, Telegram, Reddit), which is
the only realistic acquisition channel other than buying the device.

## What the toolkit can still do

`campaign_extra_referrer` plus `GetEftPromoCodeInfo` imply the app can resolve a campaign from an
**offer URL**. That makes a legitimate monitor possible: feed a public offer link into the app and read
whether the campaign is eligible for the account — no code required.

Not built yet; it would be `redeem_watch.py`: open a URL, watch Google One's campaign response, report
eligible / not-eligible / expired.

## Limitation of this research pass

`web_search` is unavailable in this session (HTTP 401 on the search endpoint), and Google's offer and
support pages render client-side, so a plain fetch returns either a login redirect or an empty shell.
Enumerating *currently live* public codes therefore was not possible here; the structural findings
above come from the APK, which is authoritative for the mechanism.
