"""Puppy Pods as a pack kind: backyard playdates, vaccine gate, 301s from /puppy-pods, graduation."""
import os, sys, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in  # noqa: E402
import accounts as A
import messages as MS
import packs as PK
import puppypods as P
from test_community import member, lily, follow_redirect


def born(weeks):
    return (date.today() - timedelta(weeks=weeks, days=2)).isoformat()


def pup(**over):
    d = lily(age="", birthday=born(10), size="small")
    d.update(over)
    return d


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


class _Clean(unittest.TestCase):
    def setUp(self):
        A.q("DELETE FROM puppy_pack_checks")
        for (i,) in A.q("SELECT id FROM packs"):
            PK.delete(i)


def attest(extra=None):
    d = {"kind": "puppy", "name": "Saturday backyard play", "area": "Nassau", "town": "Manhasset",
         "place": "Our backyard on Oak Street", "description": "A shady yard, water out, short visits.",
         "capacity": "4", "dhpp_first": "1", "vaccines_age_ok": "1", "visibility": "open"}
    if extra:
        d.update(extra)
    if "title" in d:
        d["name"] = d.pop("title")
    if "dog" in d and "dogs" not in d:
        d["dogs"] = d.pop("dog")
    return d


def create_pod(client, dog_id, **extra):
    r = client.post("/packs/new?kind=puppy", attest({"dogs": str(dog_id), **extra}))
    return r


def pid_of(r):
    loc = r.headers["Location"]
    return int(loc.split("/packs/")[1].split("-")[0].split("?")[0])


def pack_url(pid):
    p = PK.get(pid)
    return f"/packs/{pid}" + (f"-{p['slug']}" if p.get("slug") else "")


class PuppyPodTests(_Clean):
    def test_create_join_hides_place_until_join_and_blocks_runs(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = create_pod(host, lid)
        self.assertEqual(r.status, 303)
        self.assertIn("/packs/", r.headers["Location"])
        self.assertIn("p_created_puppy", r.headers["Location"])
        pid = pid_of(r)
        p = PK.get(pid)
        self.assertEqual(p["kind"], "puppy")
        page = follow_redirect(host, r.headers["Location"]).text
        self.assertIn("never at a dog run", page.lower())
        self.assertIn("Our backyard on Oak Street", page)  # host already joined
        self.assertIn("Lily", page)
        self.assertIn("Talk to your vet", page)
        self.assertIn("Weekly socialization checklist", page)

        # browsing members see the town, not the street
        guest, _, gid, (tid,) = member("TessOwner", dogs=[pup(name="Tess")])
        listing = guest.get("/packs?kind=puppy").text
        self.assertIn("Saturday backyard play", listing)
        self.assertIn("Manhasset", listing)
        self.assertNotIn("Oak Street", listing)
        self.assertIn("never at a dog run", listing.lower())
        self.assertIn("Puppy Pods", listing)
        # regular pack list does not include puppy packs
        self.assertNotIn("Saturday backyard play", guest.get("/packs").text)

        pod = guest.get(pack_url(pid)).text
        self.assertIn("Manhasset", pod)
        self.assertNotIn("Oak Street", pod)
        self.assertIn("The exact place is shared after you join", pod)
        self.assertNotIn("Home run", pod)

        r = guest.post(f"/packs/{pid}/join", {"dogs": str(tid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertEqual(r.status, 303)
        self.assertIn("p_joined", r.headers["Location"])
        joined = follow_redirect(guest, r.headers["Location"]).text
        self.assertIn("Our backyard on Oak Street", joined)
        self.assertIn("Tess", joined)

        # pack-tied meetup cannot be at a dog run
        r = host.post("/meetups/new", {"title": "Yard play", "date": "2027-03-01", "time": "10:00",
                                       "duration": "60", "loc": "run", "run_id": "n-006",
                                       "description": "A short backyard visit.", "pack_id": str(pid),
                                       "visibility": "pack"})
        self.assertEqual(r.status, 400)
        self.assertIn("backyard", r.text.lower())

    def test_vaccine_and_age_gates(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = create_pod(host, lid, dhpp_first="", vaccines_age_ok="1")
        self.assertEqual(r.status, 422)
        self.assertIn("DHPP", r.text)
        self.assertFalse(A.one("SELECT id FROM packs"))

        adult, _, aid, (adid,) = member("Pat", dogs=[lily(name="Tess", age="6")])
        r = create_pod(adult, adid, title="Adult hang")
        self.assertEqual(r.status, 422)
        self.assertIn("under 16 weeks", r.text)

        old_pup, _, oid, (odid,) = member("Quinn", dogs=[pup(name="Pip", birthday=born(16))])
        r = create_pod(old_pup, odid, title="Too old")
        self.assertEqual(r.status, 422)
        self.assertIn("under 16 weeks", r.text)

        r = create_pod(host, lid)
        self.assertEqual(r.status, 303)
        pid = pid_of(r)
        other, _, _, (tid,) = member("TessOwner", dogs=[pup(name="Tess")])
        r = other.post(f"/packs/{pid}/join", {"dogs": str(tid)})
        self.assertIn("e=vaccine", r.headers["Location"])
        self.assertFalse(PK.is_member(pid, A.one("SELECT user_id FROM dogs WHERE id=:i", i=tid)[0]))

    def test_blocks_capacity_limits_and_review(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = create_pod(host, lid, capacity="3")
        self.assertEqual(r.status, 303)
        pid = pid_of(r)

        blocked, _, bid, (bdid,) = member("Blocked", dogs=[pup(name="Tess")])
        MS.block(hid, bid)
        self.assertNotIn("Saturday backyard play", blocked.get("/packs?kind=puppy").text)
        page = blocked.get(pack_url(pid))
        self.assertEqual(page.status, 404)
        r = blocked.post(f"/packs/{pid}/join", {"dogs": str(bdid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertIn(r.status, (303, 404))
        if r.status == 303:
            loc = r.headers["Location"]
            dest = follow_redirect(blocked, loc)
            self.assertTrue("blocked" in loc or dest.status == 404 or "couldn't find" in dest.text.lower())
        self.assertFalse(PK.is_member(pid, bid))

        a, _, aid, (adid,) = member("Ada", dogs=[pup(name="Pip")])
        b, _, _, (bdog,) = member("Bea", dogs=[pup(name="Cleo")])
        extra, _, eid, (edid,) = member("Eve", dogs=[pup(name="Nell")])
        self.assertIn("p_joined", a.post(f"/packs/{pid}/join", {"dogs": str(adid), "dhpp_first": "1", "vaccines_age_ok": "1"}).headers["Location"])
        self.assertIn("p_joined", b.post(f"/packs/{pid}/join", {"dogs": str(bdog), "dhpp_first": "1", "vaccines_age_ok": "1"}).headers["Location"])
        r = extra.post(f"/packs/{pid}/join", {"dogs": str(edid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertIn("e=full", r.headers["Location"])

        r = create_pod(host, lid, title="Second pod")
        self.assertEqual(r.status, 422)
        self.assertIn("try again tomorrow", r.text.lower())

        r = a.post(f"/packs/{pid}/report", {"reason": "Safety concern", "details": "please look"})
        self.assertIn("reported", r.headers["Location"])
        review = Client().get("/admin/review?key=test-admin-key")
        self.assertIn("Saturday backyard play", review.text)
        self.assertIn("Safety concern", review.text)
        Client().post("/admin/packs", {"key": "test-admin-key", "id": str(pid), "action": "hide"}, csrf=False)
        self.assertEqual(PK.get(pid)["hidden"], 1)
        self.assertNotIn("Saturday backyard play", extra.get("/packs?kind=puppy").text)

    def test_checklist_sitemap_signin_redirects_and_graduate(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = create_pod(host, lid)
        self.assertEqual(r.status, 303)
        pid = pid_of(r)
        slug = PK.get(pid)["slug"]
        item = P.CHECKLIST[0][2][0]
        r = host.post(f"/packs/{pid}/check", {"week": "8", "item": item, "on": "1"})
        self.assertEqual(r.status, 303)
        page = follow_redirect(host, r.headers["Location"]).text
        self.assertIn("✓", page)
        self.assertIn(item, page)

        robots = Client().get("/robots.txt").text
        self.assertIn("Disallow: /puppy-pods", robots)
        sm = Client().get("/sitemap.xml").text
        self.assertNotIn("/puppy-pods", sm)
        self.assertNotIn(f"/packs/{pid}", sm)

        anon = Client("10.55.1.1")
        r = anon.get("/puppy-pods")
        self.assertEqual(r.status, 301)
        self.assertIn("/packs?kind=puppy", r.headers["Location"])
        r = anon.get("/packs?kind=puppy")
        self.assertEqual(r.status, 303)
        self.assertIn("signin", r.headers["Location"])
        r = anon.get("/puppy-pods/new")
        self.assertEqual(r.status, 301)
        self.assertIn("/packs/new?kind=puppy", r.headers["Location"])
        r = anon.get(f"/puppy-pods/{pid}-{slug}")
        self.assertEqual(r.status, 301)
        self.assertIn(f"/packs/{pid}", r.headers["Location"])
        r = anon.post("/puppy-pods/new", attest({"dogs": "1"}), csrf=False)
        self.assertIn(r.status, (301, 303, 403))

        # host sees the graduate prompt only after every listed puppy is 16 weeks
        page = host.get(pack_url(pid)).text
        self.assertNotIn("Graduate to a regular pack", page)
        A.q("UPDATE dogs SET birthday=:b WHERE id=:i", b=born(16), i=lid)
        page = host.get(pack_url(pid)).text
        self.assertIn("Graduate to a regular pack", page)
        self.assertIn("All the puppies in this pod are now 16 weeks or older", page)
        r = host.post(f"/packs/{pid}/graduate", {})
        self.assertEqual(r.status, 303)
        self.assertIn("p_graduated", r.headers["Location"])
        self.assertEqual(PK.get(pid)["kind"], "regular")
        self.assertTrue(PK.is_member(pid, hid))
        page = follow_redirect(host, r.headers["Location"]).text
        self.assertNotIn("Weekly socialization checklist", page)
        self.assertIn("now a regular pack", page)
