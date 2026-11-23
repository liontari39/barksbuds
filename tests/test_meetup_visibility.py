"""Private (invite-only) and members-only meetup visibility.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402
from test_meetups import member, create, rsvp  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def future(days=5, hhmm="10:00"):
    d = datetime.now(M.ET) + timedelta(days=days)
    return d.strftime("%Y-%m-%d"), hhmm


class MeetupVisibilityTests(unittest.TestCase):
    def test_form_offers_four_visibility_choices(self):
        host, _, _, _ = member("visform")
        page = host.get("/meetups/new").text
        self.assertIn("Who can see this", page)
        for val in ("public", "members", "pack", "private"):
            self.assertIn(f'name="visibility" value="{val}"', page)

    def test_private_meetup_hidden_except_host_and_invite_link(self):
        host, _, hid, hdogs = member("vishost")
        guest, _, gid, gdogs = member("visguest")
        stranger, _, sid, _ = member("visstranger")
        day, hhmm = future()
        title = f"Secret Lily hang {RUN}"
        mid, loc = create(host, title=title, date=day, time=hhmm, visibility="private")
        m = M.get(mid)
        self.assertEqual(M.visibility(m), "private")
        tok = M.invite_token(m)
        self.assertTrue(tok)
        path = meetweb.meetup_path(m)
        secret = f"{path}?k={tok}"

        # Hidden from public lists, calendar, sitemap, search, public feed, API
        self.assertNotIn(title, Client().get("/meetups").text)
        now = M.to_et(m["starts_at"])
        self.assertNotIn(title, Client().get(f"/meetups/calendar?y={now.year}&m={now.month}").text)
        sm = Client().get("/sitemap.xml").text
        self.assertNotIn(path, sm)
        self.assertNotIn(path, Client().get("/search?q=" + title.replace(" ", "+") + "&frag=1").text)
        self.assertNotIn(title, Client().get("/meetups/feed.ics").text)
        api = Client().get("/api/meetups").text
        self.assertNotIn(title, api)
        # Host still sees it on the list and dashboard
        self.assertIn(title, host.get("/meetups").text)
        self.assertIn(title, host.get("/me").text)

        # Direct URL is 404 without the token
        self.assertEqual(Client().get(path).status, 404)
        self.assertEqual(stranger.get(path).status, 404)
        self.assertEqual(Client().get(f"/meetups/{mid}.ics").status, 404)

        # Signed-out visitor with the secret link is sent to sign in
        r = Client().get(secret)
        self.assertEqual(r.status, 303)
        self.assertIn("/signin", r.headers["Location"])
        self.assertTrue("k=" in r.headers["Location"] or "k%3D" in r.headers["Location"])

        # Guest opens the secret link, gets invited, then can use the regular URL
        r = guest.get(secret)
        self.assertEqual(r.status, 303)
        self.assertIn("m=invited", r.headers["Location"])
        self.assertTrue(M.is_invited(mid, gid))
        page = guest.get(path)
        self.assertEqual(page.status, 200)
        self.assertIn(title, page.text)
        self.assertIn('name="robots" content="noindex"', page.text)
        self.assertEqual(page.headers.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertIn(title, guest.get("/meetups").text)
        self.assertNotIn(title, stranger.get("/meetups").text)

        # ICS for invited member; still 404 for a stranger
        self.assertEqual(guest.get(f"/meetups/{mid}.ics").status, 200)
        self.assertEqual(stranger.get(f"/meetups/{mid}.ics").status, 404)

        # Private feed includes it for host and invitee, not for a stranger
        M.enable_cal_feed(hid); M.enable_cal_feed(gid); M.enable_cal_feed(sid)
        self.assertIn(title, Client().get(f"/meetups/feed.ics?u={hid}&t={M.cal_feed_token(hid)}").text)
        self.assertIn(title, Client().get(f"/meetups/feed.ics?u={gid}&t={M.cal_feed_token(gid)}").text)
        self.assertNotIn(title, Client().get(f"/meetups/feed.ics?u={sid}&t={M.cal_feed_token(sid)}").text)

        # Rotate the link: new visitors 404, already-invited guest still has access
        r = host.post(f"/meetups/{mid}/invite-link", {})
        self.assertEqual(r.status, 303)
        self.assertIn("m=invite_new", r.headers["Location"])
        new = M.invite_token(M.get(mid))
        self.assertNotEqual(new, tok)
        self.assertEqual(stranger.get(f"{path}?k={tok}").status, 404)
        self.assertEqual(guest.get(path).status, 200)

        # Guest can RSVP after being invited
        r = rsvp(guest, mid, gdogs)
        self.assertEqual(r.status, 303)

    def test_members_only_is_listed_for_signed_in_members(self):
        host, _, _, _ = member("vismemhost")
        guest, _, _, _ = member("vismemguest")
        day, hhmm = future(6)
        title = f"Members Lily walk {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm, visibility="members")
        m = M.get(mid)
        path = meetweb.meetup_path(m)
        self.assertEqual(M.visibility(m), "members")
        self.assertNotIn(title, Client().get("/meetups").text)
        self.assertNotIn(path, Client().get("/sitemap.xml").text)
        self.assertNotIn(title, Client().get("/meetups/feed.ics").text)
        self.assertIn(title, guest.get("/meetups").text)
        # signed-out visitors are asked to sign in rather than seeing a 404
        r = Client().get(path)
        self.assertEqual(r.status, 303)
        self.assertIn("/signin", r.headers["Location"])
        self.assertEqual(guest.get(path).status, 200)
        self.assertIn('name="robots" content="noindex"', guest.get(path).text)

    def test_public_meetup_still_indexable_and_listed(self):
        host, _, _, _ = member("vispub")
        day, hhmm = future(7)
        title = f"Open Lily romp {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm, visibility="public")
        m = M.get(mid)
        path = meetweb.meetup_path(m)
        page = Client().get(path)
        self.assertEqual(page.status, 200)
        self.assertIn('name="robots" content="index,follow"', page.text)
        self.assertNotIn("X-Robots-Tag", page.headers)
        self.assertIn(title, Client().get("/meetups").text)
        self.assertIn(path, Client().get("/sitemap.xml").text)
