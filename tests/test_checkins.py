"""Run check-ins: "We're here" / "Check out", who's here now, the recently-here list, privacy and rate limits.

Reuses the existing checkins table and community.py helpers. Lily is the sample dog.
Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN, new_dog  # noqa: E402
import accounts as A  # noqa: E402
import community as C  # noqa: E402
import runsafety as RS  # noqa: E402
import communityweb  # noqa: E402
from test_community import member, lily, follow_redirect, RUN_ID  # noqa: E402

OTHER_RUN = "n-004"  # Eisenhower Park


def setUpModule():
    communityweb.AUTO_JOBS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def daisy(**over):
    d = dict(name="Daisy", breed="Beagle", age="4", size="medium", sex="female", energy="medium",
             compat=["big_dogs"])
    d.update(over)
    return d


_u = [0]


def uniq(fn, **over):
    """Sample-dog helper with a name unique across tests (shared SQLite DB)."""
    _u[0] += 1
    base = fn()
    over.setdefault("name", f"{base['name']}{_u[0]}{RUN}")
    return fn(**over)


def recently_section(html):
    if 'id="recently"' not in html:
        return ""
    part = html.split('id="recently"', 1)[1]
    for sep in ('<div class="panel', "<section", '<form class="checkin"'):
        if sep in part:
            part = part.split(sep, 1)[0]
            break
    return part


def dog_in(rows, name):
    return [r for r in rows for d in r["dogs"] if d["name"] == name]


class CheckinPageTests(unittest.TestCase):
    def test_check_out_button_and_checkout_route(self):
        c, _, uid, (lid,) = member("Alex", dogs=[uniq(lily)])
        name = A.dog_by_id(lid)["name"]
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertEqual(r.status, 303)
        page = c.get(r.headers["Location"].split("#")[0]).text
        self.assertIn("Check out", page)
        self.assertNotIn(">Leaving<", page)
        self.assertIn(name, page)
        self.assertIn("/runs/%s/checkout" % RUN_ID, page)
        r = c.post(f"/runs/{RUN_ID}/checkout", {})
        self.assertEqual(r.status, 303)
        self.assertIn("m=left", r.headers["Location"])
        page = c.get(r.headers["Location"].split("#")[0]).text
        self.assertIn("Checked out", page)
        self.assertIn("We're here", page)
        self.assertIsNone(C.active_checkin(uid))

    def test_leave_route_still_works(self):
        c, _, uid, (lid,) = member("Blair", dogs=[uniq(lily)])
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        r = c.post(f"/runs/{RUN_ID}/leave", {})
        self.assertEqual(r.status, 303)
        self.assertIsNone(C.active_checkin(uid))


class RecentlyHereTests(unittest.TestCase):
    def test_recently_here_after_checkout_fuzzy_today(self):
        c, _, uid, _ = member("SamW")
        c.post("/me/profile", {"display_name": "Sam Wilson", "area": "Nassau", "town": "Manhasset", "bio": ""})
        lid = new_dog(c, **uniq(lily))
        o, _, ouid, (did,) = member("Jordan", dogs=[uniq(daisy)])
        lname, dname = A.dog_by_id(lid)["name"], A.dog_by_id(did)["name"]
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        o.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(did)]})
        c.post(f"/runs/{RUN_ID}/checkout", {})
        # Daisy is still here now (after the short display delay); Lily should be in recently here
        C.q("UPDATE checkins SET created_at=:t WHERE user_id=:u AND left_at IS NULL",
            t=C.now() - RS.DISPLAY_DELAY - 1, u=ouid)
        RS.clear_cache()
        pub = follow_redirect(Client("10.90.1.1"), f"/runs/{RUN_ID}").text
        rec = recently_section(pub)
        self.assertIn("Recently here", rec)
        self.assertIn(lname, rec)
        self.assertIn("earlier today", rec)
        self.assertNotIn(dname, rec)
        self.assertNotIn("Wilson", pub)
        self.assertIsNone(re.search(r"\d{1,2}:\d{2}", rec), rec)
        here = pub.split('id="here"', 1)[1].split('id="recently"', 1)[0]
        self.assertIn(dname, here)
        self.assertNotIn(lname, here)

    def test_yesterday_and_this_week_labels(self):
        c, _, uid, (lid,) = member("Casey", dogs=[uniq(lily)])
        lname = A.dog_by_id(lid)["name"]
        now = C.now()
        yesterday = int((datetime.fromtimestamp(now, C.ET) - timedelta(days=1)).timestamp())
        midweek = int((datetime.fromtimestamp(now, C.ET) - timedelta(days=4)).timestamp())
        C.check_in(uid, RUN_ID, [lid])
        C.q("UPDATE checkins SET created_at=:c, expires_at=:e, left_at=:l WHERE user_id=:u AND left_at IS NULL",
            c=yesterday - 1800, e=yesterday + C.CHECKIN_TTL, l=yesterday, u=uid)
        self.assertTrue(dog_in(C.recently_here(RUN_ID), lname))
        self.assertEqual(dog_in(C.recently_here(RUN_ID), lname)[0]["when"], "yesterday")
        rec = recently_section(follow_redirect(Client("10.90.2.1"), f"/runs/{RUN_ID}").text)
        self.assertIn(lname, rec)
        self.assertIn("yesterday", rec)

        o, _, ouid, (did,) = member("Drew", dogs=[uniq(daisy)])
        dname = A.dog_by_id(did)["name"]
        C.check_in(ouid, RUN_ID, [did])
        C.q("UPDATE checkins SET created_at=:c, expires_at=:e, left_at=:l WHERE user_id=:u AND left_at IS NULL",
            c=midweek - 1800, e=midweek + C.CHECKIN_TTL, l=midweek, u=ouid)
        self.assertEqual(dog_in(C.recently_here(RUN_ID), dname)[0]["when"], "this week")
        rec = recently_section(follow_redirect(Client("10.90.2.2"), f"/runs/{RUN_ID}").text)
        self.assertIn(dname, rec)
        self.assertIn("this week", rec)
        self.assertIsNone(re.search(r"\d{1,2}:\d{2}", rec), rec)

    def test_expired_checkin_shows_in_recently_here(self):
        c, _, uid, (lid,) = member("Emery", dogs=[uniq(lily)])
        name = A.dog_by_id(lid)["name"]
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        C.q("UPDATE checkins SET expires_at=:t WHERE user_id=:u AND left_at IS NULL", t=C.now() - 10, u=uid)
        self.assertIsNone(C.active_checkin(uid))
        rec = recently_section(follow_redirect(Client("10.90.3.1"), f"/runs/{RUN_ID}").text)
        self.assertIn(name, rec)
        self.assertIn("earlier today", rec)

    def test_anon_and_hidden_omitted_from_recently_here(self):
        c, _, uid, (lid,) = member("Finley", dogs=[uniq(lily)])
        o, _, ouid, (did,) = member("Gray", dogs=[uniq(daisy)])
        lname, dname = A.dog_by_id(lid)["name"], A.dog_by_id(did)["name"]
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)], "anon": "1"})
        c.post(f"/runs/{RUN_ID}/checkout", {})
        rec = recently_section(follow_redirect(Client("10.90.4.1"), f"/runs/{RUN_ID}").text)
        self.assertNotIn(lname, rec)
        o.post("/me/community-emails", {"checkins_hidden": "1", "follow": "1", "alert": "1", "celebrate": "1", "care": "1"})
        o.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(did)]})
        o.post(f"/runs/{RUN_ID}/checkout", {})
        rec = recently_section(follow_redirect(Client("10.90.4.2"), f"/runs/{RUN_ID}").text)
        self.assertNotIn(lname, rec)
        self.assertNotIn(dname, rec)

    def test_older_than_a_week_drops_off(self):
        c, _, uid, (lid,) = member("Harper", dogs=[uniq(lily)])
        name = A.dog_by_id(lid)["name"]
        old = C.now() - (C.RECENT_HERE_DAYS * 86400 + 3600)
        C.check_in(uid, RUN_ID, [lid])
        C.q("UPDATE checkins SET created_at=:c, expires_at=:e, left_at=:l WHERE user_id=:u",
            c=old - 1800, e=old + C.CHECKIN_TTL, l=old, u=uid)
        self.assertFalse(dog_in(C.recently_here(RUN_ID), name))


class CheckinPrivacyAndLimitsTests(unittest.TestCase):
    def test_cannot_check_in_someone_elses_dog(self):
        c, _, uid, (lid,) = member("Indigo", dogs=[uniq(lily)])
        o, _, ouid, (did,) = member("Jules", dogs=[uniq(daisy)])
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(did)]})
        self.assertIn("m=nodogs", r.headers["Location"])
        self.assertIsNone(C.active_checkin(uid))

    def test_cooldown_after_checkout_same_run(self):
        c, _, uid, (lid,) = member("Kai", dogs=[uniq(lily)])
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        c.post(f"/runs/{RUN_ID}/checkout", {})
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertIn("m=wait", r.headers["Location"])
        self.assertIsNone(C.active_checkin(uid))
        C.q("UPDATE checkins SET left_at=:t WHERE user_id=:u", t=C.now() - C.CHECKIN_COOLDOWN - 1, u=uid)
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertIn("m=here", r.headers["Location"])
        self.assertEqual(C.active_checkin(uid)["run_id"], RUN_ID)

    def test_cooldown_does_not_block_refresh_or_other_run(self):
        c, _, uid, (lid,) = member("Logan", dogs=[uniq(lily)])
        c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertIn("m=here", r.headers["Location"])
        r = c.post(f"/runs/{OTHER_RUN}/checkin", {"dogs": [str(lid)]})
        self.assertIn("m=here", r.headers["Location"])
        self.assertEqual(C.active_checkin(uid)["run_id"], OTHER_RUN)

    def test_fuzzy_when_labels(self):
        now = C.now()
        et = datetime.fromtimestamp(now, C.ET)
        self.assertEqual(C.fuzzy_when(now - 120, now), "earlier today")
        y = int((et - timedelta(days=1)).replace(hour=15, minute=0).timestamp())
        self.assertEqual(C.fuzzy_when(y, now), "yesterday")
        w = int((et - timedelta(days=3)).timestamp())
        self.assertEqual(C.fuzzy_when(w, now), "this week")
