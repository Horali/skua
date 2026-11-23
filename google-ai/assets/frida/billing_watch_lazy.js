/* billing_watch.js — log what an app itself asks Play for, even if the app loads
 * its billing classes lazily (after attach).
 *
 * The naive version hooks com.android.billingclient.* at attach time. Apps that
 * fetch product details on first paywall open load those classes later, so the
 * hooks resolve to ClassNotFound and capture nothing — exactly what happened with
 * Duolingo, Perplexity and Spotify.
 *
 * This version watches class loading instead: every ClassLoader.loadClass /
 * findClass call whose name starts with com.android.billingclient triggers
 * installation of the real hooks, once, at the moment the class becomes visible.
 *
 * Read-only: logs only, never calls launchBillingFlow.
 */
var seen = {};
var wiped = {};

function emit(kind, value, src) {
  var sig = kind + "|" + value;
  if (seen[sig]) return;
  seen[sig] = 1;
  send({ ev: kind, value: String(value), src: src });
}

/* Hooks for one loaded billing class. Idempotent. */
function instrumentClass(name) {
  if (wiped[name]) return;
  wiped[name] = 1;

  if (name === "com.android.billingclient.api.QueryProductDetailsParams$Product$Builder") {
    try {
      var C = Java.use(name);
      C.setProductId.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try { emit("sku", arguments[0], "query"); } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      });
      send({ ev: "instrumented", target: name });
    } catch (e) { send({ ev: "inst_err", target: name, m: String(e).slice(0, 120) }); }
  }

  if (name === "com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder") {
    try {
      var B = Java.use(name);
      B.setOfferToken.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try { emit("token", arguments[0], "flow"); } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      });
      B.setProductDetails.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try { emit("sku", arguments[0].getProductId(), "flow"); } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      });
      send({ ev: "instrumented", target: name });
    } catch (e) { send({ ev: "inst_err", target: name, m: String(e).slice(0, 120) }); }
  }
}

function watchLoaders() {
  var targets = ["java.lang.ClassLoader", "dalvik.system.BaseDexClassLoader",
                 "dalvik.system.DexClassLoader", "dalvik.system.PathClassLoader"];
  var installed = 0;
  for (var i = 0; i < targets.length; i++) {
    try {
      var K = Java.use(targets[i]);
      var ovs = K.loadClass.overloads;
      for (var j = 0; j < ovs.length; j++) {
        (function (ov) {
          if (ov.argumentTypes.length !== 1) return;
          if (String(ov.argumentTypes[0].className) !== "java.lang.String") return;
          ov.implementation = function (nm) {
            var out = ov.call(this, nm);
            try {
              if (typeof nm === "string" && nm.indexOf("com.android.billingclient.") === 0) {
                setTimeout(function () { instrumentClass(nm); }, 0);
                // Also instrument the sibling classes that carry the payload.
                setTimeout(function () {
                  instrumentClass("com.android.billingclient.api.QueryProductDetailsParams$Product$Builder");
                  instrumentClass("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder");
                }, 5);
              }
            } catch (e) { }
            return out;
          };
          installed++;
        })(ovs[j]);
      }
    } catch (e) {
      send({ ev: "loader_err", target: targets[i], m: String(e).slice(0, 100) });
    }
  }
  send({ ev: "loaders_watched", targets: installed });
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });
  // Best effort for apps that already loaded the classes.
  instrumentClass("com.android.billingclient.api.QueryProductDetailsParams$Product$Builder");
  instrumentClass("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams$Builder");
  watchLoaders();
  send({ ev: "armed" });
});
