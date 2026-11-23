"""One-tap run condition reports: members only, rate-limited, fading after a few hours."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402
import accounts as A  # noqa: E402
import community as C  # noqa: E402

RUN_ID = "n-006"


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


_n = [0]


def member(name="cond"):
    _n[0] += 1
    c = Client(f"10.72.{_n[0] // 200}.{_n[0] % 200 + 1}")
    email = f"{name.lower().replace(' ', '')}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    c.post("/me/profile", {"display_name": name, "area": "Nassau", "town": "Manhasset", "bio": ""})
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid


def page(c, path=f"/runs/{RUN_ID}"):
    r = c.get(path)
    if r.status in (301, 302, 303):
        r = c.get(r.headers["Location"])
    return r


class RunConditionTests(unittest.TestCase):
    def setUp(self):
        A.q("DELETE FROM run_conditions")

    def test_members_report_conditions_that_fade(self):
        c, _, uid = member("Sam")
        home = page(c)
        self.assertEqual(home.status, 200)
        self.assertIn("How is the run?", home.text)
        self.assertIn("Muddy", home.text)
        self.assertIn("/runs/n-006/condition", home.text)
        r = c.post(f"/runs/{RUN_ID}/condition", {"kind": "muddy"})
        self.assertEqual(r.status, 303)
        self.assertIn("m=cond", r.headers["Location"])
        shown = page(c)
        self.assertIn("Muddy · 1", shown.text)
        # already live
        r = c.post(f"/runs/{RUN_ID}/condition", {"kind": "muddy"})
        self.assertIn("cond_already", r.headers["Location"])
        # a second member can add icy
        b, _, _ = member("Alex")
        self.assertEqual(b.post(f"/runs/{RUN_ID}/condition", {"kind": "icy"}).status, 303)
        both = page(Client("10.72.9.9"))
        self.assertIn("Muddy · 1", both.text)
        self.assertIn("Icy · 1", both.text)
        self.assertIn("Sign in to report", both.text)
        self.assertNotIn('action="/runs/n-006/condition"', both.text)
        # signed-out cannot post
        anon = Client("10.72.9.8")
        r = anon.post(f"/runs/{RUN_ID}/condition", {"kind": "closed"})
        self.assertEqual(r.status, 303)
        self.assertIn("signin", r.headers["Location"])
        self.assertEqual(C.live_conditions(RUN_ID)[[x["kind"] for x in C.live_conditions(RUN_ID)].index("closed")]["count"], 0)
        # fade
        A.q("UPDATE run_conditions SET expires_at=:t WHERE run_id=:r", t=C.now() - 10, r=RUN_ID)
        gone = page(Client("10.72.9.7"))
        self.assertNotIn("Muddy · 1", gone.text)
        self.assertNotIn("Icy · 1", gone.text)

    def test_condition_rate_limit_and_bad_kind(self):
        c, _, uid = member("Limiter")
        for i, kind in enumerate([k for k, _ in C.COND_KINDS]):
            self.assertEqual(C.add_condition(uid, RUN_ID, kind), "ok")
        # remaining kinds used; next any kind should hit daily cap (6 kinds < 8, so two more)
        self.assertEqual(C.add_condition(uid, "n-001", "muddy"), "ok")
        self.assertEqual(C.add_condition(uid, "n-002", "muddy"), "ok")
        self.assertEqual(C.add_condition(uid, "n-003", "muddy"), "limit")
        self.assertEqual(C.add_condition(uid, RUN_ID, "not-a-kind"), "bad")
        r = c.post(f"/runs/{RUN_ID}/condition", {"kind": "not-a-kind"})
        self.assertEqual(r.status, 303)
        self.assertIn("cond_slow", r.headers["Location"])


if __name__ == "__main__":
    unittest.main()
