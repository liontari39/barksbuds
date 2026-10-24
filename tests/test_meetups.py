"""Meetups: create/edit/cancel, RSVP + capacity/waitlist, permissions, comments, reports, emails, reminders.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
Reuses the server/client helpers from test_app (same process, same temp data dir and outbox).
"""
import glob, json, os, re, sys, time, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, RUN  # noqa: E402
import accounts as A  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False  # reminders are exercised explicitly through the admin endpoint
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def future(days=3, hhmm="10:00"):
    d = (datetime.now(M.ET) + timedelta(days=days)).strftime("%Y-%m-%d")
    return d, hhmm


def mark():
    """Snapshot of the outbox; later checks only look at emails written after it."""
    return set(glob.glob(os.path.join(T.TMP, "outbox", "*.json")))


def outbox(tag, to=None, since=frozenset()):
    out = []
    for fn in glob.glob(os.path.join(T.TMP, "outbox", f"*-{tag}-*.json")):
        if fn not in since:
            d = json.load(open(fn))
            if to is None or d["to"] == to:
                out.append(d)
    return out


def wait_mail(tag, to, since, n=1):
    for _ in range(60):
        got = outbox(tag, to, since)
        if len(got) >= n:
            return got
        time.sleep(0.1)
    raise AssertionError(f"no {tag} email for {to}")


_n = [0]


def member(name="m", dogs=1):
    _n[0] += 1
    c = Client(f"10.9.{_n[0] // 200}.{_n[0] % 200 + 1}")
    email = f"{name}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    c.post("/me/profile", {"display_name": name.title(), "area": "Nassau", "town": "Manhasset", "bio": ""})
    ids = [new_dog(c, f"{name.title()}dog{i}") for i in range(dogs)]
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid, ids


def create(c, **over):
    d, t = future()
    data = {"title": "Morning romp", "date": d, "time": t, "duration": "60", "loc": "run", "run_id": "n-006",
            "description": "Bring water.", "fit": "", "capacity": ""}
    data.update(over)
    r = c.post("/meetups/new", data)
    assert r.status == 303, (r.status, r.text[:800])
    return int(re.match(r"/meetups/(\d+)", r.headers["Location"]).group(1)), r


def mpage(c, mid):
    return c.get(meetweb.meetup_path(M.get(mid)))


def rsvp(c, mid, dogs, status="going"):
    return c.post(f"/meetups/{mid}/rsvp", {"status": status, "dogs": [str(x) for x in dogs]})


class MeetupTests(unittest.TestCase):
    def test_create_page_ics_and_listing(self):
        host, _, hid, _ = member("host")
        self.assertEqual(Client("10.8.0.1").get("/meetups/new").status, 303)  # sign-in required
        self.assertEqual(host.get("/meetups/new?run=n-006").status, 200)
        mid, r = create(host, title="Romp <script>x</script>", capacity="5", fit="small")
        m = M.get(mid)
        self.assertEqual(m["run_id"], "n-006")
        self.assertEqual(m["place_name"], "Christopher Morley Park Dog Run")
        self.assertAlmostEqual(m["lat"], 40.786059, places=4)
        self.assertEqual(M.to_et(m["starts_at"]).strftime("%H:%M"), "10:00")
        page = Client("10.8.0.2").get(r.headers["Location"].split("?")[0])
        self.assertEqual(page.status, 200)
        self.assertNotIn("<script>x</script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        self.assertIn('property="og:title"', page.text)
        self.assertIn("calendar.google.com", page.text)
        self.assertIn("destination=40.786059", page.text.replace("%2C", ","))
        self.assertIn(" ET", page.text)
        ics = Client().get(f"/meetups/{mid}.ics")
        self.assertEqual(ics.status, 200)
        self.assertTrue(ics.headers["Content-Type"].startswith("text/calendar"))
        self.assertIn("BEGIN:VEVENT", ics.text)
        self.assertIn("\r\n", ics.text)
        self.assertIn("DTSTART:", ics.text)
        lst = Client().get("/meetups?region=li").text
        self.assertIn(f"/meetups/{mid}-", lst)
        self.assertNotIn(f"/meetups/{mid}-", Client().get("/meetups?area=Queens").text)
        self.assertIn(f"/meetups/{mid}-", Client().get("/meetups?ns=1").text)
        api = json.loads(Client().get("/api/meetups").text)
        self.assertTrue(any(x["id"] == mid for x in api["runs"]["n-006"]))
        self.assertIn('href="/meetups"', Client().get("/").text)
        self.assertNotIn("{{NORTH_SHORE}}", Client().get("/").text)

    def test_validation_and_custom_place(self):
        host, *_ = member("val")
        r = host.post("/meetups/new", {"title": "x", "date": "2020-01-01", "time": "10:00", "duration": "60",
                                        "loc": "custom", "place_name": "", "address": "", "area": ""})
        self.assertEqual(r.status, 400)
        self.assertIn("in the future", r.text)
        mid, _ = create(host, loc="custom", run_id="", place_name="Plandome Field", address="1 Main St, Manhasset, NY",
                        area="Nassau", town="Manhasset")
        m = M.get(mid)
        self.assertEqual((m["run_id"], m["lat"], m["area"]), ("", None, "Nassau"))

    def test_permissions(self):
        host, _, hid, _ = member("own")
        other, *_ = member("other")
        mid, _ = create(host)
        self.assertEqual(other.get(f"/meetups/{mid}/edit").status, 403)
        r = other.post(f"/meetups/{mid}/edit", {"title": "Hijack", "date": future()[0], "time": "11:00", "duration": "60",
                                                "loc": "run", "run_id": "n-006"})
        self.assertEqual(r.status, 403)
        self.assertEqual(other.post(f"/meetups/{mid}/cancel", {}).status, 403)
        self.assertEqual(M.get(mid)["title"], "Morning romp")
        self.assertEqual(M.get(mid)["status"], "active")
        # CSRF required
        r = host.post(f"/meetups/{mid}/cancel", {}, csrf=False)
        self.assertEqual(r.status, 403)
        # host can edit
        r = host.post(f"/meetups/{mid}/edit", {"title": "Later romp", "date": future(4)[0], "time": "11:30", "duration": "90",
                                               "loc": "run", "run_id": "n-006"})
        self.assertEqual(r.status, 303)
        self.assertEqual(M.get(mid)["title"], "Later romp")
        # anonymous RSVP needs sign-in
        r = Client("10.8.0.3").post(f"/meetups/{mid}/rsvp", {"dogs": ["1"]}, csrf=False)
        self.assertEqual((r.status, r.headers["Location"].split("?")[0]), (303, "/signin"))

    def test_rsvp_capacity_waitlist_and_promotion(self):
        t0 = mark()
        host, hemail, hid, hdogs = member("cap")
        a, aemail, aid, adogs = member("ann", dogs=2)
        b, bemail, bid, bdogs = member("bob")
        cc, cemail, cid, cdogs = member("cat")
        mid, _ = create(host, capacity="3")
        # can't RSVP with someone else's dog
        r = rsvp(a, mid, bdogs)
        self.assertIn("e=nodogs", r.headers["Location"])
        self.assertIsNone(M.rsvp_of(mid, aid))
        self.assertIn("m=going", rsvp(a, mid, adogs).headers["Location"])   # 2 of 3
        self.assertIn("m=going", rsvp(b, mid, bdogs).headers["Location"])   # 3 of 3
        self.assertIn("m=waitlist", rsvp(cc, mid, cdogs).headers["Location"])  # full -> waitlist
        self.assertEqual(M.spots_left(M.get(mid)), 0)
        page = mpage(Client(), mid).text
        self.assertIn("3 dogs going", page)
        self.assertIn("Anndog0", page)
        self.assertIn("/dogs/", page)
        # confirmations + host notice
        wait_mail("meetup-confirm", aemail, t0)
        wait_mail("meetup-confirm", cemail, t0)
        hn = wait_mail("meetup-host", hemail, t0, n=3)
        self.assertTrue(any("Ann" in d["text"] for d in hn))
        conf = outbox("meetup-confirm", aemail, t0)[0]
        self.assertIn("/emails/meetups?u=", conf["text"])
        self.assertIn("List-Unsubscribe", conf["headers"])
        self.assertNotIn("Jack", conf["text"])
        self.assertIn("Morning romp", conf["subject"] + conf["text"])
        # going member can't add more dogs past capacity
        b2 = new_dog(b, "Bobdog2")
        r = rsvp(b, mid, bdogs + [b2])
        self.assertIn("e=full", r.headers["Location"])
        self.assertEqual(M.rsvp_of(mid, bid)["status"], "going")
        # maybe doesn't use capacity
        d, *_ = member("dee")
        self.assertIn("m=maybe", rsvp(d, mid, [new_dog(d, "Deedog")], "maybe").headers["Location"])
        # Bob cancels -> Cat promoted from the waitlist and emailed
        t1 = mark()
        r = b.post(f"/meetups/{mid}/rsvp/cancel", {})
        self.assertIn("rsvp_cancelled", r.headers["Location"])
        self.assertIsNone(M.rsvp_of(mid, bid))
        self.assertEqual(M.rsvp_of(mid, cid)["status"], "going")
        wait_mail("meetup-promoted", cemail, t1)

    def test_cancel_meetup_notifies_attendees(self):
        host, hemail, hid, _ = member("can")
        a, aemail, aid, adogs = member("att")
        mid, _ = create(host)
        rsvp(a, mid, adogs)
        t0 = mark()
        r = host.post(f"/meetups/{mid}/cancel", {})
        self.assertEqual(r.status, 303)
        self.assertEqual(M.get(mid)["status"], "cancelled")
        msg = wait_mail("meetup-cancel", aemail, t0)[0]
        self.assertIn("cancel", msg["subject"].lower())
        self.assertNotIn(f"/meetups/{mid}-", Client().get("/meetups").text)
        self.assertIn("cancelled", mpage(Client(), mid).text.lower())
        self.assertIn("e=closed", rsvp(a, mid, adogs).headers["Location"])
        # repeat next week creates a fresh meetup 7 days later
        r = host.post(f"/meetups/{mid}/repeat", {})
        nid = int(re.match(r"/meetups/(\d+)/edit", r.headers["Location"]).group(1))
        a0, a1 = M.to_et(M.get(mid)["starts_at"]), M.to_et(M.get(nid)["starts_at"])
        self.assertEqual((a1.date() - a0.date()).days, 7)
        self.assertEqual(a1.strftime("%H:%M"), a0.strftime("%H:%M"))  # same ET wall time, even across a DST change
        self.assertEqual(M.get(nid)["status"], "active")

    def test_comments_reports_and_hiding(self):
        host, _, hid, _ = member("com")
        a, _, aid, adogs = member("cmt")
        stranger, *_ = member("str")
        mid, _ = create(host)
        r = stranger.post(f"/meetups/{mid}/comments", {"body": "hi"})
        self.assertIn("e=rsvpfirst", r.headers["Location"])
        rsvp(a, mid, adogs)
        self.assertEqual(a.post(f"/meetups/{mid}/comments", {"body": "hi"}, csrf=False).status, 403)
        r = a.post(f"/meetups/{mid}/comments", {"body": "See you <b>there</b>!"})
        self.assertEqual(r.status, 303)
        page = mpage(a, mid).text
        self.assertIn("See you &lt;b&gt;there&lt;/b&gt;!", page)
        self.assertNotIn("<b>there</b>", page)
        cid = M.comments(mid)[0]["id"]
        # strangers (no RSVP) can't read comments; anonymous visitors see only a count
        self.assertNotIn("See you", mpage(Client(), mid).text)
        r = stranger.post(f"/meetups/{mid}/comments/{cid}/report", {"reason": A.REPORT_REASONS[0][0] if isinstance(A.REPORT_REASONS[0], tuple) else A.REPORT_REASONS[0]})
        self.assertEqual(r.status, 303)
        self.assertEqual(stranger.post(f"/meetups/{mid}/comments/{cid}/delete", {}).status, 403)
        adm = Client().get("/admin/reports?key=test-admin-key")
        self.assertEqual(adm.status, 200)
        self.assertIn("See you", adm.text)
        r = Client().post("/admin/reports", {"key": "test-admin-key", "action": "hide_comment", "id": "0", "comment": str(cid)}, csrf=False)
        self.assertIn(r.status, (200, 303))
        M.set_comment_hidden(cid, 1)
        self.assertNotIn("See you", mpage(a, mid).text)
        # hiding a meetup removes it from public pages
        self.assertEqual(Client().post("/admin/meetups", {"key": "wrong", "id": str(mid), "action": "hide"}, csrf=False).status, 404)
        r = Client().post("/admin/meetups", {"key": "test-admin-key", "id": str(mid), "action": "hide"}, csrf=False)
        self.assertIn(r.status, (200, 303))
        self.assertEqual(mpage(Client(), mid).status, 404)

    def test_comment_rate_limit(self):
        host, _, hid, hdogs = member("rl")
        mid, _ = create(host)
        codes = [host.post(f"/meetups/{mid}/comments", {"body": f"note {i}"}).headers.get("Location", "") for i in range(8)]
        self.assertTrue(any("e=slow" in x for x in codes), codes)
        self.assertEqual(M.comment_count(mid), 6)

    def test_email_preferences_and_unsubscribe(self):
        host, _, hid, _ = member("pref")
        a, aemail, aid, adogs = member("unsub")
        tok = M.unsub_token(aid)
        self.assertEqual(Client().post("/emails/meetups", {"u": str(aid), "t": "bad"}, csrf=False).status, 400)
        r = Client().req("POST", f"/emails/meetups?u={aid}&t={tok}", "List-Unsubscribe=One-Click",
                         {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 200)
        self.assertFalse(M.emails_on(aid))
        mid, _ = create(host)
        t0 = mark()
        rsvp(a, mid, adogs)
        time.sleep(0.6)
        self.assertEqual(outbox("meetup-confirm", aemail, t0), [])
        self.assertIn("Turn on meetup emails", a.get("/me").text)
        a.post("/me/emails", {"on": "1"})
        self.assertTrue(M.emails_on(aid))

    def test_reminders_endpoint(self):
        host, hemail, hid, hdogs = member("rem")
        a, aemail, aid, adogs = member("remi")
        mid, _ = create(host)
        rsvp(a, mid, adogs)
        self.assertEqual(Client().post("/admin/meetups/reminders", {"key": "nope"}, csrf=False).status, 404)
        # move it to ~20h from now: due for a reminder
        A.q("UPDATE meetups SET starts_at=:s WHERE id=:i", s=A.now() + 20 * 3600, i=mid)
        t0 = mark()
        r = Client().req("POST", "/admin/meetups/reminders", "", {"X-Admin-Key": "test-admin-key",
                                                                  "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 200)
        d = json.loads(r.text)
        self.assertTrue(d["ok"])
        self.assertGreaterEqual(d["meetups"], 1)
        wait_mail("meetup-reminder", aemail, t0)
        # only once
        r = Client().post("/admin/meetups/reminders", {"key": "test-admin-key"}, csrf=False)
        time.sleep(0.4)
        self.assertEqual(len(outbox("meetup-reminder", aemail, t0)), 1)

    def test_admin_test_email_goes_to_host_only(self):
        host, hemail, hid, hdogs = member("tst")
        a, aemail, aid, adogs = member("tsta")
        mid, _ = create(host)
        rsvp(a, mid, adogs)
        self.assertEqual(Client().post("/admin/meetups/test-email", {"key": "x", "id": str(mid), "kind": "confirm"}, csrf=False).status, 404)
        t0 = mark()
        for kind in ("confirm", "host", "cancel", "reminder", "promoted"):
            r = Client().post("/admin/meetups/test-email", {"key": "test-admin-key", "id": str(mid), "kind": kind}, csrf=False)
            self.assertEqual(r.status, 200, r.text)
            wait_mail(f"meetup-{kind}", hemail, t0)
        time.sleep(0.3)
        self.assertTrue(all(m["subject"].startswith("[Test] ") for k in ("confirm", "host") for m in outbox(f"meetup-{k}", hemail, t0)))
        self.assertEqual([m for m in glob.glob(os.path.join(T.TMP, "outbox", "*meetup*.json"))
                          if m not in t0 and json.load(open(m))["to"] == aemail], [])

    def test_sample_seed_sends_no_email(self):
        import seed
        t0 = mark()
        uid, _ = A.get_or_create_user(seed.OWNER["email"])
        mid = seed.seed_meetup(uid, log=lambda *a: None)
        self.assertEqual(seed.seed_meetup(uid, log=lambda *a: None), mid)  # idempotent
        m = M.get(mid)
        self.assertEqual((m["is_sample"], m["run_id"], m["duration_min"]), (1, "n-006", 60))
        self.assertEqual(M.to_et(m["starts_at"]).strftime("%Y-%m-%d %H:%M"), "2026-10-31 10:00")
        self.assertIsNotNone(m["reminder_sent_at"])  # never reminded
        self.assertNotIn("Jack", m["description"])
        time.sleep(0.4)
        self.assertEqual([f for f in glob.glob(os.path.join(T.TMP, "outbox", "*meetup*.json")) if f not in t0], [])
        self.assertIn("Sample", mpage(Client(), mid).text)


if __name__ == "__main__":
    unittest.main()
