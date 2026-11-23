/* Product-ID sniffer â€” capture the SKU strings Google One actually requests.
 *
 * Hooks the generic key/value write paths that the app (and the Play billing
 * stack inside it) use when building request payloads, and reports any value
 * that looks like a Play product id. Combined with tapping through the plans
 * UI, this reveals the *real* catalogue instead of guessed names.
 *
 * Read-only: hooks writes, never modifies them.
 */
var HIT_KEY = /^(product_?id|sku_?id|sku|productid|product)$/i;
var HIT_VAL = /^g1\.[A-Za-z0-9_.]{2,48}$/;
var seen = {};

function S(o) { send(o); }

function remember(v, src) {
  if (!v || typeof v !== "string") return;
  if (!HIT_VAL.test(v)) return;
  if (seen[v]) return;
  seen[v] = src;
  S({ ev: "id", value: v, src: src });
}

function hookJsonPut() {
  try {
    var JO = Java.use("org.json.JSONObject");
    var put = JO.put.overload("java.lang.String", "java.lang.Object");
    put.implementation = function (k, v) {
      try {
        if (k && HIT_KEY.test(String(k))) remember(String(v), "JSONObject.put(" + k + ")");
        else remember(String(v), "JSONObject.value");
      } catch (e) { }
      return put.call(this, k, v);
    };
    S({ ev: "hooked", target: "JSONObject.put" });
  } catch (e) { S({ ev: "hook_err", target: "JSONObject.put", m: String(e).slice(0, 200) }); }
}

function hookBundle() {
  try {
    var B = Java.use("android.os.Bundle");
    var putString = B.putString.overload("java.lang.String", "java.lang.String");
    putString.implementation = function (k, v) {
      try {
        if (k && HIT_KEY.test(String(k))) remember(String(v), "Bundle.putString(" + k + ")");
        else remember(String(v), "Bundle.value");
      } catch (e) { }
      return putString.call(this, k, v);
    };
    S({ ev: "hooked", target: "Bundle.putString" });
  } catch (e) { S({ ev: "hook_err", target: "Bundle.putString", m: String(e).slice(0, 200) }); }
}

function hookIntent() {
  try {
    var I = Java.use("android.content.Intent");
    var putExtra = I.putExtra.overload("java.lang.String", "java.lang.String");
    putExtra.implementation = function (k, v) {
      try {
        if (k && HIT_KEY.test(String(k))) remember(String(v), "Intent.putExtra(" + k + ")");
      } catch (e) { }
      return putExtra.call(this, k, v);
    };
    S({ ev: "hooked", target: "Intent.putExtra" });
  } catch (e) { S({ ev: "hook_err", target: "Intent.putExtra", m: String(e).slice(0, 200) }); }
}


function hookBillingBuilders() {
  // The app builds billing params through Builders, not JSON. This is the
  // authoritative place to see which product id the UI is about to request.
  try {
    var PB = Java.use("com.android.billingclient.api.QueryProductDetailsParams$Product$Builder");
    var sp = PB.setProductId.overload("java.lang.String");
    sp.implementation = function (id) {
      try { remember(String(id), "QueryProductDetailsParams.setProductId"); } catch (e) { }
      return sp.call(this, id);
    };
    S({ ev: "hooked", target: "QueryProductDetailsParams.Product.Builder" });
  } catch (e) { S({ ev: "hook_err", target: "QueryProductDetailsParams.Builder", m: String(e).slice(0, 200) }); }

  try {
    var PD = Java.use("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder");
    var sp2 = PD.setProductDetails.overload("com.android.billingclient.api.ProductDetails");
    sp2.implementation = function (pd) {
      try {
        if (pd) remember(String(pd.getProductId()), "BillingFlowParams.setProductDetails");
      } catch (e) { }
      return sp2.call(this, pd);
    };
    S({ ev: "hooked", target: "BillingFlowParams.ProductDetailsParams.Builder" });
  } catch (e) { S({ ev: "hook_err", target: "BillingFlowParams.Builder", m: String(e).slice(0, 200) }); }
}
Java.perform(function () {
  S({ ev: "sniffer_start" });
  hookJsonPut();
  hookBundle();
  hookIntent();
  hookBillingBuilders();
  S({ ev: "ready", hooked: 5 });
});

