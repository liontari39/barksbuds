"""Performance and security headers: cache headers, HSTS (no preload), CSP (report-only), sitemap lastmod, the waking-up service worker, medium photos."""
import http.client, os, sys, tempfile, threading, unittest
TMP = tempfile.mkdtemp(prefix="bbperf-")
os.environ.update(DATA_DIR=TMP, EMAIL_PROVIDER="file", EMAIL_FROM="hello@barksbuds.app", ADMIN_KEY="test-admin-key", SITE_URL="", DATABASE_URL="")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server  # noqa: E402
import communityweb  # noqa: E402
communityweb.AUTO_JOBS = False


def setUpModule():
    global PORT, HTTPD
    server.init_app()
    HTTPD = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    PORT = HTTPD.server_address[1]
    threading.Thread(target=HTTPD.serve_forever, daemon=True).start()


def tearDownModule():
    HTTPD.shutdown()


def get(path, method="GET", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20); c.request(method, path, headers=headers or {})
    r = c.getresponse(); body = r.read(); c.close()
    return r.status, r, body


import io, re  # noqa: E402
from unittest import mock  # noqa: E402
import webapp  # noqa: E402


class HeaderTests(unittest.TestCase):
    def test_static_cache_control(self):
        cc = server.static_cache_control
        self.assertEqual(cc("/app.css?v=21"), "public, max-age=31536000, immutable")
        self.assertEqual(cc("/img/logo.webp?v=jack3"), "public, max-age=31536000, immutable")
        self.assertEqual(cc("/img/icon-32.png"), "public, max-age=604800")
        self.assertEqual(cc("/vendor/leaflet/leaflet.js"), "public, max-age=604800")
        self.assertEqual(cc("/favicon.ico"), "public, max-age=604800")
        self.assertEqual(cc("/runs.js"), "public, max-age=300")
        self.assertEqual(cc("/sw.js"), "no-cache")
        for p in ("/", "/dogs", "/p/1.webp", "/sitemap.xml", "/healthz", "/api/runs"):
            self.assertIsNone(cc(p), p)

    def test_live_headers(self):
        st, r, _ = get("/app.css?v=21")
        self.assertEqual(st, 200)
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=31536000, immutable")
        st, r, _ = get("/img/icon-32.png")
        self.assertEqual(r.getheader("Cache-Control"), "public, max-age=604800")
        st, r, _ = get("/img/nope.png")
        self.assertEqual(st, 404)
        self.assertNotIn("public", r.getheader("Cache-Control") or "")  # never cache a 404 for a week
        st, r, _ = get("/dogs")
        csp = r.getheader("Content-Security-Policy-Report-Only") or ""
        self.assertIn("default-src 'self'", csp); self.assertIn("frame-ancestors 'self'", csp)
        self.assertIsNone(r.getheader("Content-Security-Policy"))  # report-only, never enforcing yet
        hsts = r.getheader("Strict-Transport-Security")  # main sends it on every response (Rex, 5e7a623)
        self.assertEqual(hsts, "max-age=31536000")
        self.assertNotIn("preload", hsts)

    def test_sitemap_lastmod(self):
        self.assertEqual(server.lastmod(0), "")
        self.assertEqual(server.lastmod(1763683200), "2025-11-21")
        st, _, body = get("/sitemap.xml")
        xml = body.decode()
        self.assertEqual(st, 200)
        for r in server.load_runs()["data"][:5]:
            if r.get("last_checked"):
                self.assertRegex(xml, re.escape(r["id"]) + r"[^<]*</loc><lastmod>" + re.escape(r["last_checked"]) + "</lastmod>")
        for m in re.finditer(r"<lastmod>([^<]*)</lastmod>", xml):
            self.assertRegex(m.group(1), r"^\d{4}-\d{2}-\d{2}$")
        for m in re.finditer(r"<url><loc>[^<]*/dogs/[^<]+</loc>(<lastmod>)?", xml):
            self.assertTrue(m.group(1), m.group(0))  # every dog page carries its own updated date
        self.assertNotIn("<lastmod></lastmod>", xml)


class WakingTests(unittest.TestCase):
    def test_service_worker_and_waking_page(self):
        st, r, body = get("/sw.js")
        self.assertEqual(st, 200)
        self.assertIn("javascript", r.getheader("Content-Type"))
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")
        js = body.decode()
        self.assertIn('"/waking.html"', js)
        self.assertIn("auth|admin|unsubscribe", js)  # never replays single-use sign-in links
        self.assertIn('req.method !== "GET"', js)
        st, _, body = get("/waking.html")
        self.assertEqual(st, 200)
        self.assertIn(b"/healthz", body); self.assertIn(b"waking up", body)
        for p in ("/", "/runs", "/dogs", "/signin"):
            self.assertIn(b"navigator.serviceWorker.register('/sw.js')", get(p)[2], p)


class ImageTests(unittest.TestCase):
    def test_medium_webp_variant(self):
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (1600, 1200), (200, 150, 40)).save(buf, "JPEG"); jpg = buf.getvalue()
        webapp._MEDIUM.clear()
        with mock.patch.object(webapp.A, "photo_blob", lambda pid, which: jpg if which == "full" else None):
            out = webapp.medium_webp(424242)
        im = Image.open(io.BytesIO(out))
        self.assertEqual((im.format, im.size), ("WEBP", (1024, 768)))
        self.assertLess(len(out), len(jpg))
        self.assertIn(424242, webapp._MEDIUM)
        with mock.patch.object(webapp.A, "photo_blob", lambda pid, which: None):
            self.assertIsNone(webapp.medium_webp(5151515))
        self.assertEqual(get("/p/987654-m.webp")[0], 404)
        self.assertEqual(get("/p/987654-x.webp")[0], 404)

    def test_lazy_images_decode_async(self):
        html = get("/")[2].decode()
        for tag in re.findall(r"<img[^>]*loading=\"lazy\"[^>]*>", html):
            self.assertIn('decoding="async"', tag)


if __name__ == "__main__":
    unittest.main()
