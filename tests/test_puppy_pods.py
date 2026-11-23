"""Puppy Pods: under-16-week backyard playdates, vaccine gate, coarse location, reports."""
import os, sys, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in  # noqa: E402
import accounts as A
import messages as MS
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
        A.q("DELETE FROM puppy_pod_reports")
        A.q("DELETE FROM puppy_pod_checks")
        A.q("DELETE FROM puppy_pod_members")
        A.q("DELETE FROM puppy_pods")


def attest(extra=None):
    d = {"dhpp_first": "1", "vaccines_age_ok": "1", "title": "Saturday backyard play",
         "area": "Nassau", "town": "Manhasset", "place": "Our backyard on Oak Street",
         "description": "A shady yard, water out, short visits.", "capacity": "4"}
    if extra:
        d.update(extra)
    return d


class PuppyPodTests(_Clean):
    def test_create_join_hides_place_until_join_and_blocks_runs(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = host.post("/puppy-pods/new", attest({"dog": str(lid)}))
        self.assertEqual(r.status, 303)
        self.assertIn("/puppy-pods/", r.headers["Location"])
        pid = int(r.headers["Location"].split("/puppy-pods/")[1].split("-")[0].split("?")[0])
        page = follow_redirect(host, r.headers["Location"]).text
        self.assertIn("never at a dog run", page.lower())
        self.assertIn("Our backyard on Oak Street", page)  # host already joined
        self.assertIn("Lily", page)
        self.assertIn("Talk to your vet", page)
        self.assertIn("Weekly socialization checklist", page)

        # browsing members see the town, not the street
        guest, _, gid, (tid,) = member("TessOwner", dogs=[pup(name="Tess")])
        listing = guest.get("/puppy-pods").text
        self.assertIn("Saturday backyard play", listing)
        self.assertIn("Manhasset", listing)
        self.assertNotIn("Oak Street", listing)
        self.assertIn("never at a dog run", listing.lower())

        pod = follow_redirect(guest, f"/puppy-pods/{pid}").text
        self.assertIn("Manhasset", pod)
        self.assertNotIn("Oak Street", pod)
        self.assertIn("The exact place is shared after you join", pod)
        self.assertNotIn("run_id", pod)
        self.assertNotIn("/runs/", pod.split("id=\"checklist\"")[0] if 'id="checklist"' in pod else pod)

        r = guest.post(f"/puppy-pods/{pid}/join", {"dog": str(tid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertEqual(r.status, 303)
        self.assertIn("m=joined", r.headers["Location"])
        joined = follow_redirect(guest, r.headers["Location"]).text
        self.assertIn("Our backyard on Oak Street", joined)
        self.assertIn("Tess", joined)

    def test_vaccine_and_age_gates(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = host.post("/puppy-pods/new", attest({"dog": str(lid), "dhpp_first": "", "vaccines_age_ok": "1"}))
        self.assertIn("err=vaccine", r.headers["Location"])
        self.assertFalse(A.one("SELECT id FROM puppy_pods"))

        adult, _, aid, (adid,) = member("Pat", dogs=[lily(name="Tess", age="6")])
        r = adult.post("/puppy-pods/new", attest({"dog": str(adid), "title": "Adult hang"}))
        self.assertIn("err=puppy", r.headers["Location"])

        old_pup, _, oid, (odid,) = member("Quinn", dogs=[pup(name="Pip", birthday=born(16))])
        r = old_pup.post("/puppy-pods/new", attest({"dog": str(odid), "title": "Too old"}))
        self.assertIn("err=puppy", r.headers["Location"])

        # a valid pod, then a join without attestation fails
        r = host.post("/puppy-pods/new", attest({"dog": str(lid)}))
        pid = int(r.headers["Location"].split("/puppy-pods/")[1].split("-")[0].split("?")[0])
        other, _, _, (tid,) = member("TessOwner", dogs=[pup(name="Tess")])
        r = other.post(f"/puppy-pods/{pid}/join", {"dog": str(tid)})
        self.assertIn("m=vaccine", r.headers["Location"])
        self.assertFalse(P.member_of(pid, A.one("SELECT user_id FROM dogs WHERE id=:i", i=tid)[0]))

    def test_blocks_capacity_limits_and_review(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        host.post("/puppy-pods/new", attest({"dog": str(lid), "capacity": "3"}))
        pid = A.one("SELECT id FROM puppy_pods")[0]

        blocked, _, bid, (bdid,) = member("Blocked", dogs=[pup(name="Tess")])
        MS.block(hid, bid)
        self.assertNotIn("Saturday backyard play", blocked.get("/puppy-pods").text)
        page = blocked.get(f"/puppy-pods/{pid}")
        self.assertEqual(page.status, 404)
        r = blocked.post(f"/puppy-pods/{pid}/join", {"dog": str(bdid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertIn(r.status, (303, 404))
        if r.status == 303:
            # hidden as 404 after redirect, or blocked flash
            loc = r.headers["Location"]
            self.assertTrue("blocked" in loc or follow_redirect(blocked, loc).status == 404 or "couldn't find" in follow_redirect(blocked, loc).text.lower())
        self.assertFalse(P.member_of(pid, bid))

        a, _, aid, (adid,) = member("Ada", dogs=[pup(name="Pip")])
        b, _, _, (bdog,) = member("Bea", dogs=[pup(name="Cleo")])
        extra, _, eid, (edid,) = member("Eve", dogs=[pup(name="Nell")])
        self.assertIn("joined", a.post(f"/puppy-pods/{pid}/join", {"dog": str(adid), "dhpp_first": "1", "vaccines_age_ok": "1"}).headers["Location"])
        self.assertIn("joined", b.post(f"/puppy-pods/{pid}/join", {"dog": str(bdog), "dhpp_first": "1", "vaccines_age_ok": "1"}).headers["Location"])
        r = extra.post(f"/puppy-pods/{pid}/join", {"dog": str(edid), "dhpp_first": "1", "vaccines_age_ok": "1"})
        self.assertIn("m=full", r.headers["Location"])

        # host daily create cap for a new account is 1
        r = host.post("/puppy-pods/new", attest({"dog": str(lid), "title": "Second pod"}))
        self.assertIn("err=limit", r.headers["Location"])

        r = a.post(f"/puppy-pods/{pid}/report", {"reason": "Safety concern", "details": "please look"})
        self.assertIn("reported", r.headers["Location"])
        review = Client().get("/admin/review?key=test-admin-key")
        self.assertIn("Puppy Pods", review.text)
        self.assertIn("Saturday backyard play", review.text)
        self.assertIn("Safety concern", review.text)
        rid = A.one("SELECT id FROM puppy_pod_reports WHERE pod_id=:p", p=pid)[0]
        Client().post("/admin/review", {"key": "test-admin-key", "kind": "pod", "id": str(rid),
                                       "pod": str(pid), "action": "hide_pod"}, csrf=False)
        self.assertEqual(P.get(pid)["hidden"], 1)
        self.assertNotIn("Saturday backyard play", extra.get("/puppy-pods").text)

    def test_checklist_sitemap_and_signin(self):
        host, _, hid, (lid,) = member("Sam", dogs=[pup()])
        r = host.post("/puppy-pods/new", attest({"dog": str(lid)}))
        pid = int(r.headers["Location"].split("/puppy-pods/")[1].split("-")[0].split("?")[0])
        item = P.CHECKLIST[0][2][0]
        r = host.post(f"/puppy-pods/{pid}/check", {"week": "8", "item": item, "on": "1"})
        self.assertEqual(r.status, 303)
        page = follow_redirect(host, r.headers["Location"]).text
        self.assertIn("✓", page)
        self.assertIn(item, page)

        robots = Client().get("/robots.txt").text
        self.assertIn("Disallow: /puppy-pods", robots)
        sm = Client().get("/sitemap.xml").text
        self.assertNotIn("/puppy-pods", sm)

        anon = Client("10.55.1.1")
        r = anon.get("/puppy-pods")
        self.assertEqual(r.status, 303)
        self.assertIn("signin", r.headers["Location"])
        r = anon.post("/puppy-pods/new", attest({"dog": "1"}), csrf=False)
        self.assertIn(r.status, (303, 403))
