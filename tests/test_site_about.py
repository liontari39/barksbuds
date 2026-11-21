"""About page (Jack + trust list), sign-in privacy line, About links."""
import http.client, os, sys, tempfile, threading, unittest
TMP = tempfile.mkdtemp(prefix="bbabout-")
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


def get(path, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20); c.request(method, path)
    r = c.getresponse(); body = r.read().decode("utf-8", "replace"); c.close()
    return r.status, r.getheader("Location"), body


class AboutTests(unittest.TestCase):
    def test_about_page(self):
        st, _, body = get("/about")
        self.assertEqual(st, 200)
        for s in ("About BarksBuds", "Meet Jack", "Cairn terrier", "passed away in 2024", "Jack lived to 17",
                  "We never sell or share your info.", 'id="trust"', 'href="/privacy"', 'rel="canonical"'):
            self.assertIn(s, body)
        self.assertIn('content="index,follow"', body)
        self.assertIn("The scruffy terrier in our logo is Jack, Mike's Cairn terrier. Jack lived to 17 and passed away in 2024.", body)
        self.assertIn("We kept him in the logo, so a little of Jack comes along to every dog run, meetup and pack on BarksBuds.", body)
        self.assertIn("Jack, Mike's Cairn terrier", body)
        self.assertIn("/img/jack-about-480.webp?v=1", body)
        self.assertIn("/img/jack-about-960.webp?v=1", body)
        self.assertIn("/img/jack-about.jpg?v=1", body)
        self.assertIn('loading="lazy"', body)
        self.assertNotIn("/img/icon-440.webp", body)
        low = body.lower()
        for bad in ("maggie", "konstantinopl3", "owl", "crescent"):
            self.assertNotIn(bad, low)
        self.assertEqual(get("/about/")[0], 200)
        st, _, _ = get("/img/jack-about.jpg?v=1")
        self.assertEqual(st, 200)
        st, _, _ = get("/img/jack-about-960.webp?v=1")
        self.assertEqual(st, 200)

    def test_signin_privacy_line(self):
        st, _, body = get("/signin")
        self.assertEqual(st, 200)
        self.assertIn("We never sell or share your info.", body)
        self.assertIn('href="/about#trust"', body)

    def test_about_linked_everywhere(self):
        for p in ("/", "/runs", "/dogs", "/signin", "/tips"):
            st, _, body = get(p)
            self.assertEqual(st, 200, p)
            self.assertIn('href="/about"', body, p)
        st, _, body = get("/sitemap.xml")
        self.assertIn("/about</loc>", body)


if __name__ == "__main__":
    unittest.main()
