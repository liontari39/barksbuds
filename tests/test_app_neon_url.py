"""Postgres URL parsing for Neon (and other hosted Postgres) connection strings.

Must sort after test_app.py. Does not connect to any database.
"""
import os, ssl, sys, tempfile, unittest

if "server" not in sys.modules:
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="bb-neon-url-"))
    os.environ.setdefault("EMAIL_PROVIDER", "file")
    os.environ.setdefault("ADMIN_KEY", "test-admin-key")
    os.environ.setdefault("SITE_URL", "")
    os.environ.setdefault("DATABASE_URL", "")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import server  # noqa: E402


NEON = ("postgresql://neondb_owner:p%40ss%2Fword@ep-xxx-123456.us-east-1.aws.neon.tech"
        "/neondb?sslmode=require&channel_binding=require")


class NeonUrlTests(unittest.TestCase):
    def test_typical_neon_url(self):
        p = server.pg_connect_params(NEON)
        self.assertEqual(p["user"], "neondb_owner")
        self.assertEqual(p["password"], "p@ss/word")  # unquoted
        self.assertEqual(p["host"], "ep-xxx-123456.us-east-1.aws.neon.tech")
        self.assertEqual(p["port"], 5432)
        self.assertEqual(p["database"], "neondb")
        self.assertEqual(p["timeout"], 15)
        self.assertIn("ssl_context", p)
        self.assertEqual(p["ssl_context"].check_hostname, False)
        self.assertEqual(p["ssl_context"].verify_mode, ssl.CERT_NONE)
        self.assertNotIn("channel_binding", p)
        # only known kwargs that pg8000.Connection accepts
        allowed = {"user", "password", "host", "port", "database", "timeout",
                   "ssl_context", "startup_params"}
        self.assertTrue(set(p) <= allowed)

    def test_unknown_query_params_are_ignored(self):
        url = "postgresql://u:p@localhost/db?sslmode=disable&channel_binding=require&foo=bar"
        p = server.pg_connect_params(url)
        self.assertNotIn("channel_binding", p)
        self.assertNotIn("foo", p)
        self.assertNotIn("ssl_context", p)

    def test_options_endpoint_fallback_is_forwarded(self):
        url = ("postgresql://u:p@ep-xxx-123456.us-east-1.aws.neon.tech/neondb"
               "?sslmode=require&options=endpoint%3Dep-xxx-123456")
        p = server.pg_connect_params(url)
        self.assertEqual(p["startup_params"], {"options": "endpoint=ep-xxx-123456"})
        self.assertIn("ssl_context", p)

    def test_ssl_default_for_remote_host_without_sslmode(self):
        p = server.pg_connect_params("postgresql://u:p@db.example.com/app")
        self.assertIn("ssl_context", p)

    def test_postgres_scheme_and_explicit_port(self):
        p = server.pg_connect_params("postgres://u:p@localhost:6543/app?sslmode=disable")
        self.assertEqual(p["port"], 6543)
        self.assertEqual(p["database"], "app")
        self.assertNotIn("ssl_context", p)


if __name__ == "__main__":
    unittest.main()
