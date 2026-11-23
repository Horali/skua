/* gpt_probe.js — capture ChatGPT's real product identifiers.
 *
 * The app is Flutter + RevenueCat over Play Billing. Two choke points:
 *   1. RevenueCat's Offering/Package objects — the offering config lists every
 *      package in the campaign, including ones the paywall does not render.
 *   2. Play Billing's QueryProductDetailsParams$Product$Builder.setProductId and
 *      BillingFlowParams — the actual SKUs and offer tokens handed to Play.
 *
 * Targeted Java.use only. Do NOT enumerateLoadedClasses here: on this app it
 * segfaults inside frida-agent and takes the process down.
 */
var RE_SKU = /^g1\.[A-Za-z0-9_.]{1,48}$/;
var seen = {};

function emit(kind, src, value, extra) {
  var sig = kind + "|" + src + "|" + value;
  if (seen[sig]) return;
  seen[sig] = 1;
  var p = { ev: kind, src: src, value: String(value) };
  if (extra) p.extra = String(extra);
  send(p);
}

function tryHook(cls, method, tag, pick) {
  try {
    var C = Java.use(cls);
    var ovs = C[method].overloads;
    for (var i = 0; i < ovs.length; i++) {
      (function (ov) {
        var orig = ov.implementation;
        ov.implementation = function () {
          try { pick(arguments); } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      })(ovs[i]);
    }
    send({ ev: "hooked", target: tag, overloads: ovs.length });
    return true;
  } catch (e) {
    send({ ev: "hook_err", target: tag, m: String(e).slice(0, 150) });
    return false;
  }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  // --- Play Billing: product ids and offer tokens -------------------------
  tryHook("com.android.billingclient.api.QueryProductDetailsParams$Product$Builder",
    "setProductId", "QueryProductDetails.Params.Product.setProductId",
    function (a) { emit("sku", "QueryProductDetails", a[0]); });

  tryHook("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder",
    "setOfferToken", "BillingFlowParams.setOfferToken",
    function (a) { emit("token", "BillingFlowParams", a[0]); });

  tryHook("com.android.billingclient.api.BillingFlowParams$SubscriptionUpdateParams$Builder",
    "setOldPurchaseToken", "BillingFlowParams.setOldPurchaseToken",
    function (a) { emit("oldtok", "BillingFlowParams", a[0]); });

  // --- RevenueCat: offerings carry every package, not just rendered ones ---
  tryHook("com.revenuecat.purchases.models.StoreProduct", "getIdentifier",
    "StoreProduct.getIdentifier",
    function (a) { });

  var rcClasses = [
    "com.revenuecat.purchases.Package",
    "com.revenuecat.purchases.Offering",
    "com.revenuecat.purchases.Offerings",
    "com.revenuecat.purchases.models.StoreProduct"
  ];
  for (var i = 0; i < rcClasses.length; i++) {
    try {
      var K = Java.use(rcClasses[i]);
      send({ ev: "class_ok", target: rcClasses[i] });
    } catch (e) {
      send({ ev: "class_missing", target: rcClasses[i] });
    }
  }

  // Dump offerings whenever RevenueCat hands them back.
  try {
    var Purchases = Java.use("com.revenuecat.purchases.Purchases");
    var getOfferings = null;
    try { getOfferings = Purchases.getOfferings; } catch (e) { }
    if (getOfferings) {
      var ovs = getOfferings.overloads;
      for (var j = 0; j < ovs.length; j++) {
        (function (ov) {
          ov.implementation = function () {
            var cb = arguments[arguments.length - 1];
            try {
              var proxy = Java.registerClass({
                name: "gp.CB" + Date.now() + "_" + j,
                interfaces: [Java.use("com.revenuecat.purchases.interfaces.ReceiveOfferingsCallback")],
                methods: {
                  onReceived: function (offerings) { dumpOfferings(offerings); },
                  onError: function (e) { send({ ev: "rc_err", m: String(e) }); }
                }
              });
              var args = Array.prototype.slice.call(arguments);
              args[args.length - 1] = proxy.$new();
              return ov.call.apply(ov, [this].concat(args));
            } catch (e) {
              send({ ev: "rc_hook_err", m: String(e).slice(0, 150) });
              return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
            }
          };
        })(ovs[j]);
      }
      send({ ev: "hooked", target: "Purchases.getOfferings", overloads: ovs.length });
    }
  } catch (e) {
    send({ ev: "hook_err", target: "Purchases", m: String(e).slice(0, 150) });
  }

  function dumpOfferings(offerings) {
    try {
      var it = offerings.getAll().values().iterator();
      while (it.hasNext()) {
        var off = it.next();
        emit("offering", "RevenueCat", off.getIdentifier());
        var pkgs = off.getAvailablePackages();
        for (var k = 0; k < pkgs.size(); k++) {
          var pkg = pkgs.get(k);
          emit("package", "RevenueCat/" + off.getIdentifier(), pkg.getIdentifier());
          try {
            var sp = pkg.getProduct();
            var pid = String(sp.getId());
            emit("sku", "RevenueCat/" + pkg.getIdentifier(), pid,
                 String(sp.getPrice().getFormattedPrice ? sp.getPrice().getFormattedPrice() : ""));
          } catch (e) { }
        }
      }
    } catch (e) {
      send({ ev: "dump_err", m: String(e).slice(0, 160) });
    }
  }

  send({ ev: "armed" });
});
