/* Offer discovery probe — enumerate every Play Billing offer for a list of SKUs.
 *
 * Injected into the Google One process. Unlike billing.js this does NOT select
 * an offer and does NOT call launchBillingFlow: it is read-only.
 *
 * __PRODUCTS__ is replaced by the orchestrator with a JSON array of product IDs.
 * Play ignores invalid IDs, so a wide candidate list is cheap.
 */
var PRODUCTS = __PRODUCTS__;
var CHUNK = 20; // queryProductDetailsAsync accepts up to 20 products per call
var dexLoader = null, ctxRef = null, clientRef = null;

function L(v) { Java.classFactory.loader = v; }
function S(o) { send(o); }

function boot() {
  Java.perform(function () {
    try {
      L(null);
      var AT = Java.use("android.app.ActivityThread");
      ctxRef = AT.currentApplication().getApplicationContext();
      var DexClassLoader = Java.use("dalvik.system.DexClassLoader");
      dexLoader = DexClassLoader.$new(
        "/data/local/tmp/module_521.apk",
        ctxRef.getCodeCacheDir().getAbsolutePath(),
        null,
        Java.use('java.lang.ClassLoader').getSystemClassLoader());
      L(dexLoader);

      var BillingClient = Java.use("com.android.billingclient.api.BillingClient");
      var PUL = Java.use("com.android.billingclient.api.PurchasesUpdatedListener");
      var Lst = Java.registerClass({
        name: "ow.L" + Date.now(), implements: [PUL],
        methods: { onPurchasesUpdated: function (r, p) { } }
      });
      var b = BillingClient.newBuilder(ctxRef);
      b.setListener(Lst.$new());
      try { b.enablePendingPurchases(); } catch (e) { }
      clientRef = b.build();

      var SLL = Java.use("com.android.billingclient.api.BillingClientStateListener");
      var SL = Java.registerClass({
        name: "ow.S" + Date.now(), implements: [SLL],
        methods: {
          onBillingSetupFinished: function (r) {
            S({ ev: "setup", code: r.getResponseCode() });
            if (r.getResponseCode() === 0) query(0);
          },
          onBillingServiceDisconnected: function () { S({ ev: "disc" }); }
        }
      });
      clientRef.startConnection(SL.$new());
      S({ ev: "connecting", count: PRODUCTS.length });
    } catch (e) {
      S({ ev: "boot_err", m: String(e).slice(0, 300) });
    }
  });
}

function query(offset) {
  if (offset >= PRODUCTS.length) { S({ ev: "done", total: PRODUCTS.length }); return; }
  var chunk = PRODUCTS.slice(offset, offset + CHUNK);
  try {
    L(dexLoader);
    var Prod = Java.use("com.android.billingclient.api.QueryProductDetailsParams$Product");
    var Params = Java.use("com.android.billingclient.api.QueryProductDetailsParams");
    var PDL = Java.use("com.android.billingclient.api.ProductDetailsResponseListener");

    var items = [];
    for (var i = 0; i < chunk.length; i++) {
      items.push(Prod.newBuilder().setProductId(chunk[i]).setProductType("subs").build());
    }
    // setProductList expects java.util.List, not a Java array.
    var ArrayList = Java.use("java.util.ArrayList");
    var plist = ArrayList.$new();
    for (var a = 0; a < items.length; a++) plist.add(items[a]);
    var params = Params.newBuilder().setProductList(plist).build();

    var RL = Java.registerClass({
      name: "ow.R" + Date.now() + "_" + offset, implements: [PDL],
      methods: {
        onProductDetailsResponse: function (res, list) {
          try {
            S({ ev: "pd", code: res.getResponseCode(), n: (list ? list.size() : 0), offset: offset });
            if (list && list.size() > 0) {
              L(dexLoader);
              var PD = Java.use("com.android.billingclient.api.ProductDetails");
              var SOD = Java.use("com.android.billingclient.api.ProductDetails$SubscriptionOfferDetails");
              var PP = Java.use("com.android.billingclient.api.ProductDetails$PricingPhase");
              for (var k = 0; k < list.size(); k++) {
                var pd = Java.cast(list.get(k), PD);
                var pid = String(pd.getProductId());
                var offs = pd.getSubscriptionOfferDetails();
                if (!offs || offs.size() === 0) {
                  S({ ev: "product", product: pid, offers: 0, title: String(pd.getTitle()) });
                  continue;
                }
                for (var j = 0; j < offs.size(); j++) {
                  var o = Java.cast(offs.get(j), SOD);
                  var phases = [];
                  var lst = o.getPricingPhases().getPricingPhaseList();
                  for (var p = 0; p < lst.size(); p++) {
                    var pp = Java.cast(lst.get(p), PP);
                    phases.push({
                      micros: String(pp.getPriceAmountMicros()),
                      period: String(pp.getBillingPeriod()),
                      currency: String(pp.getPriceCurrencyCode()),
                      formatted: String(pp.getFormattedPrice())
                    });
                  }
                  S({
                    ev: "offer", product: pid, id: String(o.getOfferId()),
                    token: String(o.getOfferToken()), phases: phases,
                    title: String(pd.getTitle())
                  });
                }
              }
            }
          } catch (e) {
            S({ ev: "parse_err", m: String(e).slice(0, 300) });
          }
          query(offset + CHUNK);
        }
      }
    });
    clientRef.queryProductDetailsAsync(params, RL.$new());
  } catch (e) {
    S({ ev: "query_err", m: String(e).slice(0, 300) });
    query(offset + CHUNK);
  }
}

Java.perform(boot);
