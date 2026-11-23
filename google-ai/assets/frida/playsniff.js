/* playsniff.js — capture the product ID + offer token Play actually carries.
 *
 * Injected into com.android.vending (Play Store), NOT Google One. Reason: the
 * purchase sheet runs in Play's process
 * (com.google.android.finsky.billing.acquire.SheetUiBuilderHostActivity), and the
 * BillingClient SDK classes are absent from that process — the SKU arrives as
 * Intent/Bundle/JSON payload, so that is where it is visible.
 *
 * Read-only: logs strings, runs in setImmediate. Never starts a purchase.
 */
var RE_SKU = /^g1\.[A-Za-z0-9_.]{1,48}$/;
var RE_TOKEN = /^AYrTWi[A-Za-z0-9+/=]{20,}$/;
var emitted = {};

function emit(kind, src, key, value) {
  var sig = kind + "|" + src + "|" + key + "|" + value;
  if (emitted[sig]) return;
  emitted[sig] = 1;
  send({ ev: kind, src: src, key: key, value: value });
}

function looksBilling(key) {
  return key && /product|sku|offer|token|subs|plan|base64/i.test(key);
}

/* Frida renders un-convertible Java refs as "<instance: ...>". Those carry no
 * key information and were the whole source of the HashMap/JSON noise. */
function keyStr(k) {
  if (k === null || k === undefined) return null;
  var s;
  try { s = String(k); } catch (e) { return null; }
  if (!s || s.length > 120) return null;
  if (s.indexOf("<instance") === 0) return null;
  if (s.indexOf("java.lang.Object@") === 0) return null;
  return s;
}

/* A real id/token is a clean token, not a debug toString(). */
var RE_CLEAN = /^[A-Za-z0-9_.:+\/=~-]{2,200}$/;

/* Classify one key/value pair observed in transit. */
function check(src, key, val) {
  if (val === null || val === undefined) return;
  var s;
  try { s = String(val); } catch (e) { return; }
  if (!s || s.length > 2000) return;

  var k = keyStr(key);

  if (RE_SKU.test(s)) { emit("sku", src, k, s); return; }
  if (RE_TOKEN.test(s)) { emit("token", src, k, s); return; }

  // Any billing-ish key carrying a short clean string is worth recording:
  // that is where a rename to a non-g1.* SKU would show up first.
  if (k && looksBilling(k) && RE_CLEAN.test(s)) {
    emit("kv", src, k, s);
  }
}

function dumpBundleExtras(src, bundle) {
  if (!bundle) return;
  try {
    var keys = bundle.keySet();
    var it = keys.iterator();
    while (it.hasNext()) {
      var k = String(it.next());
      var v = null;
      try { v = bundle.get(k); } catch (e) { continue; }
      if (v === null) continue;
      check(src, k, v);
    }
  } catch (e) { }
}

function dumpIntent(src, intent) {
  if (!intent) return;
  try { check(src + ".data", "data", intent.getDataString()); } catch (e) { }
  try { check(src + ".action", "action", intent.getAction()); } catch (e) { }
  try { dumpBundleExtras(src + ".extras", intent.getExtras()); } catch (e) { }
}

function hookOverloads(clazzName, method, tag, keyIsFirst) {
  try {
    var C = Java.use(clazzName);
    var ovs = C[method].overloads;
    var n = 0;
    for (var i = 0; i < ovs.length; i++) {
      (function (ov) {
        var argc = ov.argumentTypes.length;
        if (argc < 2) return;
        var saved = ov.implementation;
        ov.implementation = function () {
          try {
            var a = arguments;
            var key = null, val = null;
            if (keyIsFirst) { key = a[0]; val = a[1]; }
            else { key = a[argc - 1]; val = a[argc - 2]; }
            if (val !== null && val !== undefined) check(tag + "(" + argc + ")", key, val);
          } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
        n++;
      })(ovs[i]);
    }
    send({ ev: "hooked", target: clazzName + "." + method, overloads: n });
  } catch (e) {
    send({ ev: "hook_err", target: clazzName + "." + method, m: String(e).slice(0, 160) });
  }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  hookOverloads("android.content.Intent", "putExtra", "Intent.putExtra", true);
  hookOverloads("android.os.Bundle", "putString", "Bundle.putString", true);
  hookOverloads("android.os.Bundle", "putCharSequence", "Bundle.putCharSequence", true);
  hookOverloads("android.os.BaseBundle", "putString", "BaseBundle.putString", true);
  hookOverloads("org.json.JSONObject", "put", "JSONObject.put", true);
  hookOverloads("java.util.HashMap", "put", "HashMap.put", true);

  // The sheet host activity: whatever Play was handed, it is on the Intent here.
  try {
    var Sheet = Java.use("com.google.android.finsky.billing.acquire.SheetUiBuilderHostActivity");
    Sheet.onCreate.overload("android.os.Bundle").implementation = function (b) {
      try {
        send({ ev: "sheet_open", cls: "SheetUiBuilderHostActivity" });
        dumpIntent("Sheet.onCreate", this.getIntent());
      } catch (e) { send({ ev: "hook_err", target: "sheet_dump", m: String(e).slice(0, 160) }); }
      return this.onCreate(b);
    };
    send({ ev: "hooked", target: "SheetUiBuilderHostActivity.onCreate" });
  } catch (e) {
    send({ ev: "hook_err", target: "SheetUiBuilderHostActivity", m: String(e).slice(0, 160) });
  }

  // Anything currently on screen already (the sheet may be open at attach time).
  try {
    var AT = Java.use("android.app.ActivityThread");
    var at = AT.currentActivityThread();
    var acts = at.mActivities.value;
    var it = acts.keySet().iterator();
    while (it.hasNext()) {
      var token = it.next();
      var rec = acts.get(token);
      try {
        var act = rec.activity.value;
        if (act !== null) {
          dumpIntent("live:" + act.getClass().getName(), act.getIntent());
        }
      } catch (e) { }
    }
  } catch (e) {
    send({ ev: "hook_err", target: "activity_scan", m: String(e).slice(0, 160) });
  }

  // Which billing entry points actually exist in this build? Obfuscation moves
  // them around between Play releases, so discover instead of hardcoding.
  // Deferred: enumerating Play's loaded classes is slow enough to stall
  // script.load() if it runs inline (observed as frida.TransportError timeout).
  setTimeout(function () {
    try {
      var names = Java.enumerateLoadedClassesSync();
      var pick = [];
      for (var i = 0; i < names.length && pick.length < 250; i++) {
        var n = names[i];
        if (/billing|Iab|Purchase|ProductDetails|Sku/i.test(n) &&
            n.indexOf("com.google.android.finsky") === 0) {
          pick.push(n);
        }
      }
      send({ ev: "classes", count: pick.length, names: pick });
    } catch (e) {
      send({ ev: "hook_err", target: "class_probe", m: String(e).slice(0, 160) });
    }
  }, 1500);

  send({ ev: "armed" });
});
