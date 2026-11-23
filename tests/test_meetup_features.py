"""Weekly meetup series, morning-of reminders, and RSVP/host chat visibility."""
import os, re, sys, time, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
import accounts as A  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402
import messages as MS  # noqa: E402
from test_meetups import create, future, member, mpage, rsvp, mark, wait_mail, outbox  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def edit(c, mid, **over):
    m = M.get(mid)
    s = M.to_et(m["starts_at"])
    data = {"title": m["title"], "date": s.strftime("%Y-%m-%d"), "time": s.strftime("%H:%M"),
            "duration": str(m["duration_min"]), "loc": "run" if m["run_id"] else "custom",
            "run_id": m["run_id"] or "", "description": m["description"] or "", "scope": "one"}
    data.update(over)
    r = c.post(f"/meetups/{mid}/edit", data)
    assert r.status == 303, (r.status, r.text[:800])
    return r


class MeetupFeatureTests(unittest.TestCase):
    def test_weekly_series_counts_as_one_and_edits_or_cancels_by_scope(self):
        host, _, hid, _ = member("ser")
        page = host.get("/meetups/new")
        self.assertIn("Repeat weekly", page.text)
        mid, _ = create(host, title="Sunday series", weekly="1")
        rows = A.q("SELECT id, starts_at, series_id, title, status FROM meetups WHERE series_id=:s ORDER BY starts_at", s=mid)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r[2] == mid for r in rows))
        days = [M.to_et(r[1]).date() for r in rows]
        for i in range(1, 8):
            self.assertEqual(days[i] - days[i - 1], timedelta(days=7))
        # Creating the series used one slot of the new-account daily cap, not eight.
        mid2, _ = create(host, title="One-off romp")
        d, t = future()
        r = host.post("/meetups/new", {"title": "Too many", "date": d, "time": t, "duration": "60",
                                      "loc": "run", "run_id": "n-006"})
        self.assertEqual(r.status, 429)

        # This date only
        edit(host, mid, title="Sunday series (moved)", scope="one")
        titles = [M.get(r[0])["title"] for r in rows]
        self.assertEqual(titles[0], "Sunday series (moved)")
        self.assertTrue(all(t == "Sunday series" for t in titles[1:]))

        # This and future dates, starting at the second occurrence
        second = rows[1][0]
        edit(host, second, title="Sunday pack walk", scope="series")
        self.assertEqual(M.get(mid)["title"], "Sunday series (moved)")
        self.assertTrue(all(M.get(r[0])["title"] == "Sunday pack walk" for r in rows[1:]))

        # Cancel one date
        third = rows[2][0]
        r = host.post(f"/meetups/{third}/cancel", {"scope": "one"})
        self.assertEqual(r.status, 303)
        self.assertEqual(M.get(third)["status"], "cancelled")
        self.assertEqual(M.get(rows[3][0])["status"], "active")

        # Cancel this and future
        fourth = rows[3][0]
        r = host.post(f"/meetups/{fourth}/cancel", {"scope": "series"})
        self.assertEqual(r.status, 303)
        self.assertIn("m_cancelled_series", r.headers["Location"])
        for r in rows[3:]:
            self.assertEqual(M.get(r[0])["status"], "cancelled")
        self.assertEqual(M.get(rows[1][0])["status"], "active")


    def test_repeat_next_week_still_copies_a_one_off(self):
        host, _, hid, _ = member("repwk")
        A.q("UPDATE users SET created_at=:t WHERE id=:i", t=A.now() - 8 * 86400, i=hid)
        mid, _ = create(host, title="One week only")
        r = host.post(f"/meetups/{mid}/repeat", {})
        self.assertEqual(r.status, 303)
        nid = int(re.match(r"/meetups/(\d+)/edit", r.headers["Location"]).group(1))
        self.assertIsNone(M.get(nid)["series_id"])
        self.assertEqual(M.to_et(M.get(nid)["starts_at"]).date(), M.to_et(M.get(mid)["starts_at"]).date() + timedelta(days=7))

    def test_morning_of_reminder_sends_once_over_existing_paths(self):
        host, _, hid, _ = member("morn")
        a, aemail, aid, adogs = member("morni")
        mid, _ = create(host)
        rsvp(a, mid, adogs)
        fixed = int(datetime(2026, 11, 24, 8, 0, tzinfo=M.ET).timestamp())
        starts = int(datetime(2026, 11, 24, 10, 0, tzinfo=M.ET).timestamp())
        A.q("UPDATE meetups SET starts_at=:s, reminder_sent_at=:r, morning_reminder_sent_at=NULL WHERE id=:i",
            s=starts, r=fixed, i=mid)
        real = A.now
        A.now = lambda: fixed
        try:
            t0 = mark()
            r = Client().req("POST", "/admin/meetups/reminders", "",
                             {"X-Admin-Key": "test-admin-key", "Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(r.status, 200)
            self.assertGreaterEqual(r.text and __import__("json").loads(r.text).get("meetups", 0), 1)
            wait_mail("meetup-reminder", aemail, t0)
            self.assertIsNotNone(M.get(mid)["morning_reminder_sent_at"])
            r = Client().post("/admin/meetups/reminders", {"key": "test-admin-key"}, csrf=False)
            time.sleep(0.3)
            self.assertEqual(len(outbox("meetup-reminder", aemail, t0)), 1)
        finally:
            A.now = real

    def test_chat_is_for_rsvp_and_host_and_respects_blocks(self):
        host, _, hid, _ = member("chat")
        going, _, gid, gdogs = member("goer", dogs=2)
        wait, _, wid, wdogs = member("wait")
        stranger, *_ = member("nosy")
        mid, _ = create(host, title="Chat romp", capacity="2")
        rsvp(going, mid, gdogs)  # fills the 2-dog cap
        rsvp(wait, mid, wdogs)  # waitlist
        # Host can open the chat form; a stranger only sees a count.
        page = mpage(host, mid).text
        self.assertIn("Meetup chat", page)
        self.assertIn("Post to the chat", page)
        r = going.post(f"/meetups/{mid}/comments", {"body": "See you at the gate"})
        self.assertEqual(r.status, 303)
        self.assertIn("See you at the gate", mpage(going, mid).text)
        self.assertIn("See you at the gate", mpage(host, mid).text)
        # Waitlisted members can read and post.
        self.assertIn("See you at the gate", mpage(wait, mid).text)
        r = wait.post(f"/meetups/{mid}/comments", {"body": "We'll be a little late"})
        self.assertEqual(r.status, 303)
        # Signed-in strangers (no RSVP) cannot read comment bodies.
        nosy = mpage(stranger, mid).text
        self.assertNotIn("See you at the gate", nosy)
        self.assertNotIn("We'll be a little late", nosy)
        self.assertIn("RSVP to read the chat", nosy)
        r = stranger.post(f"/meetups/{mid}/comments", {"body": "sneak"})
        self.assertIn("e=rsvpfirst", r.headers["Location"])

        # Blocks hide comments both ways and stop posting if the host is involved.
        MS.block(gid, wid)
        self.assertNotIn("We'll be a little late", mpage(going, mid).text)
        self.assertNotIn("See you at the gate", mpage(wait, mid).text)
        MS.block(hid, gid)
        r = going.post(f"/meetups/{mid}/comments", {"body": "still here"})
        self.assertIn("e=blocked", r.headers["Location"])

        self.assertEqual(A.cap(gid, "comments_day"), 10)
        A.q("UPDATE users SET created_at=:t WHERE id=:i", t=A.now() - 8 * 86400, i=gid)
        self.assertEqual(A.cap(gid, "comments_day"), 30)
