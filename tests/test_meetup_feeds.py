"""Public and per-member private iCal feeds for upcoming meetups.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
import accounts as A  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402
from test_meetups import member, create, rsvp  # noqa: E402
from test_packs import make_pack  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def future(days=4, hhmm="10:00"):
    d = datetime.now(M.ET) + timedelta(days=days)
    return d.strftime("%Y-%m-%d"), hhmm


class MeetupFeedTests(unittest.TestCase):
    def test_public_feed_is_rfc5545_and_lists_public_meetups(self):
        host, _, uid, _ = member("feedpub")
        day, hhmm = future(5)
        title = f"Public Lily hang {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm, description="Bring water and a ball.")
        r = Client().get("/meetups/feed.ics")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.headers["Content-Type"].startswith("text/calendar"))
        body = r.text
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(body.endswith("END:VCALENDAR\r\n"))
        self.assertIn("\r\n", body)
        self.assertIn("VERSION:2.0", body)
        self.assertIn("PRODID:-//BarksBuds//Meetups//EN", body)
        self.assertIn(f"UID:meetup-{mid}@barksbuds.app", body)
        self.assertIn("DTSTAMP:", body)
        self.assertIn("DTSTART:", body)
        self.assertIn("DTEND:", body)
        self.assertIn(title, body)
        self.assertIn("X-WR-CALNAME:BarksBuds public meetups", body)
        # Subscribe links on the list and calendar pages
        lst = Client().get("/meetups").text
        self.assertIn('href="webcal://', lst)
        self.assertIn("/meetups/feed.ics", lst)
        self.assertIn("Add to your calendar", lst)
        cal = Client().get("/meetups/calendar").text
        self.assertIn("/meetups/feed.ics", cal)

    def test_pack_only_meetup_is_not_on_the_public_feed(self):
        host, _, uid, dogs = member("feedpack")
        pid, _ = make_pack(host, dogs, name=f"Feed pack {RUN}")
        day, hhmm = future(6)
        title = f"Pack only walk {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm, pack_id=str(pid), members_only="1")
        public = Client().get("/meetups/feed.ics").text
        self.assertNotIn(title, public)
        self.assertNotIn(f"UID:meetup-{mid}@", public)

    def test_private_feed_token_lifecycle_and_visibility(self):
        host, _, hid, hdogs = member("feedhost")
        guest, _, gid, gdogs = member("feedguest")
        stranger, _, sid, _ = member("feedstranger")
        day, hhmm = future(7)
        pub_title = f"Open park day {RUN}"
        pub_id, _ = create(host, title=pub_title, date=day, time=hhmm)
        pid, _ = make_pack(host, hdogs, name=f"Private feed pack {RUN}")
        pack_title = f"Pack romp {RUN}"
        pack_id, _ = create(host, title=pack_title, date=day, time="11:00", pack_id=str(pid), members_only="1")

        # Off by default
        self.assertEqual(M.cal_token_ver(gid), 0)
        self.assertIsNone(M.cal_feed_token(gid))
        me = guest.get("/me").text
        self.assertIn("Turn on private feed", me)
        self.assertNotIn("/meetups/feed.ics?u=", me)

        r = guest.post("/me/calendar-feed", {"action": "enable", "next": "/me#subscribe"})
        self.assertEqual(r.status, 303)
        self.assertIn("m=cal_on", r.headers["Location"])
        tok = M.cal_feed_token(gid)
        self.assertTrue(tok)
        self.assertEqual(len(tok), 32)

        # Invalid / missing token
        self.assertEqual(Client().get("/meetups/feed.ics?u=" + str(gid)).status, 404)
        self.assertEqual(Client().get(f"/meetups/feed.ics?u={gid}&t=nope").status, 404)
        self.assertEqual(Client().get(f"/meetups/feed.ics?u={sid}&t={tok}").status, 404)

        feed = Client().get(f"/meetups/feed.ics?u={gid}&t={tok}")
        self.assertEqual(feed.status, 200)
        self.assertTrue(feed.headers["Content-Type"].startswith("text/calendar"))
        body = feed.text
        self.assertIn(pub_title, body)
        # guest is not in the pack and has not RSVP'd, so pack-only stays off the feed
        self.assertNotIn(pack_title, body)

        rsvp(guest, pub_id, gdogs)
        # RSVP'd meetup stays on the feed (already public). Now RSVP can't get them into pack-only.
        host_tok_enable = host.post("/me/calendar-feed", {"action": "enable"})
        self.assertEqual(host_tok_enable.status, 303)
        htok = M.cal_feed_token(hid)
        host_feed = Client().get(f"/meetups/feed.ics?u={hid}&t={htok}").text
        self.assertIn(pack_title, host_feed)
        self.assertIn(pub_title, host_feed)

        # After guest RSVPs they still shouldn't see pack-only. Confirm host's pack meetup is host-visible only here.
        guest_feed = Client().get(f"/meetups/feed.ics?u={gid}&t={tok}").text
        self.assertNotIn(pack_title, guest_feed)

        # Rotate: old token dies, new one works
        old = tok
        r = guest.post("/me/calendar-feed", {"action": "regenerate", "next": "/me#subscribe"})
        self.assertEqual(r.status, 303)
        self.assertIn("m=cal_new", r.headers["Location"])
        new = M.cal_feed_token(gid)
        self.assertNotEqual(new, old)
        self.assertEqual(Client().get(f"/meetups/feed.ics?u={gid}&t={old}").status, 404)
        self.assertEqual(Client().get(f"/meetups/feed.ics?u={gid}&t={new}").status, 200)

        # Revoke
        r = guest.post("/me/calendar-feed", {"action": "revoke", "next": "/me#subscribe"})
        self.assertEqual(r.status, 303)
        self.assertIn("m=cal_off", r.headers["Location"])
        self.assertEqual(M.cal_token_ver(gid), 0)
        self.assertEqual(Client().get(f"/meetups/feed.ics?u={gid}&t={new}").status, 404)

    def test_feed_hides_host_surnames_and_folds_long_lines(self):
        host, _, hid, _ = member("alexr")
        guest, _, gid, _ = member("feedrsvp")
        A.update_profile(hid, "Alex Rivera", "Nassau", "Manhasset", "")
        name = A.one("SELECT display_name FROM users WHERE id=:i", i=hid)[0]
        self.assertIn("Rivera", name)
        day, hhmm = future(8)
        title = f"Intro walk {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm)
        M.enable_cal_feed(gid)
        tok = M.cal_feed_token(gid)
        body = Client().get(f"/meetups/feed.ics?u={gid}&t={tok}").text
        self.assertIn(title, body)
        self.assertIn("Hosted by Alex on BarksBuds", body)
        self.assertNotIn("Rivera", body)
        one = Client().get(f"/meetups/{mid}.ics").text
        self.assertIn("Hosted by Alex on BarksBuds", one)
        self.assertNotIn("Rivera", one)

        long_desc = "Water " * 40
        create(host, title=f"Long desc hang {RUN}", date=day, time="13:00", description=long_desc)
        ics = Client().get("/meetups/feed.ics").text
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line[:80])

    def test_csrf_required_to_manage_feed(self):
        guest, _, gid, _ = member("feedcsrf")
        r = guest.post("/me/calendar-feed", {"action": "enable"}, csrf=False)
        self.assertEqual(r.status, 403)
        self.assertEqual(M.cal_token_ver(gid), 0)
