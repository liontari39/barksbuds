"""Local picks: owner-voted vets, groomers and walkers per town, on the existing recs/rec_votes tables.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
import community as C  # noqa: E402
import communityweb  # noqa: E402
from test_community import member  # noqa: E402


def setUpModule():
    communityweb.AUTO_JOBS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def add(c, category, name, town, area="Nassau", contact="https://example.com/picks", note="", real="1"):
    return c.post("/recommendations/new", {"category": category, "name": name, "town": town, "area": area,
                                           "contact": contact, "note": note, "real": real})


class LocalPicksTests(unittest.TestCase):
    def test_picks_alias_and_town_filter(self):
        tag = RUN
        c, _, uid, _ = member("Pat")
        o, _, ouid, _ = member("Robin")
        vet = f"North Shore Animal Hospital {tag}"
        groom = f"Harbor Grooming {tag}"
        walk = f"Roslyn Walks {tag}"
        self.assertEqual(add(c, "vet", vet, "Manhasset", note="Lily's vet.").status, 303)
        self.assertEqual(add(c, "groomer", groom, "Port Washington").status, 303)
        self.assertEqual(add(o, "walker", walk, "Roslyn").status, 303)
        # one vote per member: a second add of the same business does not double-count
        self.assertEqual(add(c, "vet", vet, "Manhasset").status, 303)
        rec = C.find_rec("vet", vet, "Manhasset")
        self.assertIsNotNone(rec)
        self.assertEqual(C.rec(rec["id"])["votes"], 1)
        o.post(f"/recommendations/{rec['id']}/vote", {})
        self.assertEqual(C.rec(rec["id"])["votes"], 2)
        o.post(f"/recommendations/{rec['id']}/vote", {})
        self.assertEqual(C.rec(rec["id"])["votes"], 2)

        picks = Client("10.91.1.1").get("/picks?area=Nassau").text
        recs = Client("10.91.1.1").get("/recommendations?area=Nassau").text
        for page in (picks, recs):
            self.assertIn("Local picks", page)
            self.assertIn(vet, page)
            self.assertIn(groom, page)
            self.assertIn(walk, page)
            self.assertIn("Manhasset", page)
            self.assertIn("All towns", page)
        # grouped by town when more than one town is in view
        self.assertIn('class="townh"', picks)
        self.assertIn(">Manhasset<", picks)
        self.assertIn(">Roslyn<", picks)

        manh = Client("10.91.1.2").get("/picks?area=Nassau&town=Manhasset").text
        self.assertIn(vet, manh)
        self.assertNotIn(groom, manh)
        self.assertNotIn(walk, manh)
        self.assertIn('aria-current="page"', manh)
        # unknown town is ignored, so every listing still shows
        bogus = Client("10.91.1.3").get("/picks?area=Nassau&town=Atlantis").text
        self.assertIn(vet, bogus)
        self.assertIn(groom, bogus)
        # category + town
        only_vet = Client("10.91.1.4").get("/picks?area=Nassau&cat=vet&town=Manhasset").text
        self.assertIn(vet, only_vet)
        self.assertNotIn(groom, only_vet)
        self.assertNotIn(walk, only_vet)

    def test_sort_by_votes_then_name_and_home_town_first(self):
        tag = RUN
        c, _, uid, _ = member("Lee")  # Manhasset is the default town
        o, _, ouid, _ = member("Sam", town="Roslyn")
        a = f"Alpha Clinic {tag}"
        b = f"Beta Clinic {tag}"
        self.assertEqual(add(c, "vet", a, "Roslyn").status, 303)
        self.assertEqual(add(c, "vet", b, "Manhasset").status, 303)
        # Alpha (Roslyn) gets a second vote, so more votes than Beta
        self.assertEqual(add(o, "vet", a, "Roslyn").status, 303)
        rows = C.browse_recs(["Nassau"], "vet")
        names = [r["name"] for r in rows if tag in r["name"]]
        self.assertLess(names.index(a), names.index(b))
        # signed-in member in Manhasset should see their town heading first
        page = c.get("/picks?area=Nassau&cat=vet").text
        # only compare these two town headings
        manh = page.find(">Manhasset</h2>")
        ros = page.find(">Roslyn</h2>")
        self.assertGreater(manh, 0, page[page.find("Local picks"):page.find("Local picks")+800] if "Local picks" in page else page[:800])
        self.assertGreater(ros, 0)
        self.assertLess(manh, ros)
