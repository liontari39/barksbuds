"""Admin maintenance endpoints: stats, logical backup, cleanup of expired sessions/login links."""
import gzip, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_meetups as TM  # noqa: E402
from test_app import Client  # noqa: E402
import accounts as A  # noqa: E402

KEY = {"X-Admin-Key": "test-admin-key"}


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


class MaintTests(unittest.TestCase):
    def test_requires_header_key(self):
        c = Client("10.13.0.1")
        self.assertEqual(c.req("GET", "/admin/maint/stats").status, 404)
        self.assertEqual(c.req("GET", "/admin/maint/stats?key=test-admin-key").status, 404)
        self.assertEqual(c.req("GET", "/admin/maint/backup", headers={"X-Admin-Key": "nope"}).status, 404)
        self.assertEqual(c.req("POST", "/admin/maint/cleanup?dry_run=0").status, 404)

    def test_stats_backup_cleanup(self):
        TM.member("mnt")
        c = Client("10.13.0.2")
        r = c.req("GET", "/admin/maint/stats", headers=KEY)
        self.assertEqual(r.status, 200)
        s = json.loads(r.text)
        self.assertIn("sessions_expired", s["hygiene"])
        self.assertTrue(any(t["table"] == "dogs" for t in s["tables"]))
        r = c.req("GET", "/admin/maint/backup", headers=KEY)
        self.assertEqual(r.status, 200)
        lines = [json.loads(x) for x in gzip.decompress(r.body).decode().splitlines()]
        self.assertTrue(lines[-1].get("end"))
        ends = {x["table_end"]: x["rows"] for x in lines if "table_end" in x}
        self.assertGreaterEqual(ends.get("users", 0), 1)
        # an expired session is counted, kept on dry run, removed on a real run; live sessions survive
        A.STORE.q("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen) VALUES('maint-old',1,1,2,1)")
        live = int(A.STORE.q("SELECT COUNT(*) FROM sessions WHERE expires_at>=:t", t=A.now())[0][0])
        d = json.loads(c.req("POST", "/admin/maint/cleanup", headers=KEY).text)
        self.assertTrue(d["dry_run"]); self.assertGreaterEqual(d["after"]["sessions_expired"], 1)
        d = json.loads(c.req("POST", "/admin/maint/cleanup?dry_run=0", headers=KEY).text)
        self.assertFalse(d["dry_run"]); self.assertEqual(d["after"]["sessions_expired"], 0)
        self.assertEqual(int(A.STORE.q("SELECT COUNT(*) FROM sessions WHERE expires_at>=:t", t=A.now())[0][0]), live)


if __name__ == "__main__":
    unittest.main()
