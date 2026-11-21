/* BarksBuds "waking up" service worker.
 *
 * Why: on Render's free plan the server sleeps after ~15 minutes without visits and takes ~25-50 s to wake.
 * While it sleeps, nothing on our side can answer, so a first-time visitor just sees a blank, loading tab.
 * What this does: for visitors who have been here before (so this worker is installed), a page navigation that
 * takes longer than WAIT_MS shows a cached, friendly "waking up" page. That page polls /healthz and reloads
 * the same URL as soon as the server answers. Everything else (assets, API calls, POSTs, sign-in links) is untouched,
 * and no page content is ever cached.
 * Limits: it can't help someone's very first visit, and it only works over HTTPS (or localhost).
 * To remove it: replace this file with one that calls self.registration.unregister(), and drop the register snippet.
 */
const CACHE = "bb-wake-v1";
const WAKING = "/waking.html";
const PRECACHE = [WAKING, "/img/jack-run-144.webp"];
const WAIT_MS = 6000;
const SKIP = /^\/(auth|admin|unsubscribe|api|healthz|sw\.js)/;

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("bb-wake-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (req.mode !== "navigate" || req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || SKIP.test(url.pathname)) return;
  ev.respondWith((async () => {
    const net = fetch(req);
    let timer;
    const slow = new Promise((res) => { timer = setTimeout(() => res("slow"), WAIT_MS); });
    try {
      const r = await Promise.race([net, slow]);
      clearTimeout(timer);
      if (r !== "slow" && ![502, 503, 504].includes(r.status)) return r;
    } catch (e) {
      clearTimeout(timer);  // network error: fall through to the waking page
    }
    const page = await caches.match(WAKING);
    return page || net;
  })());
});
