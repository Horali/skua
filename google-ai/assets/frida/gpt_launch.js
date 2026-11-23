/* campaign_launch.js — open a checkout for a CAMPAIGN offer (offerId = "introprice").
 *
 * Fork of billing.js with one behavioural change: billing.js only ever selects
 * offers whose first phase is ZERO (the eft-* trials). Campaign discounts are
 * priced, so they were invisible to it — <core>.<N>months_ip_<P>p.acq returns
 * introprice with phase 1 = Rp 15.000 and phase 2 = Rp 309.000.
 *
 * Selection here is explicit: pick OFFER_ID ("introprice") on PRODUCTS[0]; if no
 * exact match, take the lowest non-zero first phase so a renamed campaign still
 * surfaces instead of silently falling back to full price.
 *
 * LIST_ONLY=true  -> query and report, never open a sheet.
 * LIST_ONLY=false -> open the checkout sheet. Nothing is confirmed: the sheet is
 *                    dismissed by the caller with a BACK keyevent.
 */
var dexLoader = null, ctxRef = null, clientRef = null;
var PRODUCTS = __PRODUCTS__;
var OFFER_ID = __OFFER_ID__;
var LIST_ONLY = __LIST_ONLY__;
var ACTIVITY_METHOD = "auto";

function L(v) { Java.classFactory.loader = v; }
function S(o) { send(o); }

function activityUsable(activity) {
  try {
    if (!activity || activity.isFinishing()) return false;
    try { if (activity.isDestroyed()) return false; } catch (_) { }
    return true;
  } catch (e) { return false; }
}

function getActivity() {
  L(null);
  var found = null;
  if (ACTIVITY_METHOD !== "thread") {
    try {
      Java.choose("android.app.Activity", {
        onMatch: function (a) { if (!found && activityUsable(a)) found = a; },
        onComplete: function () { }
      });
      if (found) {
        S({ ev: "activity_selected", method: "choose", name: String(found.getClass().getName()) });
        return found;
      }
    } catch (e) { S({ ev: "choose_err", m: String(e).slice(0, 200) }); }
  }
  if (ACTIVITY_METHOD !== "choose") {
    try {
      var Thread = Java.use("android.app.ActivityThread");
      var current = Thread.currentActivityThread();
      if (!current) throw new Error("currentActivityThread unavailable");
      var records = current.mActivities.value;
      if (!records) throw new Error("mActivities unavailable");
      var Record = Java.use("android.app.ActivityThread$ActivityClientRecord");
      for (var i = 0; i < records.size(); i++) {
        try {
          var rec = Java.cast(records.valueAt(i), Record);
          var act = rec.activity.value;
          if (activityUsable(act)) { found = act; break; }
        } catch (e) { }
      }
      if (found) {
        S({ ev: "activity_selected", method: "thread", name: String(found.getClass().getName()) });
        return found;
      }
    } catch (e) { S({ ev: "activity_thread_err", m: String(e).slice(0, 200) }); }
  }
  S({ ev: "no_activity", method: ACTIVITY_METHOD });
  return null;
}

function boot() {
  Java.perform(function () {
    try {
      L(null);
      ctxRef = Java.use("android.app.ActivityThread").currentApplication().getApplicationContext();
      var DexClassLoader = Java.use("dalvik.system.DexClassLoader");
      dexLoader = DexClassLoader.$new("/data/local/tmp/module_521.apk",
        ctxRef.getCodeCacheDir().getAbsolutePath(), null, Java.use('java.lang.ClassLoader').getSystemClassLoader());
      L(dexLoader);
      var BillingClient = Java.use("com.android.billingclient.api.BillingClient");
      var PUL = Java.use("com.android.billingclient.api.PurchasesUpdatedListener");
      var Lst = Java.registerClass({
        name: "cl.A" + Date.now(), implements: [PUL], methods: {
          onPurchasesUpdated: function (r, p) {
            S({ ev: "purchase_cb", code: r.getResponseCode(), msg: String(r.getDebugMessage() || "") });
          }
        }
      });
      var b = BillingClient.newBuilder(ctxRef);
      b.setListener(Lst.$new());
      try { b.enablePendingPurchases(); } catch (e) { }
      clientRef = b.build();
      var SLL = Java.use("com.android.billingclient.api.BillingClientStateListener");
      var SL = Java.registerClass({
        name: "cl.B" + Date.now(), implements: [SLL], methods: {
          onBillingSetupFinished: function (r) {
            S({ ev: "setup", code: r.getResponseCode() });
            if (r.getResponseCode() === 0) query();
          },
          onBillingServiceDisconnected: function () { S({ ev: "disc" }); }
        }
      });
      clientRef.startConnection(SL.$new());
      S({ ev: "connecting", products: PRODUCTS, offer: OFFER_ID, list_only: LIST_ONLY });
    } catch (e) {
      S({ ev: "boot_err", m: String(e).slice(0, 240) });
    }
  });
}

function query() {
  try {
    L(dexLoader);
    var Prod = Java.use("com.android.billingclient.api.QueryProductDetailsParams$Product");
    var Params = Java.use("com.android.billingclient.api.QueryProductDetailsParams");
    var PDL = Java.use("com.android.billingclient.api.ProductDetailsResponseListener");

    var PL = Java.registerClass({
      name: "cl.C" + Date.now(), implements: [PDL], methods: {
        onProductDetailsResponse: function (res, list) {
          S({ ev: "pd", code: res.getResponseCode(), n: (list ? list.size() : 0) });
          if (!list || list.size() === 0) { S({ ev: "no_product", code: res.getResponseCode() }); return; }
          L(dexLoader);
          var PD = Java.use("com.android.billingclient.api.ProductDetails");
          var SOD = Java.use("com.android.billingclient.api.ProductDetails$SubscriptionOfferDetails");
          var PP = Java.use("com.android.billingclient.api.ProductDetails$PricingPhase");

          var best = null, bestMicros = null;
          for (var i = 0; i < list.size(); i++) {
            var pd = Java.cast(list.get(i), PD);
            var pid = String(pd.getProductId());
            var offs = pd.getSubscriptionOfferDetails();
            if (!offs || offs.size() === 0) { S({ ev: "no_offers", product: pid }); continue; }
            for (var j = 0; j < offs.size(); j++) {
              var o = Java.cast(offs.get(j), SOD);
              var oid = String(o.getOfferId());
              var tok = String(o.getOfferToken());
              var phases = [];
              var ph = o.getPricingPhases().getPricingPhaseList();
              for (var k = 0; k < ph.size(); k++) {
                var pp = Java.cast(ph.get(k), PP);
                phases.push({
                  micros: String(pp.getPriceAmountMicros()),
                  period: String(pp.getBillingPeriod()),
                  formatted: String(pp.getFormattedPrice())
                });
              }
              var firstMicros = phases.length ? phases[0].micros : "0";
              S({
                ev: "offer", product: pid, id: oid, token: tok,
                title: String(pd.getTitle()), phases: phases
              });

              var candidate = { pd: pd, offer: o, product: pid, id: oid, token: tok, phases: phases };
              if (OFFER_ID && oid === OFFER_ID) {
                // Exact campaign match wins immediately.
                if (!best || (best && best.id !== OFFER_ID)) best = candidate;
              } else if (best === null || (best && best.id !== OFFER_ID)) {
                // Fallback: cheapest non-zero first phase (a renamed campaign).
                try {
                  if (firstMicros !== "0") {
                    if (bestMicros === null || Number(firstMicros) < Number(bestMicros)) {
                      best = candidate; bestMicros = firstMicros;
                    }
                  }
                } catch (e) { }
              }
            }
          }

          if (!best) { S({ ev: "no_campaign", offer_id: OFFER_ID }); return; }
          S({
            ev: "chosen", product: best.product, id: best.id,
            first: best.phases.length ? best.phases[0].formatted : "",
            first_micros: best.phases.length ? best.phases[0].micros : "",
            period: best.phases.length ? best.phases[0].period : "",
            phases: best.phases.length
          });

          if (LIST_ONLY) {
            S({ ev: "list_only", product: best.product, id: best.id, token: best.token });
            return;
          }
          launch(best.pd, best.offer);
        }
      }
    });

    var arr = Java.use("java.util.ArrayList").$new();
    for (var n = 0; n < PRODUCTS.length; n++) {
      arr.add(Prod.newBuilder().setProductId(PRODUCTS[n]).setProductType("subs").build());
    }
    L(dexLoader);
    clientRef.queryProductDetailsAsync(Params.newBuilder().setProductList(arr).build(), PL.$new());
    S({ ev: "query_sent", n: PRODUCTS.length });
  } catch (e) {
    S({ ev: "query_err", m: String(e).slice(0, 240) });
  }
}

/* Same mechanics as billing.js launch(): no SubscriptionUpdateParams — this is a
 * first purchase, not a replacement. Stacking params belong to the stack path. */
function launch(pd, offer) {
  try {
    L(dexLoader);
    var PDP = Java.use("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams");
    var BFP = Java.use("com.android.billingclient.api.BillingFlowParams");
    var pdp = PDP.newBuilder().setProductDetails(pd).setOfferToken(String(offer.getOfferToken())).build();
    var l = Java.use("java.util.ArrayList").$new();
    l.add(pdp);
    var params = BFP.newBuilder().setProductDetailsParamsList(l).build();
    var act = getActivity();
    S({ ev: "activity", a: act ? String(act.getClass().getName()) : "null" });
    if (!act) { S({ ev: "no_activity_launch" }); return; }

    L(null);
    var Handler = Java.use("android.os.Handler");
    var Looper = Java.use("android.os.Looper");
    var R = Java.registerClass({
      name: "cl.R" + Date.now(), implements: [Java.use("java.lang.Runnable")], methods: {
        run: function () {
          try {
            L(dexLoader);
            var Activity = Java.use("android.app.Activity");
            var res = clientRef.launchBillingFlow(Java.cast(act, Activity), params);
            S({ ev: "launched", code: res.getResponseCode(), msg: String(res.getDebugMessage() || "") });
          } catch (e) { S({ ev: "launch_err", m: String(e).slice(0, 240) }); }
        }
      }
    });
    Handler.$new(Looper.getMainLooper()).post(R.$new());
  } catch (e) {
    S({ ev: "launch_outer_err", m: String(e).slice(0, 240) });
  }
}

var __tries = 0;
var iv = setInterval(function () {
  try {
    L(null);
    var a = Java.use("android.app.ActivityThread").currentApplication();
    __tries++;
    if (a || __tries > 10) { clearInterval(iv); S({ ev: "boot_start", app: !!a, tries: __tries }); boot(); }
  } catch (e) {
    __tries++;
    if (__tries > 10) {
      clearInterval(iv);
      S({ ev: "boot_force", m: String(e).slice(0, 120) });
      try { boot(); } catch (e2) { S({ ev: "boot_fail", m: String(e2).slice(0, 200) }); }
    }
  }
}, 400);
