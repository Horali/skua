/* billing_multiloader.js — capture an app's Play product ids regardless of which
 * ClassLoader owns the billing classes.
 *
 * Why this exists: billing_watch_lazy.js instruments the builders through the app's
 * default loader. On Duolingo that installs cleanly yet never fires, while a Play
 * sheet still opens — the signature of the app calling a *different copy* of the
 * classes, loaded by a second ClassLoader (split/dynamic-feature dex).
 *
 * Strategy:
 *   1. walk Java.enumerateClassLoaders(), try the billing builders in each loader,
 *      instrument the ones that resolve
 *   2. re-scan every 2s so loaders created later are covered
 *   3. also hook loadClass for early detection
 *
 * Read-only: logs only, never calls launchBillingFlow.
 */
var seen = {};
var hooked = {};      // loaderKey + "|" + className
var defaultLoader = null;

function emit(kind, value, src) {
  var sig = kind + "|" + value;
  if (seen[sig]) return;
  seen[sig] = 1;
  send({ ev: kind, value: String(value), src: src });
}

function loaderKey(ld) {
  try { return String(ld); } catch (e) { return "?"; }
}

var QUERY = "com.android.billingclient.api.QueryProductDetailsParams$Product$Builder";
var FLOW = "com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder";

function hookQuery(C) {
  C.setProductId.overloads.forEach(function (ov) {
    ov.implementation = function () {
      try { emit("sku", arguments[0], "query"); } catch (e) { }
      return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
    };
  });
}

function hookFlow(C) {
  C.setOfferToken.overloads.forEach(function (ov) {
    ov.implementation = function () {
      try { emit("token", arguments[0], "flow"); } catch (e) { }
      return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
    };
  });
  C.setProductDetails.overloads.forEach(function (ov) {
    ov.implementation = function () {
      try { emit("sku", arguments[0].getProductId(), "flow"); } catch (e) { }
      return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
    };
  });
}

function instrumentLoader(ld) {
  var key = loaderKey(ld);
  try { Java.classFactory.loader = ld; } catch (e) { return; }

  if (!hooked[key + "|" + QUERY]) {
    try { hookQuery(Java.use(QUERY)); hooked[key + "|" + QUERY] = 1;
          send({ ev: "instrumented", target: QUERY, loader: key.slice(0, 60) }); } catch (e) { }
  }
  if (!hooked[key + "|" + FLOW]) {
    try { hookFlow(Java.use(FLOW)); hooked[key + "|" + FLOW] = 1;
          send({ ev: "instrumented", target: FLOW, loader: key.slice(0, 60) }); } catch (e) { }
  }
}

function rescan() {
  try { Java.classFactory.loader = defaultLoader; } catch (e) { }
  try {
    Java.enumerateClassLoaders({
      onMatch: function (ld) { try { instrumentLoader(ld); } catch (e) { } },
      onComplete: function () { }
    });
  } catch (e) {
    send({ ev: "enum_err", m: String(e).slice(0, 120) });
  }
  try { Java.classFactory.loader = defaultLoader; } catch (e) { }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });
  try { defaultLoader = Java.classFactory.loader; } catch (e) { }
  send({ ev: "default_loader", m: String(defaultLoader).slice(0, 80) });

  // Early detection of new loaders.
  try {
    var CL = Java.use("java.lang.ClassLoader");
    CL.loadClass.overloads.forEach(function (ov) {
      if (ov.argumentTypes.length !== 1) return;
      if (String(ov.argumentTypes[0].className) !== "java.lang.String") return;
      var orig = ov.implementation;
      ov.implementation = function (nm) {
        var out = ov.call(this, nm);
        try {
          if (typeof nm === "string" && nm.indexOf("com.android.billingclient.") === 0) {
            instrumentLoader(this);
          }
        } catch (e) { }
        return out;
      };
    });
    send({ ev: "loadclass_watched" });
  } catch (e) {
    send({ ev: "loader_err", m: String(e).slice(0, 120) });
  }

  rescan();
  setInterval(rescan, 2000);
  send({ ev: "armed" });
});
