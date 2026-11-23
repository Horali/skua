/* sheetprobe.js — capture the purchase sheet at the moment Play creates it.
 *
 * Attach BEFORE the sheet exists (Play stays running the whole time), hook the
 * sheet activity's onCreate, then dump:
 *   - the Intent extras Play was handed
 *   - the activity's own fields, depth-limited (an unbounded walk over Play's
 *     object graph wedges the script thread and the attach times out)
 *
 * Read-only: logs only, never purchases.
 */
var RE_SKU = /^g1\.[A-Za-z0-9_.]{1,48}$/;
var RE_TOKEN = /^AYrTWi[A-Za-z0-9+\/=]{20,}$/;
var RE_CLEAN = /^[A-Za-z0-9_.:+\/=~-]{2,300}$/;
var seen = {};
var visited = 0;
var MAX_OBJECTS = 150;
var MAX_FIELDS = 50;
var MAX_DEPTH = 2;

function note(src, value) {
  var sig = src + "|" + value;
  if (seen[sig]) return;
  seen[sig] = 1;
  send({ ev: "hit", src: src, value: value });
}

function keyOk(k) {
  var s;
  try { s = String(k); } catch (e) { return null; }
  if (!s || s.length > 120 || s.indexOf("<instance") === 0) return null;
  return s;
}

function interesting(src, key, v) {
  if (v === null || v === undefined) return;
  var s;
  try { s = String(v); } catch (e) { return; }
  if (!s || s.length > 800) return;
  var k = keyOk(key);
  if (RE_SKU.test(s)) { note(src + "." + k, s); return; }
  if (RE_TOKEN.test(s)) { note(src + "." + k, s); return; }
  if (k && /product|sku|offer|token|base64/i.test(k) && RE_CLEAN.test(s)) {
    note(src + "." + k, s);
  }
}

function clsName(o) {
  try { return String(o.getClass().getName()); } catch (e) { return ""; }
}

function walk(obj, depth, path) {
  if (!obj || visited >= MAX_OBJECTS || depth < 0) return;
  var cname = clsName(obj);
  if (!cname) return;
  if (!/^(com\.google\.android\.finsky|com\.google\.android\.apps|com\.android\.billingclient)/.test(cname)) return;
  visited++;
  var cls = null;
  try { cls = obj.getClass(); } catch (e) { return; }
  for (var level = 0; level < 4 && cls !== null; level++) {
    var fs = null;
    try { fs = cls.getDeclaredFields(); } catch (e) { break; }
    for (var i = 0; i < fs.length && i < MAX_FIELDS; i++) {
      var f = fs[i];
      var v = null;
      try { f.setAccessible(true); v = f.get(obj); } catch (e) { continue; }
      if (v === null) continue;
      interesting(path, String(f.getName()), v);
      if (depth > 0 && visited < MAX_OBJECTS) {
        var t = "";
        try { t = String(f.getType().getName()); } catch (e) { continue; }
        if (/^(com\.google\.android\.finsky|com\.google\.android\.apps|java\.lang\.String\[\])/.test(t)) {
          try { walk(v, depth - 1, path + "." + String(f.getName())); } catch (e) { }
        }
      }
    }
    try { cls = cls.getSuperclass(); } catch (e) { break; }
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
      if (clsName(v) === "android.os.Bundle") { dumpBundle(src + "/" + k, v); continue; }
      interesting(src, k, v);
    }
  } catch (e) { }
}

function inspectActivity(act, tag) {
  try { send({ ev: "sheet_open", cls: clsName(act) }); } catch (e) { }
  try { dumpBundle(tag + ".intent", act.getIntent().getExtras()); } catch (e) { }
  try {
    var d = act.getIntent().getDataString();
    if (d) interesting(tag + ".uri", "data", d);
  } catch (e) { }
  try { walk(act, MAX_DEPTH, tag); } catch (e) { send({ ev: "walk_err", m: String(e).slice(0, 120) }); }
  send({ ev: "phase", m: tag + " visited=" + visited });
}

function hookCreate(clazzName, tag) {
  try {
    var C = Java.use(clazzName);
    C.onCreate.overload("android.os.Bundle").implementation = function (b) {
      try { inspectActivity(this, tag); } catch (e) { }
      return this.onCreate(b);
    };
    send({ ev: "hooked", target: clazzName + ".onCreate" });
    return true;
  } catch (e) {
    send({ ev: "hook_err", target: clazzName, m: String(e).slice(0, 140) });
    return false;
  }
}

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  hookCreate("com.google.android.finsky.billing.acquire.SheetUiBuilderHostActivity", "SheetUiBuilderHost");
  hookCreate("com.google.android.finsky.billing.lightpurchase.PurchaseActivity", "PurchaseActivity");
  hookCreate("com.google.android.finsky.billing.lightpurchase.IabV3Activity", "IabV3Activity");

  // Backup: catch the payload when Play builds the intent.
  try {
    var Intent = Java.use("android.content.Intent");
    var ovs = Intent.putExtra.overloads;
    for (var i = 0; i < ovs.length; i++) {
      (function (ov) {
        if (ov.argumentTypes.length < 2) return;
        ov.implementation = function () {
          try {
            var a = arguments;
            if (a.length >= 2) interesting("Intent.putExtra", a[0], a[1]);
          } catch (e) { }
          return ov.call.apply(ov, [this].concat(Array.prototype.slice.call(arguments)));
        };
      })(ovs[i]);
    }
    send({ ev: "hooked", target: "Intent.putExtra", overloads: ovs.length });
  } catch (e) {
    send({ ev: "hook_err", target: "Intent.putExtra", m: String(e).slice(0, 120) });
  }

  send({ ev: "armed" });
});
