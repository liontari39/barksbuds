"""Community features: run check-ins, park announcements + follows, lost and found, compatibility,
private care reminders, local recommendations, birthdays and gotcha days, community emails + unsubscribe.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
Reuses the server/client helpers from test_app (same process, same temp data dir and outbox).
Test dogs are Lily (6-year-old standard poodle mix) and Maggie (3-year-old merle Frenchie).
"""
import glob, html, json, os, re, sys, time, unittest
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, jpeg_with_exif, RUN  # noqa: E402
import accounts as A  # noqa: E402
import community as C  # noqa: E402
import communityweb  # noqa: E402

KEY = "test-admin-key"
RUN_ID = "n-006"  # Christopher Morley Park Dog Run (Nassau)


def setUpModule():
    communityweb.AUTO_JOBS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def mark():
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
    for _ in range(80):
        got = outbox(tag, to, since)
        if len(got) >= n:
            return got
        time.sleep(0.1)
    raise AssertionError(f"no {tag} email for {to}")


_n = [0]


def member(name, area="Nassau", town="Manhasset", dogs=()):
    """A signed-in member; dogs is a list of dicts passed to new_dog (Lily / Maggie)."""
    _n[0] += 1
    c = Client(f"10.77.{_n[0] // 200}.{_n[0] % 200 + 1}")
    email = f"{name.lower()}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    c.post("/me/profile", {"display_name": name, "area": area, "town": town, "bio": ""})
    ids = [new_dog(c, **d) for d in dogs]
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid, ids


def lily(**over):
    d = dict(name="Lily", breed="Standard Poodle mix", age="6", size="large", sex="female", energy="medium",
             compat=["puppies", "small_dogs", "big_dogs"])
    d.update(over)
    return d


def maggie(**over):
    d = dict(name="Maggie", breed="Merle French Bulldog", age="3", size="small", sex="female", energy="high",
             compat=["puppies", "rough"])
    d.update(over)
    return d


def upload_form(c, path, fields, files):
    """multipart POST with form fields plus files in the "photos" field."""
    import uuid
    bnd = "----bb" + uuid.uuid4().hex
    fields = dict(fields, csrf=c.csrf())
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    for name, data, ctype in files:
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="photos"; filename="{name}"\r\n'
                     f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    return c.req("POST", path, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={bnd}"})


def follow_redirect(c, path):
    r = c.get(path)
    if r.status in (301, 302, 303):
        r = c.get(r.headers["Location"])
    return r


def daily(today=None):
    c = Client("10.77.250.1")
    data = {"today": today} if today else {}
    return c.post("/admin/jobs/daily", data, csrf=False, headers={"X-Admin-Key": KEY})


class CheckinTests(unittest.TestCase):
    def test_checkin_leave_privacy_and_live_counts(self):
        c, email, uid, (lid,) = member("Mike", dogs=[lily()])
        o, _, ouid, (mid,) = member("Sam", dogs=[maggie()])
        r = follow_redirect(c, f"/runs/{RUN_ID}")
        self.assertEqual(r.status, 200)
        self.assertIn("We're here", r.text)
        # can't check in someone else's dog
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(mid)]})
        self.assertIn("m=nodogs", r.headers["Location"])
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertEqual(r.status, 303)
        page = c.get(r.headers["Location"].split("#")[0]).text
        self.assertIn("Leaving", page)
        self.assertIn("Lily", page)
        live = json.loads(Client("10.77.251.1").get("/api/runs/live").body)
        self.assertGreaterEqual(live["here"].get(RUN_ID, 0), 1)
        # anonymous check-in: counted, but not shown by name
        o.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(mid)], "anon": "1"})
        pub = follow_redirect(Client("10.77.251.2"), f"/runs/{RUN_ID}").text
        self.assertIn("Lily", pub)
        self.assertNotIn("Maggie", pub)
        n = json.loads(Client("10.77.251.1").get("/api/runs/live").body)["here"][RUN_ID]
        self.assertGreaterEqual(n, 2)
        # leaving drops the count
        c.post(f"/runs/{RUN_ID}/leave", {})
        n2 = json.loads(Client("10.77.251.1").get("/api/runs/live").body)["here"].get(RUN_ID, 0)
        self.assertEqual(n2, n - 1)
        # check-ins expire after two hours
        C.q("UPDATE checkins SET expires_at=:t WHERE user_id=:u", t=C.now() - 1, u=ouid)
        self.assertEqual(json.loads(Client("10.77.251.1").get("/api/runs/live").body)["here"].get(RUN_ID, 0), n - 2)

    def test_checkin_needs_login_and_rate_limit(self):
        r = Client("10.77.252.1").post(f"/runs/{RUN_ID}/checkin", {"dogs": ["1"]}, csrf=False)
        self.assertIn(r.status, (303, 403))
        c, _, uid, (lid,) = member("Pat", dogs=[maggie()])
        for _ in range(C.CHECKINS_PER_HOUR):
            c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertIn("m=slow", r.headers["Location"])
        c.post(f"/runs/{RUN_ID}/leave", {})

    def test_privacy_setting_defaults_check_ins_to_anonymous(self):
        c, _, uid, (lid,) = member("Robin", dogs=[maggie(name="Maggie")])
        c.post("/me/community-emails", {"checkins_hidden": "1", "follow": "1", "alert": "1", "celebrate": "1", "care": "1"})
        self.assertTrue(C.checkins_hidden(uid))
        page = follow_redirect(c, f"/runs/{RUN_ID}").text
        self.assertRegex(page, r'name="anon" value="1" checked')
        c.post(f"/runs/{RUN_ID}/leave", {})


class AnnouncementTests(unittest.TestCase):
    def test_park_role_announce_follow_email_feed_and_unsubscribe(self):
        park, pemail, puid, _ = member("Parks")
        fan, femail, fuid, _ = member("Fan", dogs=[lily()])
        # not verified yet: can't post
        r = park.post(f"/runs/{RUN_ID}/announce", {"kind": "closure", "title": "Closed", "body": "x"})
        self.assertEqual(r.status, 403)
        # admin page needs the key
        self.assertEqual(Client("10.77.253.1").get("/admin/parks").status, 404)
        r = Client("10.77.253.1").post("/admin/parks", {"key": KEY, "action": "grant", "email": pemail, "runs": RUN_ID,
                                                       "org": "Town of North Hempstead Parks"}, csrf=False)
        self.assertEqual(r.status, 200)
        self.assertIn("Granted for 1 run", r.text)
        fan.post(f"/runs/{RUN_ID}/follow", {"on": "1"})
        self.assertTrue(C.follows(fuid, RUN_ID))
        since = mark()
        r = park.post(f"/runs/{RUN_ID}/announce", {"kind": "closure", "title": f"Run closed Saturday {RUN}",
                                                   "body": "Resurfacing the small-dog side.", "until": (date.today() + timedelta(days=3)).isoformat()})
        self.assertEqual(r.status, 303)
        page = follow_redirect(Client("10.77.253.2"), f"/runs/{RUN_ID}").text
        self.assertIn(f"Run closed Saturday {RUN}", page)
        self.assertIn("offbadge", page)
        self.assertIn("Town of North Hempstead Parks", page)
        m = wait_mail("community-announce", femail, since)[0]
        self.assertIn("List-Unsubscribe", m["headers"])
        self.assertNotIn(pemail, json.dumps(outbox("community-announce", None, since)))  # poster isn't emailed
        feed = Client("10.77.253.3").get(f"/runs/{RUN_ID}/feed.xml")
        self.assertEqual(feed.status, 200)
        self.assertIn("rss", feed.headers["Content-Type"] + feed.text[:200])
        self.assertIn(f"Run closed Saturday {RUN}", feed.text)
        self.assertIn(f"Run closed Saturday {RUN}", Client("10.77.253.3").get(f"/runs/{RUN_ID}/news").text)
        self.assertGreaterEqual(json.loads(Client("10.77.253.3").get("/api/runs/live").body)["news"].get(RUN_ID, 0), 1)
        # one-click unsubscribe from the header link
        link = m["headers"]["List-Unsubscribe"].strip("<>")
        p = urlsplit(link)
        r = Client("10.77.253.4").req("POST", p.path + "?" + p.query, "List-Unsubscribe=One-Click",
                                     {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 200)
        self.assertFalse(C.emails_on(fuid, "follow"))
        # a bad token does nothing
        bad = Client("10.77.253.4").post(p.path, {"u": str(fuid), "k": "follow", "t": "nope", "action": "on"}, csrf=False)
        self.assertEqual(bad.status, 400)
        since = mark()
        park.post(f"/runs/{RUN_ID}/announce", {"kind": "event", "title": f"Yappy hour {RUN}", "body": "Treats at 5."})
        time.sleep(0.6)
        self.assertEqual(outbox("community-announce", femail, since), [])
        # the verified account can remove its own announcement; admin can too
        aid = C.announcements(RUN_ID)[0]["id"]
        park.post(f"/runs/{RUN_ID}/announce/{aid}/remove", {})
        self.assertNotIn(f"Yappy hour {RUN}", follow_redirect(Client("10.77.253.5"), f"/runs/{RUN_ID}").text)
        for a in C.announcements(RUN_ID):
            Client("10.77.253.1").post("/admin/parks", {"key": KEY, "action": "remove_announcement", "id": str(a["id"])}, csrf=False)
        self.assertNotIn(f"Run closed Saturday {RUN}", follow_redirect(Client("10.77.253.5"), f"/runs/{RUN_ID}").text)
        fan.post(f"/runs/{RUN_ID}/follow", {"on": "0"})
        self.assertFalse(C.follows(fuid, RUN_ID))


class LostFoundTests(unittest.TestCase):
    def test_lost_alert_flow(self):
        c, email, uid, (lid,) = member("Mike", dogs=[lily()])
        nb, nemail, nuid, _ = member("Neighbor", town="Roslyn", dogs=[maggie()])
        since = mark()
        seen = datetime.now(C.ET).strftime("%Y-%m-%dT%H:%M")
        r = c.post("/lost-found/new", {"kind": "lost", "dog": str(lid), "dog_name": "", "run": RUN_ID, "area": "", "town": "",
                                       "seen": seen, "description": "Cream poodle mix, red collar, very friendly."})
        self.assertEqual(r.status, 303, r.text[:500])
        path = r.headers["Location"].split("?")[0]
        aid = int(path.rsplit("/", 1)[1])
        page = Client("10.77.254.1").get(path)
        self.assertEqual(page.status, 200)
        self.assertIn("Lily", page.text)
        self.assertIn(f"/lost-found/{aid}/og.png", page.text)  # share card
        self.assertNotIn(email, page.text)  # contact only through messages
        self.assertIn(f"/messages/to/{uid}", nb.get(path).text)
        og = Client("10.77.254.1").get(f"/lost-found/{aid}/og.png")
        self.assertEqual(og.status, 200)
        self.assertEqual(og.body[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("lfbanner", Client("10.77.254.2").get("/").text)
        self.assertIn(f"/lost-found/{aid}", follow_redirect(Client("10.77.254.2"), f"/runs/{RUN_ID}").text)
        wait_mail("community-lost", nemail, since)  # area resident
        self.assertEqual(outbox("community-lost", email, since), [])  # not the poster
        # one alert per day
        r = c.post("/lost-found/new", {"kind": "found", "dog_name": "", "run": "", "area": "Nassau", "town": "Roslyn",
                                       "seen": seen, "description": "A second one, same day."})
        self.assertEqual(r.status, 429)
        # only the poster can close it
        self.assertEqual(nb.post(f"/lost-found/{aid}/reunited", {}).status, 404)
        r = c.post(f"/lost-found/{aid}/reunited", {})
        self.assertEqual(r.status, 303)
        self.assertEqual(C.alert(aid)["status"], "reunited")
        self.assertNotIn(f"/lost-found/{aid}", Client("10.77.254.2").get("/").text)
        self.assertIn("Reunited", Client("10.77.254.2").get(path).text)

    def test_found_alert_with_photo_expiry_and_admin_delete(self):
        c, email, uid, _ = member("Finder", area="Queens", town="Fresh Meadows")
        r = upload_form(c, "/lost-found/new", {"kind": "found", "dog_name": "", "run": "", "area": "Queens", "town": "Fresh Meadows",
                                              "seen": "", "description": "Small black and white dog, no collar."},
                          [("dog.jpg", jpeg_with_exif(), "image/jpeg")])
        self.assertEqual(r.status, 303, r.text[:500])
        aid = int(r.headers["Location"].split("?")[0].rsplit("/", 1)[1])
        ph = Client("10.77.255.1").get(f"/lost-found/{aid}/photo.jpg")
        self.assertEqual(ph.status, 200)
        self.assertNotIn(b"SecretCam", ph.body)  # EXIF stripped
        self.assertEqual(Client("10.77.255.1").get("/admin/lost").status, 404)
        self.assertIn("Small black and white", Client("10.77.255.1").get(f"/admin/lost?key={KEY}").text)
        Client("10.77.255.1").post("/admin/lost", {"key": KEY, "id": str(aid)}, csrf=False)
        self.assertEqual(C.alert(aid)["status"], "removed")
        self.assertEqual(Client("10.77.255.1").get(f"/lost-found/{aid}").status, 404)
        # expiry: alerts older than 14 days drop off the live list
        C.q("UPDATE lost_alerts SET status='active', expires_at=:t WHERE id=:i", t=C.now() - 60, i=aid)
        self.assertNotIn(aid, [a["id"] for a in C.live_alerts()])
        C.set_alert_status(aid, "removed")

    def test_lost_needs_login_and_description(self):
        r = Client("10.77.255.9").get("/lost-found/new")
        self.assertEqual(r.status, 303)
        c, *_ = member("Quick")
        r = c.post("/lost-found/new", {"kind": "lost", "dog_name": "Lily", "area": "Nassau", "description": "short", "seen": ""})
        self.assertEqual(r.status, 422)


class CompatibilityTests(unittest.TestCase):
    def test_chips_and_filters(self):
        c, _, uid, (lid, mid) = member("Mike", dogs=[lily(name=f"Lily{RUN}"), maggie(name=f"Maggie{RUN}")])
        slug = A.dog_by_id(mid)["slug"]
        page = Client("10.77.240.1").get(f"/dogs/{slug}").text
        self.assertIn("Meeting other dogs", page)
        self.assertIn("High energy", page)
        self.assertIn("Plays rough", page)
        self.assertIn("Small", page)
        grid = lambda t: t.split('class="dgrid"', 1)[-1]
        hi = grid(Client("10.77.240.1").get("/dogs?area=Nassau&energy=high").text)
        self.assertIn(f"Maggie{RUN}", hi)
        self.assertNotIn(f"Lily{RUN}", hi)
        big = grid(Client("10.77.240.1").get("/dogs?size=large&compat=small_dogs").text)
        self.assertIn(f"Lily{RUN}", big)
        self.assertNotIn(f"Maggie{RUN}", big)
        # bad values are ignored, not errors
        self.assertEqual(Client("10.77.240.1").get("/dogs?size=huge&energy=zoom").status, 200)
        # the edit form keeps the values
        form = c.get(f"/me/dogs/{mid}/edit").text
        self.assertRegex(form, r'name="energy" value="high" checked')
        self.assertRegex(form, r'name="compat" value="rough" checked')


class CareTests(unittest.TestCase):
    def test_private_reminders_and_daily_emails(self):
        c, email, uid, (lid,) = member("Mike", dogs=[lily()])
        stranger, *_ = member("Stranger")
        self.assertIn(stranger.get(f"/me/dogs/{lid}/care").status, (403, 404))
        due30 = (C.today_et() + timedelta(days=30)).isoformat()
        due7 = (C.today_et() + timedelta(days=7)).isoformat()
        self.assertEqual(c.post(f"/me/dogs/{lid}/care", {"action": "add", "kind": "rabies", "due": due30}).status, 303)
        self.assertEqual(c.post(f"/me/dogs/{lid}/care", {"action": "add", "kind": "vaccine", "label": "Bordetella", "due": due7}).status, 303)
        self.assertEqual(c.post(f"/me/dogs/{lid}/care", {"action": "add", "kind": "license", "due": "not-a-date"}).status, 422)
        page = c.get(f"/me/dogs/{lid}/care").text
        self.assertIn("Rabies vaccine", page)
        self.assertIn("Bordetella", page)
        slug = A.dog_by_id(lid)["slug"]
        self.assertNotIn("Bordetella", Client("10.77.241.1").get(f"/dogs/{slug}").text)  # never public
        self.assertEqual(Client("10.77.241.2").post("/admin/jobs/daily", {}, csrf=False).status, 404)
        since = mark()
        r = daily()
        self.assertEqual(r.status, 200)
        self.assertGreaterEqual(json.loads(r.body)["care_reminders"], 2)
        got = wait_mail("community-care", email, since, n=2)
        self.assertTrue(any("Rabies" in g["subject"] or "rabies" in g["text"] for g in got))
        # not twice for the same date
        since = mark()
        daily()
        time.sleep(0.5)
        self.assertEqual(outbox("community-care", email, since), [])
        # delete
        items = C.care_items(lid)
        for it in items:
            c.post(f"/me/dogs/{lid}/care", {"action": "delete", "id": str(it["id"])})
        self.assertEqual(C.care_items(lid), [])


class RecommendationTests(unittest.TestCase):
    def test_add_vote_report_moderate(self):
        c, _, uid, _ = member("Mike")
        o, _, ouid, _ = member("Sam")
        name = f"Test Animal Hospital {RUN}"
        empty = Client("10.77.242.1").get("/recommendations?area=Westchester&cat=daycare").text
        self.assertIn("No ", empty)
        r = c.post("/recommendations/new", {"category": "vet", "name": name, "town": "Manhasset", "area": "Nassau",
                                            "contact": "", "note": "Great with nervous dogs.", "real": "1"})
        self.assertEqual(r.status, 422)  # needs a website or phone
        r = c.post("/recommendations/new", {"category": "vet", "name": name, "town": "Manhasset", "area": "Nassau",
                                            "contact": "https://example.com/vet", "note": "Great with nervous dogs."})
        self.assertEqual(r.status, 422)  # needs the customer checkbox
        r = c.post("/recommendations/new", {"category": "vet", "name": name, "town": "Manhasset", "area": "Nassau",
                                            "contact": "https://example.com/vet", "note": "Great with nervous dogs.", "real": "1"})
        self.assertEqual(r.status, 303)
        rid = int(r.headers["Location"].rsplit("#r", 1)[1])
        # adding the same business again counts as "I use them too", once per member
        o.post("/recommendations/new", {"category": "vet", "name": name.upper(), "town": "manhasset", "area": "Nassau",
                                        "contact": "", "note": "", "real": "1"})
        o.post(f"/recommendations/{rid}/vote", {})
        self.assertEqual(C.rec(rid)["votes"], 2)
        page = Client("10.77.242.1").get("/recommendations?area=Nassau&cat=vet").text
        self.assertIn(name, page)
        self.assertIn("Great with nervous dogs.", page)
        o.post(f"/recommendations/{rid}/unvote", {})
        self.assertEqual(C.rec(rid)["votes"], 1)
        o.post(f"/recommendations/{rid}/report", {"reason": "Not a real business", "details": "test"})
        self.assertIn(name, Client("10.77.242.1").get(f"/admin/recs?key={KEY}").text)
        Client("10.77.242.1").post("/admin/recs", {"key": KEY, "action": "hide", "id": str(rid)}, csrf=False)
        self.assertNotIn(name, Client("10.77.242.1").get("/recommendations?area=Nassau").text)
        Client("10.77.242.1").post("/admin/recs", {"key": KEY, "action": "delete", "id": str(rid)}, csrf=False)
        self.assertIsNone(C.rec(rid))


class CelebrationTests(unittest.TestCase):
    def test_birthday_today(self):
        t = C.today_et()
        try:
            bd = t.replace(year=t.year - 6).isoformat()
        except ValueError:
            self.skipTest("Feb 29")
        c, email, uid, (lid,) = member("Mike", dogs=[lily(name=f"Lily{RUN}", birthday=bd, age="")])
        slug = A.dog_by_id(lid)["slug"]
        home = Client("10.77.243.1").get("/").text
        self.assertIn("Celebrating today", home)
        self.assertIn(f"Lily{RUN}", home)
        self.assertIn(f"Lily{RUN}", Client("10.77.243.1").get("/dogs?area=Nassau").text)
        r = Client("10.77.243.1").get(f"/celebrate/{slug}")
        self.assertEqual(r.status, 200)
        self.assertIn("6th birthday", r.text)
        self.assertIn(f"/celebrate/{slug}.png", r.text)
        png = Client("10.77.243.1").get(f"/celebrate/{slug}.png")
        self.assertEqual(png.body[:4], b"\x89PNG")
        since = mark()
        daily()
        wait_mail("community-celebrate", email, since)
        since = mark()
        daily()
        time.sleep(0.5)
        self.assertEqual(outbox("community-celebrate", email, since), [])
        # opt-out
        c.post("/me/community-emails", {"follow": "1", "alert": "1", "care": "1"})
        self.assertFalse(C.emails_on(uid, "celebrate"))

    def test_admin_dog_birthday_sets_only_birthday(self):
        c, email, uid, (lid,) = member("Mike", dogs=[maggie(name=f"Maggie{RUN}")])
        d0 = A.dog_by_id(lid)
        slug = d0["slug"]
        adm = Client("10.77.243.9")
        self.assertEqual(adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2023-08-02"}, csrf=False).status, 404)
        self.assertEqual(adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2023-08-02"}, csrf=False,
                                  headers={"X-Admin-Key": "wrong"}).status, 404)
        H = {"X-Admin-Key": KEY}
        self.assertEqual(adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2099-01-01"}, csrf=False, headers=H).status, 400)
        self.assertEqual(adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2023-02-30"}, csrf=False, headers=H).status, 400)
        self.assertEqual(adm.post("/admin/dogs/birthday", {"slug": "no-such-dog-x", "birthday": "2023-08-02"}, csrf=False, headers=H).status, 404)
        r = adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2023-08-02", "dry_run": "1"}, csrf=False, headers=H)
        self.assertEqual(r.status, 200)
        self.assertEqual(A.dog_by_id(lid)["birthday"], d0["birthday"])
        since = mark()
        r = adm.post("/admin/dogs/birthday", {"slug": slug, "birthday": "2023-08-02"}, csrf=False, headers=H)
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.text)["after"]["birthday"], "2023-08-02")
        d1 = A.dog_by_id(lid)
        self.assertEqual(d1["birthday"], "2023-08-02")
        for k in d0:
            if k != "birthday":
                self.assertEqual(d0[k], d1[k], k)
        pg = Client("10.77.243.1").get(f"/dogs/{slug}").text
        self.assertIn("Birthday Aug 2", pg)
        self.assertIn("3 years old", pg)
        time.sleep(0.3)
        self.assertEqual(mark() - since, set())

    def test_gotcha_day_validation_and_card(self):
        t = C.today_et()
        try:
            gd = t.replace(year=t.year - 2).isoformat()
        except ValueError:
            self.skipTest("Feb 29")
        c, _, uid, _ = member("Sam")
        r = c.post("/me/dogs/new", dict(maggie(), gotcha_day=(t + timedelta(days=3)).isoformat(),
                                        temperament=["Gentle"], play_style=["Chaser"], runs=["n-006"]))
        self.assertEqual(r.status, 422)
        mid = new_dog(c, **maggie(name=f"Maggie{RUN}", gotcha_day=gd))
        slug = A.dog_by_id(mid)["slug"]
        r = Client("10.77.243.2").get(f"/celebrate/{slug}?k=gotcha")
        self.assertEqual(r.status, 200)
        self.assertIn("gotcha day", r.text.lower())
        self.assertIn("/celebrate/", Client("10.77.243.2").get(f"/dogs/{slug}").text)


class HubAndNavTests(unittest.TestCase):
    def test_pages_load_and_nav(self):
        cl = Client("10.77.244.1")
        for p in ("/community", "/lost-found", "/lost-found?kind=found", "/recommendations", f"/runs/{RUN_ID}/news", "/sitemap.xml"):
            r = cl.get(p)
            self.assertEqual(r.status, 200, p)
        self.assertIn('href="/community"', cl.get("/").text)
        self.assertIn('href="/community"', cl.get("/dogs").text)
        self.assertIn('href="/community"', cl.get("/runs").text)
        self.assertIn("/lost-found", cl.get("/sitemap.xml").text)
        self.assertEqual(cl.get("/runs/z-99999").status, 404)
        r = cl.get(f"/runs/{RUN_ID}")
        self.assertEqual(r.status, 301)
        self.assertRegex(r.headers["Location"], rf"^/runs/{RUN_ID}-[a-z0-9-]+$")
        home = cl.get("/").text
        self.assertLess(home.find("pixel"), home.find('id="community"'))  # pixel pals stay above the community block

    def test_daily_job_needs_key(self):
        self.assertEqual(Client("10.77.244.2").post("/admin/jobs/daily", {"key": "wrong"}, csrf=False).status, 404)
        r = daily()
        self.assertEqual(r.status, 200)
        self.assertIn("care_reminders", json.loads(r.body))


if __name__ == "__main__":
    unittest.main()
