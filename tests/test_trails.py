"""Dog-friendly hiking trails (/trails, /api/trails, sitemap/nav links, the etiquette tip) and trail suggestions
through the existing tip-suggestion queue (/trails/suggest -> /tips/suggest?topic=trail -> /admin/tips)."""
import json, os, re, sys, unittest
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Client  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member  # noqa: E402
import accounts as A  # noqa: E402
import tipsdata as D  # noqa: E402
import trailsdata as TD  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# Rough lat/lng boxes for each region; a pin outside its box is almost certainly a typo.
BOUNDS = {"nyc": (40.49, 40.92, -74.26, -73.69), "li": (40.54, 41.16, -73.77, -71.84), "wch": (40.88, 41.37, -73.99, -73.48)}
OFFICIAL = ("nyc.gov", "nycgovparks.org", "parks.ny.gov", "ny.gov", "nps.gov", "westchestergov.com",
            "westchestercountyny.gov", "suffolkcountyny.gov", "cornell.edu")


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


class TrailData(unittest.TestCase):
    def test_count_regions_and_slugs(self):
        self.assertEqual(len(TD.TRAILS), 28)
        regions = {t["region"] for t in TD.TRAILS}
        self.assertEqual(regions, {"nyc", "li", "wch"})
        slugs = [t["slug"] for t in TD.TRAILS]
        self.assertEqual(len(slugs), len(set(slugs)))
        for s in slugs:
            self.assertRegex(s, r"^[a-z0-9-]+$")

    def test_every_trail_is_sourced_and_pinned(self):
        for t in TD.TRAILS:
            with self.subTest(t["slug"]):
                for k in ("name", "park", "area", "dogs"):
                    self.assertTrue(t[k].strip(), k)
                self.assertIn("leash", t["dogs"].lower())
                self.assertTrue(t["sources"])
                for label, url in t["sources"]:
                    self.assertTrue(label.strip())
                    u = urlparse(url)
                    self.assertEqual(u.scheme, "https", url)
                    self.assertTrue(any(u.netloc == d or u.netloc.endswith("." + d) for d in OFFICIAL), url)
                lo, hi, w, e = BOUNDS[t["region"]]
                self.assertTrue(lo <= t["lat"] <= hi and w <= t["lng"] <= e, (t["lat"], t["lng"]))
                self.assertIsInstance(t["restrictions"], list)

    def test_excluded_parks_stay_out(self):
        for t in TD.TRAILS:
            self.assertNotEqual(t["park"], "Forest Park")
            self.assertNotIn("Amsterdam Beach", t["park"])
            for _, url in t["sources"]:
                self.assertNotIn("nassaucountyny.gov", url)


class TrailPages(unittest.TestCase):
    def test_trails_page(self):
        r = Client().get("/trails")
        self.assertEqual(r.status, 200)
        self.assertIn('content="index,follow"', r.text)
        self.assertIn('rel="canonical"', r.text)
        self.assertEqual(r.text.count("<h1"), 1)
        self.assertEqual(r.text.count('class="trcard"'), len(TD.TRAILS))
        for t in TD.TRAILS:
            self.assertIn(f'id="{t["slug"]}"', r.text)
            for _, url in t["sources"]:
                self.assertIn(url.replace("&", "&amp;"), r.text)
        for k, v in TD.REGIONS:
            self.assertIn(f'data-region="{k}"', r.text); self.assertIn(v, r.text)
        self.assertIn("/vendor/leaflet/leaflet.js", r.text)
        self.assertIn('href="/tips/trail-etiquette-with-dogs"', r.text)
        self.assertIn('href="/trails/suggest"', r.text)
        m = re.search(r'<script type="application/json" id="trail-data">(.*?)</script>', r.text, re.S)
        self.assertEqual(len(json.loads(m.group(1))), len(TD.TRAILS))
        self.assertIn('"@type": "ItemList"', r.text)
        self.assertNotIn("Jack", r.text)

    def test_api(self):
        r = Client().get("/api/trails")
        self.assertEqual(r.status, 200)
        d = json.loads(r.text)
        self.assertEqual(d["count"], 28); self.assertEqual(len(d["data"]), 28)
        self.assertEqual(d["updated"], TD.CHECKED)
        self.assertEqual({x["region"] for x in d["data"]}, {"nyc", "li", "wch"})

    def test_sitemap_and_nav(self):
        self.assertIn("/trails</loc>", Client().get("/sitemap.xml").text)
        for p in ("/", "/runs", "/tips", "/meetups", "/trails"):
            self.assertIn('href="/trails"', Client().get(p).text, p)
        self.assertIn('href="/trails" aria-current=page', Client().get("/trails").text)

    def test_etiquette_tip(self):
        t = D.BY_SLUG["trail-etiquette-with-dogs"]
        self.assertNotIn("Jack", t["body"] + t["title"] + t["desc"])
        self.assertIn("/trails", t["body"])
        r = Client().get("/tips/trail-etiquette-with-dogs")
        self.assertEqual(r.status, 200); self.assertIn("Ask your vet.", r.text)
        self.assertIn('href="/tips/trail-etiquette-with-dogs"', Client().get("/tips").text)


class TrailSuggestions(unittest.TestCase):
    def test_flow(self):
        r = Client("10.45.0.1").get("/trails/suggest")
        self.assertEqual(r.status, 303); self.assertEqual(r.headers["Location"], "/tips/suggest?topic=trail")
        r = Client("10.45.0.2").get("/tips/suggest?topic=trail")
        self.assertEqual(r.status, 303); self.assertIn("/signin", r.headers["Location"])
        c, email, uid, _ = member("trailer")
        page = c.get("/tips/suggest?topic=trail").text
        self.assertIn("Suggest a trail", page)
        self.assertRegex(page, r'<option value="trail" selected')
        r = c.post("/tips/suggest", {"topic": "trail", "title": "Muttontown <i>", "body": "Leashed dogs welcome on the trails, lot on Route 25A."})
        self.assertEqual(r.status, 303); self.assertEqual(r.headers["Location"], "/trails?m=sent")
        self.assertIn("Thanks", Client().get("/trails?m=sent").text)
        row = A.one("SELECT id, topic FROM tip_suggestions WHERE user_id=:u", u=uid)
        self.assertEqual(row[1], "trail")
        adm = Client().get("/admin/tips?key=test-admin-key").text
        self.assertIn("Trail suggestion", adm); self.assertIn("Muttontown &lt;i&gt;", adm)
        self.assertNotIn("Muttontown", Client().get("/trails").text)  # never auto-published
        Client().post("/admin/tips", {"key": "test-admin-key", "id": str(row[0]), "action": "delete"}, csrf=False)
        # a normal tip still goes back to /tips
        r = c.post("/tips/suggest", {"topic": "runs", "title": "Water bowl", "body": "Bring a collapsible bowl for summer runs."})
        self.assertEqual(r.headers["Location"], "/tips?m=sent")


if __name__ == "__main__":
    unittest.main()
