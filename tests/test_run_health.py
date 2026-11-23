"""Owner-reported run health heads-ups: expiry, disclaimers, privacy, and the review queue."""
import os, sys, unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in  # noqa: E402
import accounts as A
import community as C
import runhealth as RH
from test_community import member, lily, follow_redirect

RUN_ID = "n-006"
ET = ZoneInfo("America/New_York")


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()



def health_section(page):
    if 'id="health"' not in page:
        return page
    rest = page.split('id="health"', 1)[1]
    nxt = rest.find('<div class="panel')
    return rest[:nxt] if nxt != -1 else rest


class _Clean(unittest.TestCase):
    def setUp(self):
        C.q("DELETE FROM run_health_reports")
        C.q("DELETE FROM run_health_pins")


class HealthPinTests(_Clean):
    def test_post_shows_disclaimer_hides_reporter_and_expires(self):
        owner, _, uid, _ = member("Sam", dogs=[lily()])
        viewer, _, _, _ = member("TessOwner", dogs=[lily(name="Tess")])
        r = owner.post(f"/runs/{RUN_ID}/health", {"kind": "kennel_cough", "note": "Heard a few coughs near the gate."})
        self.assertEqual(r.status, 303)
        self.assertIn("m=health", r.headers["Location"])
        self.assertIn("#health", r.headers["Location"])
        self.assertEqual(len(RH.live_pins(RUN_ID)), 1)

        page = follow_redirect(viewer, f"/runs/{RUN_ID}").text
        health = health_section(page)
        self.assertIn("Kennel cough", health)
        self.assertIn("Unverified", health)
        self.assertIn("Talk to your vet", health)
        self.assertIn("not a diagnosis", health.lower())
        self.assertIn("Heard a few coughs near the gate.", health)
        self.assertNotIn("Sam", health)
        self.assertNotIn("Lily", health)
        expires = datetime.now(ET) + timedelta(seconds=RH.HEALTH_TTL)
        self.assertIn(expires.strftime("%b"), health)

        # unsigned visitors also see the pin, still without a reporter name
        pub = follow_redirect(Client("10.91.1.1"), f"/runs/{RUN_ID}").text
        pub_h = health_section(pub)
        self.assertIn("Kennel cough", pub_h)
        self.assertIn("Talk to your vet", pub)
        self.assertNotIn("Sam", pub_h)

        # expired pins drop off
        C.q("UPDATE run_health_pins SET expires_at=:t", t=C.now() - 10)
        gone = follow_redirect(viewer, f"/runs/{RUN_ID}").text
        self.assertIn("No live health heads-ups", gone)
        self.assertNotIn("Heard a few coughs near the gate.", gone)
        self.assertEqual(RH.live_pins(RUN_ID), [])

    def test_rate_limit_and_duplicate_kind(self):
        owner, _, uid, _ = member("Sam", dogs=[lily()])
        self.assertEqual(owner.post(f"/runs/{RUN_ID}/health", {"kind": "ticks"}).status, 303)
        r = owner.post(f"/runs/{RUN_ID}/health", {"kind": "ticks"})
        self.assertIn("health_already", r.headers["Location"])
        r = owner.post(f"/runs/{RUN_ID}/health", {"kind": "fleas"})
        loc = r.headers["Location"]
        self.assertIn("m=health", loc)
        self.assertNotIn("already", loc)
        self.assertNotIn("slow", loc)
        r = owner.post(f"/runs/{RUN_ID}/health", {"kind": "giardia"})
        self.assertIn("health_slow", r.headers["Location"])
        self.assertEqual(len(RH.live_pins(RUN_ID)), 2)

    def test_signed_out_cannot_post(self):
        r = Client("10.91.2.1").post(f"/runs/{RUN_ID}/health", {"kind": "ticks"}, csrf=False)
        self.assertIn(r.status, (303, 403, 401))
        if r.status == 303:
            self.assertIn("signin", r.headers["Location"])
        self.assertEqual(RH.live_pins(RUN_ID), [])

    def test_unknown_kind_is_rejected(self):
        owner, _, _, _ = member("Sam", dogs=[lily()])
        r = owner.post(f"/runs/{RUN_ID}/health", {"kind": "parvo_diagnosed"})
        self.assertIn("health_bad", r.headers["Location"])
        self.assertEqual(RH.live_pins(RUN_ID), [])


class HealthReportTests(_Clean):
    def test_report_lands_in_review_queue_and_hide(self):
        owner, _, uid, _ = member("Sam", dogs=[lily()])
        viewer, _, vid, _ = member("TessOwner", dogs=[lily(name="Tess")])
        owner.post(f"/runs/{RUN_ID}/health", {"kind": "giardia", "note": "Saw signs on the path."})
        pins = RH.live_pins(RUN_ID)
        self.assertEqual(len(pins), 1)
        pid = pins[0]["id"]

        r = viewer.post(f"/runs/{RUN_ID}/health/{pid}/report",
                        {"reason": "Not accurate or outdated", "details": "looks stale"})
        self.assertEqual(r.status, 303)
        self.assertIn("health_reported", r.headers["Location"])

        page = Client().get("/admin/review?key=test-admin-key")
        self.assertEqual(page.status, 200)
        self.assertIn("Giardia", page.text)
        self.assertIn("Not accurate or outdated", page.text)
        self.assertIn("looks stale", page.text)
        self.assertIn("Run health heads-ups", page.text)

        rid = C.one("SELECT id FROM run_health_reports WHERE pin_id=:p", p=pid)[0]
        r = Client().post("/admin/review", {"key": "test-admin-key", "kind": "health", "id": str(rid),
                                           "pin": str(pid), "action": "hide_health"}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(RH.live_pins(RUN_ID), [])
        hidden = follow_redirect(viewer, f"/runs/{RUN_ID}").text
        self.assertIn("No live health heads-ups", hidden)
        self.assertNotIn("Saw signs on the path.", hidden)
        st = C.one("SELECT status FROM run_health_reports WHERE id=:i", i=rid)[0]
        self.assertEqual(st, "resolved")

    def test_source_defaults_to_owner(self):
        owner, _, uid, _ = member("Sam", dogs=[lily()])
        owner.post(f"/runs/{RUN_ID}/health", {"kind": "other", "note": "Something odd near the fountain."})
        p = RH.live_pins(RUN_ID)[0]
        self.assertEqual(p["source"], "owner")
        # vet source is stored for later use, and relabeled when present
        C.q("UPDATE run_health_pins SET source='vet' WHERE id=:i", i=p["id"])
        page = follow_redirect(Client("10.91.3.1"), f"/runs/{RUN_ID}").text
        self.assertIn("Vet-sourced", page)
