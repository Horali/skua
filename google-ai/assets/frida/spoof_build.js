/* spoof_build.js — present a different device identity inside one app process.
 *
 * Tests whether a partner/device entitlement check reads device identity from the
 * Java side (android.os.Build + SystemProperties). It overrides both, so any check
 * that samples the model at runtime sees the spoofed device.
 *
 * Usage: attach to the app, load, then drive its offers UI.
 */
var TARGET = {
  "ro.product.model": "Pixel 9 Pro",
  "ro.product.brand": "google",
  "ro.product.manufacturer": "Google",
  "ro.product.device": "caiman",
  "ro.product.name": "caiman",
  "ro.product.board": "caiman",
  "ro.build.product": "caiman",
  "ro.build.fingerprint": "google/caiman/caiman:15/AP4A.250105.002/12345678:user/release-keys"
};

Java.perform(function () {
  send({ ev: "ready", pid: Process.id });

  // 1. Static Build fields
  try {
    var Build = Java.use("android.os.Build");
    var map = {
      MODEL: "Pixel 9 Pro", BRAND: "google", MANUFACTURER: "Google",
      DEVICE: "caiman", PRODUCT: "caiman", BOARD: "caiman"
    };
    for (var k in map) {
      try { Build[k].value = map[k]; send({ ev: "set", field: k, v: map[k] }); } catch (e) { }
    }
    try {
      Build.FINGERPRINT.value = TARGET["ro.build.fingerprint"];
      send({ ev: "set", field: "FINGERPRINT", v: TARGET["ro.build.fingerprint"] });
    } catch (e) { }
  } catch (e) {
    send({ ev: "err", m: "Build: " + String(e).slice(0, 120) });
  }

  // 2. SystemProperties lookups
  try {
    var SP = Java.use("android.os.SystemProperties");
    SP.get.overload("java.lang.String").implementation = function (key) {
      if (TARGET[key] !== undefined) {
        send({ ev: "spoofed_get", key: key });
        return TARGET[key];
      }
      return SP.get.call(SP, key);
    };
    if (SP.get.overloads.some(function (o) { return o.argumentTypes.length === 2; })) {
      SP.get.overload("java.lang.String", "java.lang.String").implementation = function (key, def) {
        if (TARGET[key] !== undefined) return TARGET[key];
        return SP.get.call(SP, key, def);
      };
    }
    send({ ev: "hooks", target: "SystemProperties.get" });
  } catch (e) {
    send({ ev: "err", m: "SystemProperties: " + String(e).slice(0, 120) });
  }

  send({ ev: "armed" });
});
