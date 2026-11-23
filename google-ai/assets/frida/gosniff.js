/* gosniff.js — capture the SKU/offer token at Google One's own billing sheet.
 *
 * Why here: the purchase sheet is com.google.android.apps.subscriptions.red.sdk
 * .GoogleOneSdkActivity — an in-app overlay, NOT Play's SheetUiBuilderHostActivity
 * (verified 2026-11-23: tapping Upgrade moved mCurrentFocus to GoogleOneSdkActivity
 * while Play's sheet hooks stayed silent). The app has no BillingClient classes on
 * its classpath, so the payload reaches the sheet as Intent/Bundle/JSON data.
 *
 * Also taps the classloader: whatever billing entry class this build uses (it is
 * obfuscated and moves between releases) gets reported the moment it is loaded.
 *
 * Read-only: logs, never purchases.
 */
var RE_SKU = /^g1\.[A-Za-z0-9_.]{1,48}$/;
var RE_TOKEN = /^AYrTWi[A-Za-z0-9+/=]{20,}$/;
var RE_CLEAN = /^[A-Za-z0-9_.:+\/=~-]{2,200}$/;
var emitted = {};

function emit(kind, src, key, value) {
  var sig = kind + "|" + src + "|" + key + "|" + value;
  if (emitted[sig]) return;
  emitted[sig] = 1;
  send({ ev: kind, src: src, key: key, value: value });
}

function keyStr(k) {
  if (k === null || k === undefined) return null;
  var s;
  try { s = String(k); } catch (e) { return null; }
  if (!s || s.length > 120) return null;
  if (s.indexOf("<instance") === 0) return null;
  return s;
}

function check(src, key, val) {
  if (val === null || val === undefined) return;
  var s;
  try { s = String(val); } catch (e) { return; }
  if (!s || s.length > 4000) return;
  var k = keyStr(key);
  if (RE_SKU.test(s)) { emit("sku", src, k, s); return; }
  if (RE_TOKEN.test(s)) { emit("token", src, k, s); return; }
  if (k && /product|sku|offer|token|subs|plan|base64/i.test(k) && RE_CLEAN.test(s)) {
    emit("kv", src, k, s);
  }
}

function dumpBundle(src, b) {
  if (!b) return;
  try {
    var it = b.keySet().iterator();
    while (it.hasNext()) {
      var k = String(it.next());
      var v = null;
      try { v = b.get(k); } catch (e) { continue; }
      if (v === null) continue;
      if (v.getClass().getName() === "android.os.Bundle") { dumpBundle(src + "/" + k, v); continue; }
      check(src, k, v);
    }
  } catch (e) { }
}

function dumpIntent(src, intent) {
  if (!intent) return;
  try { check(src, "data", intent.getDataString()); } catch (e) { }
  try { check(src, "action", intent.getAction()); } catch (e) { }
  try { dumpBundle(src + ".extras", intent.getExtras()); } catch (e) { }
}

function hookOverloads(clazzName, method, tag, keyIsFirst) {
  try {
    var C = Java.use(clazzName);
    var ovs = C[method].overloads, n = 0;
    for (var i = 0; i < ovs.length; i++) {
      (function (ov) {
        var argc = ov.argumentTypes.length;
        if (argc < 2) return;
        ov.implementation = function () {
          try {
            var a = arguments;
            check(tag + "(" + argc + ")", keyIsFirst ? a[0] : a[argc - 1],
                  keyIsFirst ? a[1] : a[argc - 2]);
          } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
        n++;
      })(ovs[i]);
    }
    send({ ev: "hooked", target: clazzName + "." + method, overloads: n });
  } catch (e) {
    send({ ev: "hook_err", target: clazzName + "." + method, m: String(e).slice(0, 140) });
  }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  hookOverloads("android.content.Intent", "putExtra", "Intent.putExtra", true);
  hookOverloads("android.os.Bundle", "putString", "Bundle.putString", true);
  hookOverloads("android.os.Bundle", "putCharSequence", "Bundle.putCharSequence", true);
  hookOverloads("org.json.JSONObject", "put", "JSONObject.put", true);

  // The sheet itself. Whatever Google One hands its billing overlay lands here.
  try {
    var Sdk = Java.use("com.google.android.apps.subscriptions.red.sdk.GoogleOneSdkActivity");
    Sdk.onCreate.overload("android.os.Bundle").implementation = function (b) {
      try {
        send({ ev: "sheet_open", cls: String(this.getClass().getName()) });
        dumpIntent("GoogleOneSdkActivity", this.getIntent());
      } catch (e) { send({ ev: "hook_err", target: "sheet_dump", m: String(e).slice(0, 140) }); }
      return this.onCreate(b);
    };
    send({ ev: "hooked", target: "GoogleOneSdkActivity.onCreate" });
  } catch (e) {
    send({ ev: "hook_err", target: "GoogleOneSdkActivity", m: String(e).slice(0, 140) });
  }

  // Classloader tap: report billing-ish classes as the app loads them.
  try {
    var BDCL = Java.use("dalvik.system.BaseDexClassLoader");
    BDCL.findClass.implementation = function (name) {
      if (name && /billing|InAppBilling|SkuDetails|ProductDetails|BuyIntent/i.test(name)) {
        emit("cls_load", "findClass", "", String(name));
      }
      return BDCL.findClass.call(this, name);
    };
    send({ ev: "hooked", target: "BaseDexClassLoader.findClass" });
  } catch (e) {
    send({ ev: "hook_err", target: "BaseDexClassLoader", m: String(e).slice(0, 140) });
  }

  send({ ev: "armed" });
});
