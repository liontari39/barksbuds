"""'Be the first in your town' empty states and the curated, sourced Long Island picks."""
import http.client, os, re, sys, tempfile, threading, unittest
from contextlib import ExitStack
from unittest import mock
TMP = tempfile.mkdtemp(prefix="bbempty-")
os.environ.update(DATA_DIR=TMP, EMAIL_PROVIDER="file", EMAIL_FROM="hello@barksbuds.app", ADMIN_KEY="test-admin-key", SITE_URL="", DATABASE_URL="")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server  # noqa: E402
import communityweb  # noqa: E402
import localpicks as L  # noqa: E402
import emptystate as ES  # noqa: E402
communityweb.AUTO_JOBS = False

OFFICIAL = ("nassaucountyny.gov", "oysterbaytown.com", "manorhaven.gov", "gnparksny.gov", "suffolkcountyny.gov")


def setUpModule():
    global PORT, HTTPD
    server.init_app()
    HTTPD = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    PORT = HTTPD.server_address[1]
    threading.Thread(target=HTTPD.serve_forever, daemon=True).start()


def tearDownModule():
    HTTPD.shutdown()


def empty_lists():
    """Other test modules share this process and database, so force every list to be empty."""
    import privacy, packs, meetups, feed
    st = ExitStack()
    st.enter_context(mock.patch.object(privacy, "directory", lambda *a, **k: []))
    st.enter_context(mock.patch.object(packs, "browse", lambda *a, **k: []))
    st.enter_context(mock.patch.object(meetups, "upcoming", lambda *a, **k: []))
    st.enter_context(mock.patch.object(feed, "page", lambda *a, **k: ([], None)))
    return st


def get(path):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20); c.request("GET", path)
    r = c.getresponse(); body = r.read().decode("utf-8", "replace"); c.close()
    return r.status, body


class EmptyStateTests(unittest.TestCase):
    def setUp(self):
        self.st = empty_lists(); self.st.__enter__()

    def tearDown(self):
        self.st.__exit__(None, None, None)

    def test_four_pages_show_first_in_town(self):
        for p, cta in (("/dogs", "Add your dog"), ("/packs", "Start a pack"), ("/meetups", "Host a meetup"), ("/photos", "Sign in to share a photo")):
            st, body = get(p)
            self.assertEqual(st, 200, p)
            self.assertIn('class="empty bfirst"', body, p)
            self.assertIn("Be the first", body, p)
            self.assertIn(cta, body, p)
            self.assertIn("Dog runs to try on Long Island", body, p)
            frag = body[body.index('class="empty bfirst"'):body.index("Rules and hours can change")]
            self.assertNotIn("Maggie", frag, p)

    def test_area_filters(self):
        st, body = get("/dogs?area=Suffolk")
        self.assertIn("Be the first in Suffolk County", body)
        self.assertIn("Blydenburgh County Park", body)
        self.assertNotIn("Christopher Morley Park", body)  # Nassau run not shown for Suffolk
        st, body = get("/dogs?area=Queens")
        self.assertIn("Be the first in Queens", body)
        self.assertNotIn("Dog runs to try on Long Island", body)  # only Long Island is curated so far
        st, body = get("/packs?region=li")
        self.assertIn("Be the first in Long Island", body)

    def test_every_pick_is_sourced_from_an_official_page(self):
        ids = {r["id"] for r in server.load_runs()["data"]}
        for r in L.RUNS:
            self.assertTrue(r["src"].startswith("https://") and any(d in r["src"] for d in OFFICIAL), r)
            self.assertIn(r["id"], ids, r)  # links to our run page
            self.assertIn(r["area"], ("Nassau", "Suffolk"))
        for t in L.TIPS:
            self.assertTrue(any(d in t["src"] for d in OFFICIAL), t)
        html = ES.picks_html(None, server.load_runs()["data"])
        n_cards = html.count('class="lp-card"')
        self.assertEqual(html.count("Source: <a href=\"https://"), n_cards)
        self.assertIn('rel="noopener nofollow"', html)
        self.assertRegex(html, r'href="/runs/n-006[^"]*"')

    def test_guides_exist(self):
        for slug, _ in L.GUIDES:
            self.assertEqual(get("/tips/" + slug)[0], 200, slug)

    def test_no_occult_or_personal_links(self):
        st, body = get("/dogs")
        low = body.lower()
        for bad in ("konstantinopl3", "owl", "crescent"):
            self.assertNotIn(bad, low)


if __name__ == "__main__":
    unittest.main()
