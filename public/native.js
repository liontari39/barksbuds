/* BarksBuds native bridges. No-ops on the website unless Capacitor is present,
 * so existing browser behavior stays the same. */
(function () {
  var C = window.Capacitor;
  if (!C) return;
  var Plugins = C.Plugins || {};
  var Geo = Plugins.Geolocation;
  var Camera = Plugins.Camera;
  var Push = Plugins.PushNotifications;
  var App = Plugins.App;

  function csrf() {
    if (window.BB_CSRF) return window.BB_CSRF;
    var el = document.querySelector('input[name="csrf"]');
    return el ? el.value : "";
  }
  function post(url, body) {
    body = body || {};
    body.csrf = csrf();
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }
  function isIos() {
    var p = (C.getPlatform && C.getPlatform()) || "";
    if (p === "ios") return true;
    var ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua);
  }

  // ----- deep links (magic-link sign-in and shared URLs)
  if (App && App.addListener) {
    App.addListener("appUrlOpen", function (ev) {
      var raw = (ev && ev.url) || "";
      if (!raw) return;
      try {
        var abs = raw.replace(/^barksbuds:\/\//i, "https://barksbuds.app/");
        var u = new URL(abs);
        if (!/barksbuds\.app$/i.test(u.hostname) && u.protocol !== "https:") return;
        var next = u.pathname + u.search + u.hash;
        if (next && next !== (location.pathname + location.search + location.hash)) {
          location.assign(next);
        }
      } catch (e) {}
    });
  }

  // ----- geolocation: only after the owner taps, with a reason first
  var locBusy = false;
  function locateDialog(onYes, onNo) {
    if (document.getElementById("bb-loc")) return;
    var el = document.createElement("div");
    el.id = "bb-loc";
    el.className = "a2hs";
    el.style.zIndex = "10000";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Use your location");
    el.innerHTML = '<p><b>Use your location?</b> BarksBuds uses it only when you tap to sort dog runs near you, or to drop a pin when suggesting a run. We don\'t save it.</p>' +
      '<p class="a2hs-actions"><button type="button" class="btn btn-sm" data-loc="yes">Allow</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-loc="no">Not now</button></p>';
    if (!document.querySelector("style[data-bb-native]")) {
      var st = document.createElement("style");
      st.setAttribute("data-bb-native", "1");
      st.textContent = ".a2hs{position:fixed;z-index:10000;left:16px;right:16px;bottom:16px;max-width:480px;margin:0 auto;padding:14px 16px;background:#fff;border:1px solid #EADBB9;border-radius:16px;box-shadow:0 10px 30px rgba(42,38,34,.12)}.a2hs p{margin:0 0 10px}.a2hs-actions{display:flex;gap:8px;flex-wrap:wrap;margin:0}.bb-native-photos{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin:8px 0}";
      document.head.appendChild(st);
    }
    document.body.appendChild(el);
    el.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest("[data-loc]");
      if (!btn) return;
      el.remove();
      if (btn.getAttribute("data-loc") === "yes") onYes();
      else onNo();
    });
  }

  window.bbLocate = function (ok, err, opts) {
    opts = opts || { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 };
    function fail(code, message) {
      if (err) err({ code: code || 1, message: message || "Location is off." });
    }
    function request() {
      if (!Geo || !Geo.getCurrentPosition) {
        if (navigator.geolocation) return navigator.geolocation.getCurrentPosition(ok, err, opts);
        return fail(2, "Location is unavailable.");
      }
      var timeout = opts.timeout || 10000;
      Geo.getCurrentPosition({ enableHighAccuracy: !!opts.enableHighAccuracy, timeout: timeout, maximumAge: opts.maximumAge || 0 })
        .then(function (p) {
          var c = (p && p.coords) || p || {};
          ok({ coords: { latitude: c.latitude, longitude: c.longitude, accuracy: c.accuracy } });
        })
        .catch(function () { fail(1, "Couldn't find your location."); });
    }
    if (locBusy) return;
    try {
      if (sessionStorage.getItem("bb-loc-ok") === "1") { request(); return; }
    } catch (e) {}
    locBusy = true;
    locateDialog(function () {
      locBusy = false;
      try { sessionStorage.setItem("bb-loc-ok", "1"); } catch (e) {}
      request();
    }, function () {
      locBusy = false;
      fail(1, "Location is off. Allow location access or search by town.");
    });
  };

  // ----- camera: add buttons next to the dog photo file input
  function dataUrlToFile(dataUrl, name) {
    var parts = (dataUrl || "").split(",");
    var mime = (parts[0].match(/:(.*?);/) || [])[1] || "image/jpeg";
    var bin = atob(parts[1] || "");
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    var ext = mime === "image/png" ? "png" : "jpg";
    return new File([arr], name || ("photo." + ext), { type: mime });
  }
  function addFile(input, file) {
    var dt = new DataTransfer();
    if (input.files) {
      for (var i = 0; i < input.files.length; i++) dt.items.add(input.files[i]);
    }
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.removeAttribute("required");
  }
  function hookPhotos() {
    if (!Camera || !Camera.getPhoto) return;
    var input = document.getElementById("photos");
    if (!input || input.getAttribute("data-bb-native") === "1") return;
    input.setAttribute("data-bb-native", "1");
    var wrap = document.createElement("div");
    wrap.className = "bb-native-photos";
    wrap.innerHTML = '<button type="button" class="btn btn-sm" data-native-photo="camera">Take a photo</button>' +
      '<button type="button" class="btn btn-sm btn-ghost" data-native-photo="library">Choose from library</button>';
    input.parentNode.insertBefore(wrap, input);
    wrap.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest("[data-native-photo]");
      if (!btn) return;
      ev.preventDefault();
      var source = btn.getAttribute("data-native-photo") === "camera" ? "CAMERA" : "PHOTOS";
      Camera.getPhoto({
        quality: 90,
        allowEditing: false,
        resultType: "dataUrl",
        source: source,
        saveToGallery: false,
        promptLabelHeader: "Add a photo of your dog",
        promptLabelCancel: "Cancel",
        promptLabelPhoto: "Choose from library",
        promptLabelPicture: "Take a photo"
      }).then(function (pic) {
        if (!pic || !pic.dataUrl) return;
        addFile(input, dataUrlToFile(pic.dataUrl, "dog-photo.jpg"));
      }).catch(function () {});
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hookPhotos);
  else hookPhotos();

  // ----- native push (alongside Web Push; pwa.js already skipped itself)
  var pushReady = null;
  function ensurePushListeners(kinds) {
    if (pushReady) return pushReady;
    pushReady = new Promise(function (resolve, reject) {
      if (!Push) { reject(new Error("push unavailable")); return; }
      var settled = false;
      Push.addListener("registration", function (tok) {
        if (settled) return;
        settled = true;
        resolve((tok && tok.value) || "");
      });
      Push.addListener("registrationError", function () {
        if (settled) return;
        settled = true;
        reject(new Error("registration"));
      });
      Push.addListener("pushNotificationActionPerformed", function (ev) {
        var data = (ev && ev.notification && ev.notification.data) || {};
        var url = data.url || data.next || "";
        if (url && url.charAt(0) === "/") location.assign(url);
      });
    });
    return pushReady;
  }

  window.bbPush = {
    available: function () { return !!Push; },
    subscribe: function (kinds) {
      if (!Push) return Promise.reject(new Error("push unavailable"));
      kinds = kinds && kinds.length ? kinds : ["meetups", "checkins"];
      return Push.requestPermissions().then(function (perm) {
        var ok = perm && (perm.receive === "granted" || perm.receive === "prompt");
        // iOS returns 'granted' after the system dialog; 'prompt' means we should register first.
        if (perm && perm.receive === "denied") throw new Error("permission");
        return Push.register();
      }).then(function () { return ensurePushListeners(kinds); })
        .then(function (token) {
          if (!token) throw new Error("no token");
          return post("/me/push/device", {
            platform: isIos() ? "ios" : "android",
            token: token,
            kinds: kinds
          });
        })
        .then(function (r) {
          if (!r.ok) throw new Error("subscribe failed");
          return r.json();
        });
    },
    unsubscribe: function () {
      return post("/me/push/device", { action: "off" }).then(function (r) {
        if (!r.ok) throw new Error("unsubscribe failed");
        try { if (Push && Push.removeAllListeners) Push.removeAllListeners(); } catch (e) {}
        return r.json();
      });
    }
  };

  // If the account page has no push toggle (VAPID off) but we are in the app, add one.
  function injectPushPrefs() {
    if (!Push || document.getElementById("push")) return;
    if (location.pathname !== "/me" && location.pathname.indexOf("/me/") !== 0) return;
    var host = document.querySelector(".emailpref") || document.querySelector(".formfoot");
    if (!host) return;
    var box = document.createElement("div");
    box.className = "emailpref";
    box.id = "push";
    box.innerHTML = '<p class="small" style="margin:0 0 8px"><b>Phone notifications:</b> Off. ' +
      'Get a reminder the day before a meetup you RSVPed to, and a note when a dog arrives at a run where you already are. ' +
      'Opt in only \u2014 we never turn this on for you.</p>' +
      '<button class="btn btn-ghost btn-sm" type="button" data-push="on" data-kinds="meetups,checkins">Turn on notifications</button>';
    host.parentNode.insertBefore(box, host.nextSibling);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", injectPushPrefs);
  else injectPushPrefs();

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("[data-push]");
    if (!btn || !window.bbPush) return;
    ev.preventDefault();
    var action = btn.getAttribute("data-push");
    var kinds = (btn.getAttribute("data-kinds") || "meetups,checkins").split(",");
    btn.disabled = true;
    var p = action === "off" ? window.bbPush.unsubscribe() : window.bbPush.subscribe(kinds);
    p.then(function () { location.reload(); })
     .catch(function () { btn.disabled = false; alert("Couldn't update notifications. You can try again from this page."); });
  });
})();
