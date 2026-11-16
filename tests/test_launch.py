"""Launch polish: friendly 404 page and redirects for common URL guesses."""
import http.client, os, sys, tempfile, threading, unittest
TMP = tempfile.mkdtemp(prefix="bblaunch-")
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


class LaunchTests(unittest.TestCase):
    def test_branded_404(self):
        for p in ("/nope-xyz", "/runs/nope-xyz", "/packs/nope-xyz", "/meetups/nope-xyz", "/img/nope.png", "/admin/export.csv"):
            st, _, body = get(p)
            self.assertEqual(st, 404, p)
            self.assertIn("We couldn", body, p); self.assertNotIn("Error response", body, p); self.assertIn('href="/runs"', body)
        st, _, body = get("/nope-xyz", "HEAD"); self.assertEqual((st, body), (404, ""))

    def test_aliases(self):
        for p, want in (("/signup", "/signin"), ("/login/", "/signin"), ("/join?next=%2Fme", "/signin?next=%2Fme"),
                        ("/parks", "/runs"), ("/dog-runs", "/runs"), ("/dog/lily", "/dogs/lily")):
            st, loc, _ = get(p)
            self.assertEqual((st, loc), (301, want), p)
        self.assertEqual(get("/signin")[0], 200)
        self.assertEqual(get("/")[0], 200)


if __name__ == "__main__":
    unittest.main()
