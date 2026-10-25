"""Tips (/tips, articles, sitemap, homepage teaser), tip suggestions + /admin/tips, privacy/terms, robots.txt,
email footers, and a rehearsal of launch.py against the local test server (dry run changes nothing; --yes deletes samples)."""
import os, re, subprocess, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member  # noqa: E402
import accounts as A  # noqa: E402
import mailer  # noqa: E402
import packs as P  # noqa: E402
import tipsdata as D  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


class TipsPages(unittest.TestCase):
    def test_index_lists_every_article(self):
        r = Client().get("/tips")
        self.assertEqual(r.status, 200)
        self.assertIn('content="index,follow"', r.text)
        self.assertIn('rel="canonical"', r.text); self.assertIn('og:image', r.text)
        for t in D.TIPS:
            self.assertIn(f'href="/tips/{t["slug"]}"', r.text)
        self.assertGreaterEqual(len(D.TIPS), 10)

    def test_article_pages(self):
        for t in D.TIPS:
            r = Client().get("/tips/" + t["slug"])
            self.assertEqual(r.status, 200, t["slug"])
            self.assertIn('<meta name="description"', r.text)
            self.assertIn('"@type": "Article"', r.text)
            self.assertEqual(r.text.count("<h1"), 1)
            self.assertEqual("Ask your vet." in r.text, t["vet"], t["slug"])
            self.assertNotIn("Jack", t["body"] + t["title"] + t["desc"])
            for href in re.findall(r'href="(/tips/[a-z0-9-]+)"', t["body"]):
                self.assertIn(href.split("/")[-1], D.BY_SLUG, f"broken internal link {href} in {t['slug']}")
        self.assertEqual(Client().get("/tips/not-a-tip").status, 404)

    def test_sitemap_nav_teaser_robots(self):
        sm = Client().get("/sitemap.xml").text
        for t in D.TIPS:
            self.assertIn(f"/tips/{t['slug']}</loc>", sm)
        self.assertIn("/privacy</loc>", sm); self.assertIn("/terms</loc>", sm)
        home = Client().get("/").text
        self.assertIn('id="tips"', home); self.assertIn('href="/tips"', home)
        self.assertNotIn("{{", home)
        self.assertIn('href="/tips"', Client().get("/dogs").text)
        self.assertIn('href="/tips"', Client().get("/runs").text)
        rb = Client().get("/robots.txt")
        self.assertEqual(rb.status, 200)
        self.assertIn("Sitemap: http://127.0.0.1", rb.text); self.assertIn("Disallow: /admin/", rb.text)
        self.assertNotIn("Disallow: /me\n", rb.text)  # would also block /meetups

    def test_privacy_terms_contact(self):
        for p in ("/privacy", "/terms"):
            r = Client().get(p)
            self.assertEqual(r.status, 200); self.assertIn("hello@barksbuds.app", r.text)
        self.assertIn('href="/privacy"', Client().get("/").text)
        self.assertIn('href="/terms"', Client().get("/packs").text)


class TipSuggestions(unittest.TestCase):
    def test_flow(self):
        anon = Client("10.44.0.1")
        r = anon.get("/tips/suggest")
        self.assertEqual(r.status, 303); self.assertIn("/signin", r.headers["Location"])
        c, email, uid, _ = member("tipper")
        self.assertIn("Suggest a tip", c.get("/tips/suggest").text)
        self.assertEqual(c.post("/tips/suggest", {"title": "x", "body": "y"}, csrf=False).status, 403)
        r = c.post("/tips/suggest", {"topic": "runs", "title": "No", "body": "short"})
        self.assertEqual(r.status, 422)
        r = c.post("/tips/suggest", {"topic": "runs", "title": "Bring a towel <b>", "body": "Beach runs get sandy, so keep a towel in the car."})
        self.assertEqual(r.status, 303); self.assertEqual(r.headers["Location"], "/tips?m=sent")
        sid = A.one("SELECT id FROM tip_suggestions WHERE user_id=:u", u=uid)[0]
        self.assertEqual(Client().get("/admin/tips?key=wrong").status, 404)
        adm = Client().get("/admin/tips?key=test-admin-key").text
        self.assertIn("Bring a towel &lt;b&gt;", adm)
        self.assertNotIn("Bring a towel", Client().get("/tips").text)  # never auto-published
        Client().post("/admin/tips", {"key": "test-admin-key", "id": str(sid), "action": "reviewed"}, csrf=False)
        self.assertEqual(A.one("SELECT status FROM tip_suggestions WHERE id=:i", i=sid)[0], "reviewed")
        for i in range(2):
            c.post("/tips/suggest", {"topic": "other", "title": f"Tip {i}", "body": "Another useful tip for dog people."})
        self.assertEqual(c.post("/tips/suggest", {"topic": "other", "title": "Tip 4", "body": "One too many tips for today."}).status, 429)
        Client().post("/admin/tips", {"key": "test-admin-key", "id": str(sid), "action": "delete"}, csrf=False)
        self.assertIsNone(A.one("SELECT id FROM tip_suggestions WHERE id=:i", i=sid))


class EmailFooters(unittest.TestCase):
    def test_footers_have_contact_privacy_and_optout(self):
        _s, h, t, unsub = mailer.build("https://barksbuds.app", "Mike", "Lily", "x@example.com")
        for body in (h, t):
            self.assertIn("hello@barksbuds.app", body); self.assertIn("/privacy", body)
        self.assertIn("Remove me from the list", h)
        _s, h, t = mailer.build_signin("https://barksbuds.app", "https://barksbuds.app/auth?t=x", "x@example.com")
        self.assertIn("hello@barksbuds.app", h); self.assertIn("/privacy", t)


class LaunchScript(unittest.TestCase):
    def run_launch(self, *args):
        env = dict(os.environ, BASE=f"http://127.0.0.1:{T.PORT}", ADMIN_KEY="test-admin-key")
        return subprocess.run([sys.executable, os.path.join(ROOT, "launch.py"), *args], env=env, capture_output=True, text=True, timeout=120)

    def test_dry_run_then_yes(self):
        _c, _e, oid, odogs = member("lo")
        pid = P.save(oid, {"name": "Launch Sample Crew", "area": "Nassau", "town": "Manhasset", "run_id": "n-006",
                           "description": "A sample pack.", "fit": "", "visibility": "open", "dogs": odogs},
                     seed_key="launch-sample-" + T.RUN, is_sample=1)
        out = self.run_launch()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("dry run", out.stdout); self.assertIn("REMOVE MEETUP_EMAIL_ALLOWLIST", out.stdout)
        self.assertNotIn("test-admin-key", out.stdout + out.stderr)
        self.assertIsNotNone(A.one("SELECT id FROM packs WHERE id=:i", i=pid))  # dry run changed nothing
        out = self.run_launch("--yes")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("delete_all_samples: HTTP 303 ok", out.stdout)
        self.assertIsNone(A.one("SELECT id FROM packs WHERE id=:i", i=pid))
        self.assertEqual(A.one("SELECT COUNT(*) FROM packs WHERE is_sample=1")[0], 0)
        self.assertNotIn("test-admin-key", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
