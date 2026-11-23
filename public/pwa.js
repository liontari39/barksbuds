/* BarksBuds PWA: home-screen prompt + optional Web Push. Skipped inside Capacitor.
 * Dismissed install prompt stays dismissed for 30 days (localStorage). Never nags in standalone. */
(function () {
  if (window.Capacitor) return;
  var STANDALONE = window.matchMedia && window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
  var DISMISS_KEY = "bb-a2hs-dismissed";
  var DISMISS_MS = 30 * 24 * 3600 * 1000;

  function dismissed() {
    try {
      var t = parseInt(localStorage.getItem(DISMISS_KEY) || "0", 10);
      return t && (Date.now() - t) < DISMISS_MS;
    } catch (e) { return false; }
  }
  function dismiss() {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (e) {}
    var el = document.getElementById("a2hs");
    if (el) el.remove();
  }
  function isIos() {
    var ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }
  function banner(html) {
    if (document.getElementById("a2hs")) return;
    var el = document.createElement("div");
    el.id = "a2hs";
    el.className = "a2hs";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Add BarksBuds to your home screen");
    el.innerHTML = html;
    document.body.appendChild(el);
    var x = el.querySelector("[data-dismiss]");
    if (x) x.addEventListener("click", dismiss);
  }

  if (!STANDALONE && !dismissed()) {
    var deferred = null;
    window.addEventListener("beforeinstallprompt", function (ev) {
      ev.preventDefault();
      deferred = ev;
      banner(
        '<p><b>Add BarksBuds to your home screen</b> for quicker access to runs and meetups.</p>' +
        '<p class="a2hs-actions"><button type="button" class="btn btn-sm" data-install>Add</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-dismiss>Not now</button></p>'
      );
      var add = document.querySelector("#a2hs [data-install]");
      if (add) add.addEventListener("click", function () {
        deferred.prompt();
        deferred.userChoice.finally(dismiss);
      });
    });
    // iOS has no beforeinstallprompt; show Share-sheet instructions once.
    if (isIos() && !STANDALONE) {
      banner(
        '<p><b>Add BarksBuds to your home screen.</b> Tap the Share button, then <b>Add to Home Screen</b>.</p>' +
        '<p class="a2hs-actions"><button type="button" class="btn btn-ghost btn-sm" data-dismiss>Got it</button></p>'
      );
    }
  }

  // Web Push (opt-in). Server injects window.BB_VAPID when keys are configured and the user is signed in.
  function b64ToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
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
  window.bbPush = {
    available: function () {
      return !!(window.BB_VAPID && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window);
    },
    status: function () {
      if (!this.available()) return Promise.resolve("off");
      return navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.getSubscription();
      }).then(function (sub) { return sub ? "on" : "off"; });
    },
    subscribe: function (kinds) {
      if (!this.available()) return Promise.reject(new Error("push unavailable"));
      return Notification.requestPermission().then(function (perm) {
        if (perm !== "granted") throw new Error("permission");
        return navigator.serviceWorker.ready;
      }).then(function (reg) {
        return reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: b64ToBytes(window.BB_VAPID)
        });
      }).then(function (sub) {
        return post("/me/push/subscribe", { subscription: sub.toJSON(), kinds: kinds || ["meetups"] });
      }).then(function (r) {
        if (!r.ok) throw new Error("subscribe failed");
        return r.json();
      });
    },
    unsubscribe: function () {
      return navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.getSubscription();
      }).then(function (sub) {
        var endpoint = sub && sub.endpoint;
        return (sub ? sub.unsubscribe() : Promise.resolve()).then(function () {
          return post("/me/push/unsubscribe", { endpoint: endpoint || "" });
        });
      });
    }
  };

  // Wire the account-page buttons if present.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("[data-push]");
    if (!btn || !window.bbPush) return;
    ev.preventDefault();
    var action = btn.getAttribute("data-push");
    var kinds = (btn.getAttribute("data-kinds") || "meetups").split(",");
    btn.disabled = true;
    var p = action === "off" ? window.bbPush.unsubscribe() : window.bbPush.subscribe(kinds);
    p.then(function () { location.reload(); })
     .catch(function () { btn.disabled = false; alert("Couldn't update notifications. You can try again from this page."); });
  });
})();
