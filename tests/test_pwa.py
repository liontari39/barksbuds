"""Installable PWA: manifest, icons, service worker, home-screen prompt, optional Web Push.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import json, os, re, sys, unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402
import accounts as A  # noqa: E402
import push  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


class PwaTests(unittest.TestCase):
    def test_manifest_icons_shortcuts_and_start_url(self):
        r = Client().get("/site.webmanifest")
        self.assertEqual(r.status, 200)
        self.assertIn("application/manifest+json", r.headers.get("Content-Type", ""))
        m = json.loads(r.text)
        self.assertEqual(m["name"], "BarksBuds")
        self.assertEqual(m["short_name"], "BarksBuds")
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["theme_color"], "#FBB321")
        self.assertEqual(m["background_color"], "#FFF8EA")
        self.assertTrue(m["start_url"].endswith("src=pwa") or "src=pwa" in m["start_url"])
        purposes = {(i["sizes"], i.get("purpose", "any")): i["src"] for i in m["icons"]}
        self.assertIn(("192x192", "any"), purposes)
        self.assertIn(("512x512", "any"), purposes)
        self.assertIn(("192x192", "maskable"), purposes)
        self.assertIn(("512x512", "maskable"), purposes)
        names = {s["name"] for s in m["shortcuts"]}
        self.assertEqual(names, {"Dog run map", "Meetups", "My dogs"})
        for s in m["shortcuts"]:
            self.assertIn("src=pwa", s["url"])
        for src in purposes.values():
            path = src.split("?")[0]
            self.assertEqual(Client().get(path).status, 200, src)
            self.assertTrue((PUBLIC / path.lstrip("/")).exists(), path)

    def test_pages_have_ios_meta_prompt_script_and_sw(self):
        home = Client().get("/").text
        self.assertIn('rel="manifest" href="/site.webmanifest"', home)
        self.assertIn("apple-mobile-web-app-capable", home)
        self.assertIn("apple-mobile-web-app-title", home)
        self.assertIn("/img/icon-180-touch.png?v=jack5", home)
        self.assertIn("apple-touch-startup-image", home)
        self.assertIn("/img/splash-1170x2532.png?v=jack5", home)
        self.assertIn("/pwa.js?v=1", home)
        self.assertIn("serviceWorker", home)
        pwa = Client().get("/pwa.js?v=1").text
        self.assertIn("beforeinstallprompt", pwa)
        self.assertIn("Add to Home Screen", pwa)
        self.assertIn("data-dismiss", pwa)
        self.assertIn("bb-a2hs-dismissed", pwa)
        self.assertIn("Capacitor", pwa)
        sw = Client().get("/sw.js")
        self.assertEqual(sw.status, 200)
        self.assertIn("no-cache", sw.headers.get("Cache-Control", ""))
        self.assertIn("bb-pwa-v1", sw.text)
        self.assertIn("/waking.html", sw.text)
        self.assertIn("/offline.html", sw.text)
        self.assertIn("|api|", sw.text)
        self.assertIn("push", sw.text)
        self.assertEqual(Client().get("/offline.html").status, 200)
        self.assertEqual(Client().get("/waking.html").status, 200)

    def test_push_is_off_without_vapid_keys(self):
        old = {k: os.environ.get(k) for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT")}
        try:
            for k in list(old):
                os.environ.pop(k, None)
            self.assertFalse(push.enabled())
            c = Client()
            sign_in(c, f"pwa-off-{RUN}@example.com")
            me = c.get("/me").text
            self.assertNotIn("Turn on notifications", me)
            self.assertNotIn("BB_VAPID", me)
            self.assertEqual(c.req("POST", "/me/push/subscribe", "{}", {"Content-Type": "application/json"}).status, 404)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_push_subscribe_unsubscribe_and_no_private_key_leak(self):
        pub, priv = push.generate_vapid_keypair()
        os.environ["VAPID_PUBLIC_KEY"] = pub
        os.environ["VAPID_PRIVATE_KEY"] = priv
        os.environ["VAPID_CONTACT"] = "mailto:hello@barksbuds.app"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT")])
        self.assertTrue(push.enabled())
        c = Client()
        sign_in(c, f"pwa-on-{RUN}@example.com")
        me = c.get("/me").text
        self.assertIn("Turn on notifications", me)
        self.assertIn("BB_VAPID", me)
        self.assertIn(pub, me)
        self.assertNotIn(priv, me)
        self.assertNotIn(priv, Client().get("/").text)
        self.assertNotIn(priv, Client().get("/site.webmanifest").text)
        self.assertNotIn(priv, Client().get("/sw.js").text)
        self.assertNotIn(priv, Client().get("/pwa.js?v=1").text)

        csrf = re.search(r"window.BB_CSRF=\"([0-9a-f]+)\"", me)
        # BB_CSRF may be quoted with JSON
        if not csrf:
            csrf = re.search(r"window.BB_CSRF=(\"?)([0-9a-f]+)\1", me)
            token = csrf.group(2) if csrf else c.csrf()
        else:
            token = csrf.group(1)
        sub = {"endpoint": "https://push.example.com/sub/" + RUN,
               "keys": {"p256dh": "A" * 88, "auth": "B" * 24}}
        body = json.dumps({"csrf": "bad", "subscription": sub, "kinds": ["meetups"]})
        self.assertEqual(c.req("POST", "/me/push/subscribe", body, {"Content-Type": "application/json"}).status, 403)
        uid = A.one("SELECT id FROM users WHERE email=:e", e=f"pwa-on-{RUN}@example.com")[0]
        self.assertFalse(push.user_flags(uid)["meetups"])

        ok = c.req("POST", "/me/push/subscribe",
                   json.dumps({"csrf": token, "subscription": sub, "kinds": ["meetups", "checkins"]}),
                   {"Content-Type": "application/json"})
        self.assertEqual(ok.status, 200, ok.text[:300])
        flags = push.user_flags(uid)
        self.assertTrue(flags["meetups"] and flags["checkins"])
        me2 = c.get("/me").text
        self.assertIn("Turn off notifications", me2)

        off = c.req("POST", "/me/push/unsubscribe",
                    json.dumps({"csrf": token, "endpoint": sub["endpoint"]}),
                    {"Content-Type": "application/json"})
        self.assertEqual(off.status, 200, off.text[:300])
        self.assertFalse(push.user_flags(uid)["meetups"])

        # notify is a no-throw no-op against a fake endpoint (gone/404 is swallowed)
        n = push.notify(uid, "meetups", "Hello", "Test", "/")
        self.assertEqual(n, 0)
