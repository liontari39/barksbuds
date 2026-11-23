"""Growth tools: QR flyers, share previews for runs/meetups (not private), member invite links."""
import os, re, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402
import accounts as A  # noqa: E402
import growth  # noqa: E402
import meetups as M  # noqa: E402
from test_meetups import create, member  # noqa: E402

RUN_ID = "n-006"


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def follow(c, path):
    r = c.get(path)
    if r.status in (301, 302, 303):
        r = c.get(r.headers["Location"])
    return r


class GrowthTests(unittest.TestCase):
    def test_run_flyer_and_og_image(self):
        r = follow(Client("10.81.0.1"), f"/runs/{RUN_ID}")
        self.assertEqual(r.status, 200)
        self.assertIn(f"/runs/{RUN_ID}/flyer", r.text)
        self.assertIn(f"/runs/{RUN_ID}/og.png", r.text)
        self.assertIn('property="og:image"', r.text)
        self.assertIn('name="twitter:card" content="summary_large_image"', r.text)
        self.assertIn('name="twitter:image"', r.text)

        flyer = Client("10.81.0.2").get(f"/runs/{RUN_ID}/flyer")
        self.assertEqual(flyer.status, 200)
        self.assertIn("Print flyer", flyer.text)
        self.assertIn("noindex", flyer.text)
        self.assertIn("<svg", flyer.text)
        self.assertIn("Christopher Morley", flyer.text)
        self.assertIn("BarksBuds", flyer.text)

        og = Client("10.81.0.3").get(f"/runs/{RUN_ID}/og.png")
        self.assertEqual(og.status, 200)
        self.assertIn("image/png", og.headers.get("Content-Type", ""))
        self.assertTrue(og.body.startswith(b"\x89PNG"))

    def test_meetup_og_public_only(self):
        host, _, _, _ = member("oghost")
        mid, _ = create(host, title="Public share romp")
        og = Client("10.81.1.1").get(f"/meetups/{mid}/og.png")
        self.assertEqual(og.status, 200)
        self.assertTrue(og.body.startswith(b"\x89PNG"))
        page = follow(Client("10.81.1.2"), f"/meetups/{mid}")
        self.assertIn(f"/meetups/{mid}/og.png", page.text)
        self.assertIn('name="twitter:image"', page.text)

        pmid, _ = create(host, title="Invite only romp", visibility="private")
        pog = Client("10.81.1.3").get(f"/meetups/{pmid}/og.png")
        self.assertEqual(pog.status, 404)
        ppage = follow(host, f"/meetups/{pmid}")
        self.assertEqual(ppage.status, 200)
        self.assertNotIn(f"/meetups/{pmid}/og.png", ppage.text)
        self.assertNotIn('property="og:image"', ppage.text)

    def test_member_invite_counts_new_signups_only(self):
        inviter = Client("10.81.2.1")
        inv_email = f"inviter-{RUN}@example.com"
        sign_in(inviter, inv_email)
        inviter.post("/me/profile", {"display_name": "Ivy", "area": "Nassau", "town": "Roslyn", "bio": ""})
        uid = A.one("SELECT id FROM users WHERE email=:e", e=inv_email)[0]
        me = inviter.get("/me")
        token = growth.invite_token(uid)
        self.assertIn("/join/" + token, me.text)
        self.assertIn("No one has joined with your link yet.", me.text)

        guest = Client("10.81.2.2")
        r = guest.get("/join/" + token)
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"], "/")
        self.assertIn("bb_inv", guest.cookies)
        self.assertEqual(guest.cookies["bb_inv"], token)
        guest_email = f"newbie-{RUN}@example.com"
        sign_in(guest, guest_email)
        self.assertEqual(growth.signup_count(uid), 1)
        me2 = inviter.get("/me")
        self.assertIn("1 person has joined with your link.", me2.text)
        self.assertNotIn(guest_email, me2.text)

        # Existing member who follows the link is not counted.
        existing = Client("10.81.2.3")
        exist_email = f"already-{RUN}@example.com"
        sign_in(existing, exist_email)
        existing.get("/join/" + token)
        A.q("UPDATE login_tokens SET created_at=created_at-60 WHERE email=:e", e=exist_email)
        sign_in(existing, exist_email)
        self.assertEqual(growth.signup_count(uid), 1)

        # Bad token sets no cookie.
        bad = Client("10.81.2.4")
        b = bad.get(f"/join/{uid}-aaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(b.status, 303)
        self.assertNotIn("bb_inv", bad.cookies)

        # ?inv= also remembers the inviter for a new signup.
        via_q = Client("10.81.2.5")
        r = via_q.get("/runs?inv=" + token)
        self.assertEqual(r.status, 200)
        self.assertEqual(via_q.cookies.get("bb_inv"), token)
        sign_in(via_q, f"viaq-{RUN}@example.com")
        self.assertEqual(growth.signup_count(uid), 2)
        me3 = inviter.get("/me")
        self.assertIn("2 people have joined with your link.", me3.text)
