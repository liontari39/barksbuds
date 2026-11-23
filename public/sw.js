/* BarksBuds service worker (PWA + "waking up" fallback).
 *
 * Navigations: try the network first. If the server is waking (Render cold start, 6s) or is down,
 * show the cached waking-up or offline page. Never cache authenticated HTML or API responses.
 * Version CACHE when this file changes so clients pick up a new worker.
 */
const CACHE = "bb-pwa-v1";
const WAKING = "/waking.html";
const OFFLINE = "/offline.html";
const PRECACHE = [WAKING, OFFLINE, "/img/jack-run-144.webp", "/img/icon-96.webp?v=jack5"];
const WAIT_MS = 6000;
const SKIP = /^\/(auth|admin|unsubscribe|api|healthz|sw\.js|me(?:$|\/)|\.ics$)/;

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE && /^(bb-wake-|bb-pwa-)/.test(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method !== "GET") return;

  // Static precache hit for offline assets only — never HTML app pages.
  if (req.mode !== "navigate") {
    if (PRECACHE.includes(url.pathname) || PRECACHE.includes(url.pathname + url.search)) {
      ev.respondWith(caches.match(req).then((c) => c || fetch(req)));
    }
    return;
  }
  if (SKIP.test(url.pathname) || /\.ics$/.test(url.pathname)) return;
  ev.respondWith((async () => {
    const net = fetch(req, { cache: "no-store" });
    let timer;
    const slow = new Promise((res) => { timer = setTimeout(() => res("slow"), WAIT_MS); });
    try {
      const r = await Promise.race([net, slow]);
      clearTimeout(timer);
      if (r !== "slow" && r && ![502, 503, 504].includes(r.status)) return r;
    } catch (e) {
      clearTimeout(timer);
    }
    // Prefer the waking-up page when the server may be cold-starting; otherwise the offline page.
    const waking = await caches.match(WAKING);
    try {
      const late = await Promise.race([net, new Promise((res) => setTimeout(() => res(null), 400))]);
      if (late && late !== "slow" && late.ok) return late;
    } catch (e) {}
    if (waking) return waking;
    return (await caches.match(OFFLINE)) || net;
  })());
});

self.addEventListener("push", (ev) => {
  let data = {};
  try { data = ev.data ? ev.data.json() : {}; } catch (e) { data = { body: ev.data && ev.data.text() }; }
  const title = data.title || "BarksBuds";
  const opts = {
    body: data.body || "",
    icon: data.icon || "/img/icon-192.png?v=jack5",
    badge: "/img/icon-192.png?v=jack5",
    data: { url: data.url || "/" },
  };
  ev.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", (ev) => {
  ev.notification.close();
  const url = (ev.notification.data && ev.notification.data.url) || "/";
  ev.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) {
      if (c.url && "focus" in c) { c.navigate(url); return c.focus(); }
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
