"""Site-wide search (/search): hits for every type, privacy exclusions, blocks, empty query, XSS escaping, limits, nav box.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import html, os, re, sys, unittest
from datetime import datetime
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
from test_community import member, lily, maggie, RUN_ID, KEY  # noqa: E402
from test_packs import make_pack  # noqa: E402
from test_meetups import create as make_meetup  # noqa: E402
import accounts as A  # noqa: E402
import community as C  # noqa: E402
import messages  # noqa: E402
import search  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def s(q, c=None, **kw):
    extra = "".join(f"&{k}={quote(v)}" for k, v in kw.items())
    return (c or Client("10.66.0.1")).get(f"/search?q={quote(q)}{extra}")


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tag = RUN.lower()
        cls.tag = tag
        cls.c, cls.email, cls.uid, (cls.lid, cls.mid) = member(f"Mike{tag}", town="Manhasset",
                                                               dogs=[lily(name=f"Lily{tag}"), maggie(name=f"Maggie{tag}")])
        cls.lily_slug = A.one("SELECT slug FROM dogs WHERE id=:i", i=cls.lid)[0]
        cls.pid, _ = make_pack(cls.c, dogs=[cls.lid], name=f"Morley Crew {tag}", town="Manhasset")
        cls.meet, _ = make_meetup(cls.c, title=f"Saturday romp {tag}")
        cls.c.post("/recommendations/new", {"category": "groomer", "name": f"Spaw Salon {tag}", "town": "Westbury", "area": "Nassau",
                                            "contact": "https://example.com", "note": "Lily's groomer.", "real": "1"})
        cls.c.post("/recommendations/new", {"category": "sitter", "name": f"Luxury Petsitter {tag}", "town": "Jericho", "area": "Nassau",
                                            "contact": "https://example.com/s", "note": "", "real": "1"})
        cls.rec_id = A.one("SELECT id FROM recs WHERE name=:n", n=f"Spaw Salon {tag}")[0]
        seen = datetime.now(C.ET).strftime("%Y-%m-%dT%H:%M")
        r = cls.c.post("/lost-found/new", {"kind": "found", "dog_name": f"Pepper{tag}", "run": "", "area": "Nassau", "town": "Roslyn",
                                           "seen": seen, "description": "Found near the pond, black collar."})
        assert r.status == 303, r.text[:400]
        cls.alert = int(r.headers["Location"].split("?")[0].rsplit("/", 1)[1])

    def test_hits_each_type(self):
        t = self.tag
        r = s(f"lily{t}")
        self.assertEqual(r.status, 200)
        self.assertIn(f'href="/dogs/{self.lily_slug}"', r.text)
        self.assertIn("Dogs", r.text)
        # breed, partial and case-insensitive
        self.assertIn(f"/dogs/{self.lily_slug}", s(f"POOD lily{t}").text)
        self.assertIn(f"Maggie{t}", s(f"french maggie{t}").text)
        # dog runs by park name
        r = s("morley")
        self.assertIn("Christopher Morley Park", r.text)
        self.assertIn("/runs/n-006-", r.text)
        self.assertIn(f"Morley Crew {t}", r.text)  # pack by name
        # meetups
        self.assertIn(f"Saturday romp {t}", s(f"romp {t}").text)
        # recommendations by category word and town
        r = s(f"sitter {t}")
        self.assertIn(f"Luxury Petsitter {t}", r.text)
        self.assertIn("/recommendations?cat=sitter#r", r.text)
        r = s(f"westbury {t}")
        self.assertIn(f"Spaw Salon {t}", r.text)
        self.assertIn(f"Spaw Salon {t}", s(f"groomer {t}").text)
        # lost & found
        r = s(f"pepper{t}")
        self.assertIn(f"/lost-found/{self.alert}", r.text)
        self.assertIn("Found: Pepper", r.text)
        # guides
        self.assertIn("/tips/dog-run-etiquette", s("etiquette").text)
        # town search finds dogs by owner town
        self.assertIn(f"/dogs/{self.lily_slug}", s(f"manhasset lily{t}").text)

    def test_type_filter_tabs_and_frag(self):
        t = self.tag
        r = s(f"{t}")
        self.assertIn('data-type="recs"', r.text)
        r = s(f"{t}", type="recs")
        self.assertIn(f"Spaw Salon {t}", r.text)
        self.assertNotIn(f"/dogs/{self.lily_slug}", r.text)
        f = s(f"{t}", frag="1")
        self.assertEqual(f.status, 200)
        self.assertNotIn("<html", f.text)
        self.assertIn("sr-count", f.text)
        self.assertEqual(s(f"{t}", type="bogus").status, 200)

    def test_privacy_never_leaks_email_or_hidden(self):
        t = self.tag
        r = s(f"mike{t}")
        self.assertNotIn(self.email, r.text)
        r = s(self.email)
        self.assertNotIn(self.email.split("@")[0] + "@", r.text.replace(html.escape(self.email), ""))
        self.assertNotIn(f"/dogs/{self.lily_slug}", r.text)  # email isn't searchable
        # hidden dog disappears
        o, _, ouid, (hid,) = member(f"Hidden{t}", dogs=[lily(name=f"Secret{t}")])
        slug = A.one("SELECT slug FROM dogs WHERE id=:i", i=hid)[0]
        self.assertIn(f"/dogs/{slug}", s(f"secret{t}").text)
        A.set_dog_hidden(hid, True)
        self.assertNotIn(f"/dogs/{slug}", s(f"secret{t}").text)
        # hidden recommendation disappears
        o.post("/recommendations/new", {"category": "vet", "name": f"Hidden Vet {t}", "town": "Roslyn", "area": "Nassau",
                                        "contact": "https://example.com/v", "note": "", "real": "1"})
        rid = A.one("SELECT id FROM recs WHERE name=:n", n=f"Hidden Vet {t}")[0]
        self.assertIn(f"Hidden Vet {t}", s(f"hidden vet {t}").text)
        C.set_rec_hidden(rid, True)
        self.assertNotIn(f"Hidden Vet {t}", s(f"hidden vet {t}").text)
        # resolved/removed alerts: removed never shows
        o.post("/lost-found/new", {"kind": "lost", "dog_name": f"Gone{t}", "run": "", "area": "Nassau", "town": "Roslyn",
                                   "seen": datetime.now(C.ET).strftime("%Y-%m-%dT%H:%M"), "description": "Brown terrier."})
        aid = A.one("SELECT id FROM lost_alerts WHERE dog_name=:n", n=f"Gone{t}")[0]
        self.assertIn(f"/lost-found/{aid}", s(f"gone{t}").text)
        C.set_alert_status(aid, "removed")
        self.assertNotIn(f"/lost-found/{aid}", s(f"gone{t}").text)

    def test_blocked_members_are_hidden(self):
        t = self.tag
        v, _, vuid, _ = member(f"Viewer{t}")
        self.assertIn(f"/dogs/{self.lily_slug}", s(f"lily{t}", v).text)
        messages.block(vuid, self.uid)
        try:
            r = s(f"lily{t}", v).text
            self.assertNotIn(f"/dogs/{self.lily_slug}", r)
            self.assertNotIn(f"Spaw Salon {t}", s(f"spaw {t}", v).text)
            self.assertIn(f"/dogs/{self.lily_slug}", s(f"lily{t}").text)  # others still see it
        finally:
            messages.unblock(vuid, self.uid)

    def test_empty_query_and_no_results(self):
        r = s("")
        self.assertEqual(r.status, 200)
        self.assertIn("What are you sniffing for?", r.text)
        self.assertIn("jack-run-72.webp", r.text)  # Jack, original art
        self.assertIn('name="robots" content="noindex"', r.text)
        r = s("   ")
        self.assertIn("What are you sniffing for?", r.text)
        r = s(f"zzqx{self.tag}nothing")
        self.assertIn("No matches for", r.text)
        self.assertIn("jk-sniff", r.text)
        self.assertNotIn("Jack", r.text)  # the art is shown, never named in page copy

    def test_xss_escaped_and_limits(self):
        r = s('<script>alert(1)</script>"><img src=x onerror=alert(1)>')
        self.assertEqual(r.status, 200)
        self.assertNotIn("<script>alert(1)", r.text)
        self.assertNotIn("<img src=x", r.text)
        self.assertIn("&lt;script&gt;", r.text)
        # stored content is escaped too
        t = self.tag
        self.c.post("/recommendations/new", {"category": "trainer", "name": f"<b>Bad</b> Trainer {t}", "town": "Roslyn", "area": "Nassau",
                                            "contact": "https://example.com/t", "note": "", "real": "1"})
        r = s(f"trainer {t}")
        self.assertNotIn("<b>Bad</b>", r.text)
        # long queries are capped
        q, terms = search.parse_query("a" * 500)
        self.assertLessEqual(len(q), search.MAX_Q)
        q, terms = search.parse_query("one two three four five six seven eight nine")
        self.assertEqual(len(terms), search.MAX_TERMS)
        self.assertEqual(s("x" * 3000).status, 200)
        # result counts are capped per type in the "All" view
        r = s("dog run")
        for grp in re.findall(r'<ul class="sr-list">(.*?)</ul>', r.text, re.S):
            self.assertLessEqual(grp.count("<li>"), search.PER_TYPE_ALL)
        self.assertIn("See all", r.text)

    def test_nav_box_on_every_page(self):
        for path in ("/", "/runs", "/dogs", "/recommendations", "/search?q=lily"):
            r = Client("10.66.0.9").get(path)
            if r.status in (301, 302, 303):
                r = Client("10.66.0.9").get(r.headers["Location"])
            self.assertIn('class="nsrch"', r.text, path)
            self.assertIn('action="/search"', r.text, path)
            self.assertIn('class="mm-search"', r.text, path)
            self.assertIn("/search.css?v=", r.text, path)
        self.assertEqual(Client("10.66.0.9").get("/search.css?v=2").status, 200)
        self.assertEqual(Client("10.66.0.9").get("/img/jack-run-72.webp?v=1").status, 200)


if __name__ == "__main__":
    unittest.main()
