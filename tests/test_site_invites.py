"""Per-partner invite links (?ref=) behind INVITES_ENABLED (default off), with additive-only sign-up attribution."""
import os, sys, unittest, uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in  # noqa: E402
import test_meetups as TM  # noqa: E402
import invites  # noqa: E402
import server  # noqa: E402

ON = {"INVITES_ENABLED": "1", "INVITE_PARTNERS": "petshop=Paws Pet Shop;vet-clinic=Main St Vet"}
ADMIN = {"X-Admin-Key": "test-admin-key"}


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def has_table():
    st = server.STORE
    if st.kind == "postgres":
        return bool(st.q("SELECT 1 FROM information_schema.tables WHERE table_name='signup_refs'"))
    return bool(st.q("SELECT name FROM sqlite_master WHERE type='table' AND name='signup_refs'"))


class InviteOffTests(unittest.TestCase):
    def test_off_by_default_does_nothing(self):
        with mock.patch.dict(os.environ, {"INVITES_ENABLED": "", "INVITE_PARTNERS": ON["INVITE_PARTNERS"]}):
            self.assertFalse(invites.enabled())
            c = Client()
            r = c.get("/?ref=petshop")
            self.assertEqual(r.status, 200)
            self.assertFalse(any(s.startswith("bb_ref=") for s in r.set_cookies))
            self.assertEqual(c.req("GET", "/admin/invites", headers=ADMIN).status, 404)
            self.assertEqual(invites.valid_ref("petshop"), "")
            self.assertEqual(invites.record_signup(1, "petshop.1"), "")


class InviteOnTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ON); self.env.start()
        self.assertTrue(invites.init_schema(server.STORE))
        self.assertTrue(has_table())

    def tearDown(self):
        self.env.stop()

    def test_unknown_or_bad_refs_ignored(self):
        c = Client()
        for ref in ("nobody", "BAD%20ref", "x" * 80, "..%2Fetc"):
            r = c.get("/dogs?ref=" + ref)
            self.assertFalse(any(s.startswith("bb_ref=") for s in r.set_cookies), ref)

    def test_attribution_new_account_only(self):
        c = Client(ip="10.9.0.1")
        r = c.get("/?ref=petshop")
        sc = [s for s in r.set_cookies if s.startswith("bb_ref=")]
        self.assertEqual(len(sc), 1)
        self.assertIn("HttpOnly", sc[0]); self.assertIn("SameSite=Lax", sc[0])
        r = c.get("/runs?ref=vet-clinic")  # first partner wins
        self.assertFalse(any(s.startswith("bb_ref=") for s in r.set_cookies))
        email = f"inv-{uuid.uuid4().hex[:8]}@example.com"
        sign_in(c, email)
        self.assertNotIn("bb_ref", c.cookies)  # cleared after sign-up
        uid = server.STORE.q("SELECT id FROM users WHERE email=:e", e=email)[0][0]
        row = server.STORE.q("SELECT ref, landed_at, created_at FROM signup_refs WHERE user_id=:u", u=uid)
        self.assertEqual(row[0][0], "petshop")
        self.assertTrue(row[0][1] and row[0][2] >= row[0][1])
        # an existing member who later follows a partner link is not attributed
        import accounts as A
        email2 = f"inv-old-{uuid.uuid4().hex[:8]}@example.com"
        uid2, new = A.get_or_create_user(email2)
        self.assertTrue(new)
        c3 = Client(ip="10.9.0.3")
        c3.get("/?ref=vet-clinic")
        sign_in(c3, email2)
        self.assertNotIn("bb_ref", c3.cookies)
        self.assertEqual(server.STORE.q("SELECT COUNT(*) FROM signup_refs WHERE user_id=:u", u=uid2)[0][0], 0)
        # admin counts: no emails
        r = Client().req("GET", "/admin/invites", headers=ADMIN)
        self.assertEqual(r.status, 200)
        self.assertIn('"petshop"', r.text); self.assertNotIn("@", r.text)
        self.assertGreaterEqual(invites.counts()["petshop"], 1)
        self.assertEqual(Client().req("GET", "/admin/invites").status, 404)  # needs the admin key

    def test_migration_is_additive_and_idempotent(self):
        self.assertTrue(invites.init_schema(server.STORE))  # re-run is safe
        import inspect
        src = inspect.getsource(invites)
        for bad in ("DROP ", "ALTER TABLE", "DELETE FROM", "UPDATE "):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
