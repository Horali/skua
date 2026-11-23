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

---

## The Jio activation page, seen directly (2026-11-23)

A screenshot of a live Jio activation link shows what a carrier EFT actually is:

```
Badges : "Penawaran berakhir 26 Okt"   (offer ended 26 Oct)
         "Tidak perlu bayar"            (no payment required)
Title  : "Aktifkan paket Google AI Pro Anda dari Jio
          seharga ₹35.100* gratis selama 18 bulan"
Charge : "Anda membayar: ₹0"    ->  [ Aktifkan paket ]
Footer : status langganan dibagikan kepada Jio untuk memulai,
         menghentikan, atau mengubah paket Anda.
```

URL shape:

```
one.google.com/u/1/activate-plan/subscription/new/AQCpilGy_JiaeaAJ-43QonOH9ZJTZuWZRUkPGE94fiWu6k8ViP18V-AVhKS2j9AT5byZCyplq7sQo3-86eHQ...
```

### What this establishes

1. **The carrier grant is the same 18-month product we already enumerated.** `gratis selama 18 bulan` maps to
   `g1.2tb.ai.18months_eft` -> offer `eft-18months` -> Free / **P1Y6M**, which this session verified is
   claimable on a clean Play account for Rp 0. A carrier link grants the same entitlement; it is not a
   different or better plan.
2. **Activation links are one-time tokens.** The path carries an opaque `AQCpilGy...` token, the page is
   account-scoped (`/u/1/`), and the shown offer had already ended 26 Oct and been claimed. Nothing in that
   URL is reusable.
3. **These links open in a browser, not the app.** Google One's manifest claims `/redeemoffer` and `/ai*`
   only — not `/u/*/activate-plan/*` — so Chromium renders them. `redeem_watch.py` handles that path via
   the system resolver.
4. The page states the subscription is **shared with the carrier** for start/stop/change. So the entitlement
   is carrier-managed, which is consistent with the CPID/partner-offer subsystem in §11: eligibility and
   lifecycle live server-side, and the link is only a claim ticket.

### Practical consequence

There is nothing to extract from a claimed, expired token. A *fresh* unclaimed activation link is the only
useful input, and even then the outcome for a non-Indian account is expected to be UNAVAILABLE or
NOT ELIGIBLE — worth measuring once, with `redeem_watch.py`, if such a link is ever available.

---

## Dissection: how a partner activation actually authenticates

Two delivery channels, both server-issued, neither forgeable client-side.

### Channel A — activation token (the Jio link)

```
https://serviceactivation.google.com/activate-plan/subscription/new/<opaque token>
```

- Host is **not referenced anywhere** in the Google One APK (`serviceactivation` and `activate-plan`: 0 hits),
  and the bare host 404s. So the flow is web-only; the app is not a participant.
- Auth = the normal Google account session. The token identifies the purchased entitlement; the server binds it
  to whichever account is signed in at redemption, once.
- The token in the screenshot was already consumed and the campaign closed 26 Oct; the live check returns 404.

### Channel B — install referrer campaign (the mechanism that matters for Xiaomi)

The APK consumes Play's Install Referrer:

```
com.android.vending.INSTALL_REFERRER
com.google.android.finsky.BIND_GET_INSTALL_REFERRER_SERVICE
ImmediatePurchaseFragment / StartImmediatePurchase
campaignId, gclid, gbraid, gad_campaignid, pcampaignid
PerkByCampaignIdCache.db, UserBenefitsByCampaignIdCache.db
GetEftPromoCodeInfo
```

So a partner campaign is delivered as a **referrer string recorded by Play at install time**, containing a
`campaignId`. The app reads it, asks Google's promo API about that campaign, and renders
an immediate-purchase or redeem fragment if the server says the account qualifies.

**This explains the spoof failure in §11.1 exactly.** The gate is
`(account, campaignId from install referrer, server-side entitlement)` — not `Build.MODEL`. Spoofing the
device changes a value the eligibility decision never reads, which is why the app did not even run an
eligibility check.

### The one testable lever left for the Xiaomi route

Play honours a `referrer` parameter on install links:

```
https://play.google.com/store/apps/details?id=com.google.android.apps.subscriptions.red&referrer=campaignId%3D<ID>
```

Meaning: uninstall Google One, reinstall it via a link carrying a known `campaignId`, and Play will store
that referrer for (package, account). The app then evaluates the campaign for our account.

This is **not** a spoof — it is the delivery mechanism itself, reproduced. The server still decides eligibility
(carrier/device/region/cohort), so success is not guaranteed, but it is the only path that exercises the real
check without a purchase.

Prerequisite: at least one real `campaignId` for a device/carrier EFT campaign. Known fragments from the APK:
`FAMILY_SHARING` (a different campaign), `GEMINI_DEVICE_EFT` (a campaign family name, not necessarily an id).

---

## Finding the campaign id — what the client will and will not reveal

### The real entry point

The account's own CTA cache (databases/g1_sdk_database_<account>, table `rpc_cache`, 35 `GET_CTA_CONFIG`
rows) contains the partner onboarding URL:

```
https://one.google.com/partner-eft-onboard
```

That is the page the Xiaomi/Jio-style partner flow funnels through — not a token URL and not the
`serviceactivation` host.

### What it does without a valid campaign

```
GET https://one.google.com/partner-eft-onboard                -> 404 "We can't display the page"
GET ...?campaignId=test                                       -> 404
GET ...?campaign_id=test                                      -> 404
GET ...?token=test                                            -> 404
```

So the page requires context the client cannot invent. Campaign ids are **server-issued per campaign**
and are not present in the APK: a scan for campaign-id-shaped UPPER_SNAKE constants returns 5,086 names,
but they are UI element ids (`CHECK_PARTNER_OFFER_PAGE`, `AI_CREDITS_PURCHASE_CTA` …), not campaign ids.

### How the app can receive a campaign

Two paths, both already documented above:

1. **Play install referrer** — `campaignId` inside the referrer recorded at install time.
2. **Deep link** — the DeepLink activity logs `No link parameter found for Google One deep link … Falling
   back to the original URL`, i.e. it expects a `link=` parameter. Injecting an activity referrer via
   `am start --es android.intent.extra.REFERRER` produces no campaign handling; only that warning.

### Where the id therefore comes from in practice

| Source | Contains campaign id? |
|---|---|
| Partner marketing email / retailer page (Xiaomi, Jio) | yes — in the link path or Play referrer |
| Play install link with `&referrer=campaignId%3D…` | yes |
| Google One CTA config (server) | path only, no id |
| APK constants | no |
| Guessing the endpoint | no — every probe 404s |

Practical consequence: the only way forward is to **capture an id from a real partner link**, then replay it
via the install-referrer path (`referrer_replay`). Nothing on the client can synthesise one.
