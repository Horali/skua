/* billing_watch.js — log what an app itself asks Play for.
 *
 * For apps whose product ids are server-delivered (not in dex, not cached), this
 * hooks the app's own BillingClient calls and records:
 *   - QueryProductDetailsParams$Product$Builder.setProductId  (the SKUs it queries)
 *   - BillingFlowParams ... setOfferToken                       (tokens it buys with)
 *   - ProductDetails.getProductId in the flow params            (what it actually bought)
 *
 * Most apps ship the billing AAR unobfuscated (consumer rules keep the public API),
 * so these names resolve. If they do not, fall back to appoffer.py's dex scan.
 *
 * Read-only: logs only, never calls launchBillingFlow.
 */
var seen = {};

function emit(kind, value, src) {
  var sig = kind + "|" + value;
  if (seen[sig]) return;
  seen[sig] = 1;
  send({ ev: kind, value: String(value), src: src });
}

function hookOverloads(cls, method, tag, pick) {
  try {
    var C = Java.use(cls);
    var ovs = C[method].overloads;
    for (var i = 0; i < ovs.length; i++) {
      (function (ov) {
        ov.implementation = function () {
          try { pick(arguments); } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      })(ovs[i]);
    }
    send({ ev: "hooked", target: tag, overloads: ovs.length });
  } catch (e) {
    send({ ev: "hook_err", target: tag, m: String(e).slice(0, 140) });
  }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  hookOverloads("com.android.billingclient.api.QueryProductDetailsParams$Product$Builder",
    "setProductId", "QueryProduct.setProductId",
    function (a) { emit("sku", a[0], "query"); });

  hookOverloads("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder",
    "setOfferToken", "BillingFlowParams.setOfferToken",
    function (a) { emit("token", a[0], "flow"); });

  hookOverloads("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder",
    "setProductDetails", "BillingFlowParams.setProductDetails",
    function (a) {
      try { emit("sku", a[0].getProductId(), "flow"); } catch (e) { }
    });

  hookOverloads("com.android.billingclient.api.ProductDetails",
    "getProductId", "ProductDetails.getProductId",
    function () { });

  send({ ev: "armed" });
});
