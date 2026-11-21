"""Admin maintenance endpoints: stats, logical backup, cleanup of expired sessions/login links."""
import gzip, json, os, sys, unittest
from pathlib import Path

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

    def test_pixel_pals_canonical_not_doubled(self):
        import re
        t = Client("10.13.0.3").get("/pixel-pals").text
        m = re.search(r'<link rel="canonical" href="([^"]+)"', t)
        self.assertTrue(m and m.group(1).endswith("/pixel-pals"))
        self.assertEqual(m.group(1).count("://"), 1)

    def test_restore_backup_roundtrip(self):
        """Backup the test store and restore it into a throwaway SQLite dir via the CLI."""
        import io, subprocess, tempfile
        import maintweb
        TM.member("rst")
        buf = io.BytesIO()
        maintweb.write_backup(buf)
        raw = buf.getvalue()
        src = Path(tempfile.mkstemp(suffix=".ndjson.gz")[1])
        src.write_bytes(raw)
        dest = tempfile.mkdtemp(prefix="bb-restore-test-")
        env = os.environ.copy()
        for k in ("DATABASE_URL", "TEST_DATABASE_URL"):
            env.pop(k, None)
        env["EMAIL_PROVIDER"] = "file"
        env["ADMIN_KEY"] = "restore-test"
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "restore_backup.py")
        r = subprocess.run(
            [sys.executable, script, "--data-dir", dest, str(src)],
            cwd=os.path.dirname(script) and os.path.dirname(os.path.dirname(script)),
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr or r.stdout)
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["tables"].get("users", 0), 1)
        # counts in the dest file match the backup's table_end records
        lines = [json.loads(x) for x in gzip.decompress(raw).decode().splitlines()]
        expected = {x["table_end"]: x["rows"] for x in lines if "table_end" in x}
        import sqlite3
        con = sqlite3.connect(os.path.join(dest, "waitlist.db"))
        try:
            for table, n in expected.items():
                got = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                self.assertEqual(got, n, f"{table}: restored {got}, backup said {n}")
        finally:
            con.close()
        src.unlink(missing_ok=True)

    def test_security_headers(self):
        h = Client("10.13.0.4").get("/").headers
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(h.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(h.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(h.get("Strict-Transport-Security"), "max-age=31536000")

    def test_restore_refuses_nonempty_without_replace(self):
        import io, maintweb
        buf = io.BytesIO()
        maintweb.write_backup(buf)
        buf.seek(0)
        with self.assertRaises(RuntimeError) as cm:
            maintweb.restore_backup(buf, store=A.STORE, replace=False)
        self.assertIn("already has rows", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
