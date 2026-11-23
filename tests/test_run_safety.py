"""Live run safety: delayed map counts, privacy, quiet hours, planned arrivals, favorites and alerts."""
import json, os, sys, unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402
import accounts as A
import community as C
import communityweb
import messages
import runsafety as RS
from test_community import member, lily, follow_redirect

RUN_ID = "n-006"


def setUpModule():
    communityweb.AUTO_JOBS = False
    RS.AUTO_TICK = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def backdate(uid, seconds=None):
    seconds = RS.DISPLAY_DELAY + 5 if seconds is None else seconds
    C.q("UPDATE checkins SET created_at=:t WHERE user_id=:u AND left_at IS NULL",
        t=C.now() - seconds, u=uid)
    RS.clear_cache()


def live(client=None):
    c = client or Client("10.88.1.1")
    r = c.get("/api/runs/live")
    return r, json.loads(r.body)


class _Clean(unittest.TestCase):
    def setUp(self):
        C.q("DELETE FROM checkins")
        C.q("DELETE FROM planned_arrivals")
        C.q("DELETE FROM run_quiet_windows")
        C.q("DELETE FROM presence_alert_sent")
        RS.clear_cache()


class PresenceTests(_Clean):
    def test_delay_privacy_blocks_and_mix(self):
        owner, _, uid, (lid,) = member("Sam", dogs=[lily(play_style=["Gentle"], size="large")])
        friend, _, fid, (tid,) = member("TessOwner", dogs=[lily(name="Tess", play_style=["Shy"], size="small")])
        r = owner.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        self.assertEqual(r.status, 303)
        resp, data = live()
        self.assertEqual(resp.headers.get("Cache-Control"), "public, max-age=60")
        self.assertEqual(data["here"].get(RUN_ID, 0), 0)
        self.assertIn("runs", data)

        page = owner.get(r.headers["Location"].split("#")[0]).text
        self.assertIn("Lily", page)  # owner sees themselves immediately
        self.assertIn("not a promise", page.lower())

        pub = follow_redirect(Client("10.88.1.2"), f"/runs/{RUN_ID}").text
        # Public visitors should not see Lily in the live list until the delay has passed.
        here = pub.split('id="here"', 1)[1] if 'id="here"' in pub else pub
        for marker in ("id='recently'", 'id="recently"', 'id="plan"', 'id="quiet"', 'id="conditions"'):
            if marker in here:
                here = here.split(marker, 1)[0]
                break
        self.assertNotIn("Lily", here)

        backdate(uid)
        resp, data = live()
        self.assertEqual(data["here"][RUN_ID], 1)
        info = data["runs"][RUN_ID]
        self.assertEqual(info["n"], 1)
        self.assertFalse(info["busy"])
        self.assertGreaterEqual(info["sizes"].get("Large", 0) + info["sizes"].get("XL", 0), 1)
        self.assertGreaterEqual(info["styles"].get("Gentle", 0), 1)
        # payload must not include owner or dog names
        blob = json.dumps(data)
        self.assertNotIn("Sam", blob)
        self.assertNotIn("Lily", blob)

        pub = follow_redirect(Client("10.88.1.3"), f"/runs/{RUN_ID}").text
        self.assertIn("Lily", pub)
        self.assertIn("Size mix", pub)
        self.assertNotIn("Sam", pub.split("At the run now")[1].split("Recently here")[0] if "At the run now" in pub else pub)

        # Hidden, members-only, anonymous and checkins_hidden are omitted from public counts
        hid, _, hid_uid, (hid_dog,) = member("Hidden", dogs=[lily(name="Pip", visibility="private")])
        hid.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(hid_dog)]})
        backdate(hid_uid)
        mem, _, mem_uid, (mem_dog,) = member("MembersOnly", dogs=[lily(name="Ned", visibility="members")])
        mem.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(mem_dog)]})
        backdate(mem_uid)
        anon, _, anon_uid, (anon_dog,) = member("Anon", dogs=[lily(name="Ace")])
        anon.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(anon_dog)], "anon": "1"})
        backdate(anon_uid)
        hush, _, hush_uid, (hush_dog,) = member("Hush", dogs=[lily(name="Bo")])
        hush.post("/me/community-emails", {"checkins_hidden": "1", "follow": "1", "alert": "1", "celebrate": "1", "care": "1"})
        hush.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(hush_dog)]})
        backdate(hush_uid)
        RS.clear_cache()
        _, pub_live = live()
        # Public: Lily (public) only. Ned is members-only.
        self.assertEqual(pub_live["here"][RUN_ID], 1)
        signed = Client("10.88.1.4")
        sign_in(signed, f"viewer-{RUN}@example.com")
        resp, mem_live = live(signed)
        self.assertEqual(mem_live["here"][RUN_ID], 2)  # Lily + Ned
        self.assertEqual(resp.headers.get("Cache-Control"), "private, max-age=30")

        # Blocks: Tess's owner blocks Sam; they should not see Lily in the count
        messages.block(fid, uid)
        RS.clear_cache()
        blocked_live = json.loads(friend.get("/api/runs/live").body)
        self.assertEqual(blocked_live["here"][RUN_ID], 1)  # Ned only, Lily subtracted

    def test_sticker_and_gate(self):
        r = Client("10.88.2.1").get(f"/runs/{RUN_ID}/sticker")
        self.assertEqual(r.status, 200)
        self.assertIn("noindex", r.text)
        self.assertIn(f"/runs/{RUN_ID}/gate", r.text)
        self.assertIn("nothing is posted", r.text.lower())
        g = Client("10.88.2.2").get(f"/runs/{RUN_ID}/gate")
        self.assertEqual(g.status, 303)
        self.assertIn("m=gate", g.headers["Location"])
        self.assertIn("#here", g.headers["Location"] + g.headers.get("Location", ""))


class PlanQuietFavoriteTests(_Clean):
    def test_planned_arrival_and_quiet_hour(self):
        c, _, uid, (lid,) = member("Planter", dogs=[lily()])
        # too soon
        r = c.post(f"/runs/{RUN_ID}/plan", {"dogs": [str(lid)], "date": datetime.now(RS.ET).date().isoformat(),
                                            "time": datetime.now(RS.ET).strftime("%H:%M")})
        self.assertIn("plan_bad", r.headers.get("Location", ""))
        when = datetime.now(RS.ET) + timedelta(hours=3)
        r = c.post(f"/runs/{RUN_ID}/plan", {"dogs": [str(lid)], "date": when.date().isoformat(),
                                            "time": when.strftime("%H:%M")})
        self.assertIn("m=plan", r.headers["Location"])
        RS.clear_cache()
        _, data = live()
        self.assertTrue(data["runs"].get(RUN_ID, {}).get("planned"))
        self.assertNotIn("Planter", json.dumps(data))
        page = follow_redirect(Client("10.88.3.1"), f"/runs/{RUN_ID}").text
        self.assertIn("Planning to come?", page)
        self.assertIn("Planning to arrive", page)

        later = datetime.now(RS.ET) + timedelta(days=1)
        r = c.post(f"/runs/{RUN_ID}/quiet", {"date": later.date().isoformat(), "start": "08:00", "end": "09:00"})
        self.assertIn("m=quiet", r.headers["Location"])
        page = c.get(r.headers["Location"].split("#")[0]).text
        self.assertIn("Quiet hours", page)
        self.assertIn("8:00 AM", page)

    def test_favorite_requires_owner_opt_in(self):
        owner, _, uid, (lid,) = member("LilyHuman", dogs=[lily()])
        fan, _, fan_id, _ = member("Fan")
        # default off
        self.assertFalse(RS.checkin_alerts_ok(lid))
        slug = A.dog_by_id(lid)["slug"]
        r = fan.post(f"/dogs/{slug}/favorite", {"on": "1"})
        self.assertEqual(r.status, 303)
        self.assertTrue(RS.is_favorite(fan_id, lid))
        page = fan.get(f"/dogs/{slug}").text
        self.assertIn("Favorited", page)

        notes = []
        def capture(uid_, kind, title, body, href):
            notes.append(dict(uid=uid_, kind=kind, title=title, body=body))
        owner.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        backdate(uid)
        with mock.patch("push.notify_async", side_effect=capture):
            RS.flush_alerts()
        self.assertFalse(any(n["uid"] == fan_id for n in notes))

        # Owner opts in, then a new check-in after the delay notifies the fan
        RS.set_checkin_alerts_ok(lid, True)
        C.leave(uid)
        C.q("UPDATE checkins SET left_at=:t, expires_at=:t WHERE user_id=:u", t=C.now() - 120, u=uid)
        owner.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(lid)]})
        backdate(uid)
        notes.clear()
        with mock.patch("push.notify_async", side_effect=capture):
            RS.flush_alerts()
        hits = [n for n in notes if n["uid"] == fan_id and "Lily" in n["body"]]
        self.assertTrue(hits, notes)
        self.assertNotIn("LilyHuman", hits[0]["body"] + hits[0]["title"])
        self.assertEqual(hits[0]["kind"], "checkins")

        # Quiet hours suppress a repeat; rate/claim also prevents a second send of the same check-in
        notes.clear()
        RS.set_quiet_hours(fan_id, 0, 23 * 60 + 59)  # quiet all day
        with mock.patch("push.notify_async", side_effect=capture):
            RS.flush_alerts()
        # same check-in already claimed, so no new favorite alert even after quiet hours would lift
        self.assertFalse(any(n["uid"] == fan_id for n in notes))

    def test_crowd_threshold_and_alerts_page(self):
        a, _, a_uid, (a_dog,) = member("One", dogs=[lily(name="Lily")])
        b, _, b_uid, (b_dog,) = member("Two", dogs=[lily(name="Tess")])
        c, _, c_uid, (c_dog,) = member("Three", dogs=[lily(name="Pip")])
        watcher, _, w_uid, _ = member("Watcher")
        page = watcher.get("/me/run-alerts")
        self.assertEqual(page.status, 200)
        self.assertIn("Quiet hours", page.text)
        self.assertIn("noindex", page.text.lower() or "")  # page() index=False should noindex
        watcher.post("/me/run-alerts", {
            "quiet_start": "21:00", "quiet_end": "07:00",
            "add_run": RUN_ID, "crowd_" + RUN_ID: "3",
        })
        pref = RS.alert_pref(w_uid, RUN_ID)
        # add_run defaults crowd to 3 if the select for that run wasn't in the form... we passed crowd_
        # save_alert_pref uses crowd_threshold from crowd_{rid} or 3 if add.
        self.assertGreaterEqual(pref["crowd_threshold"], 3)

        for cli, did, uid in ((a, a_dog, a_uid), (b, b_dog, b_uid), (c, c_dog, c_uid)):
            cli.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(did)]})
            backdate(uid)
        notes = []
        with mock.patch("push.notify_async", side_effect=lambda *args, **kw: notes.append(args)):
            RS.flush_alerts()
        self.assertTrue(any(n[0] == w_uid and "3 dogs" in (n[2] + n[3]) for n in notes), notes)
        # wording never says safe
        text = " ".join(n[2] + n[3] for n in notes)
        self.assertNotIn("safe", text.lower())

    def test_suggest_packs_separates_rough_and_shy(self):
        dogs = [
            dict(id=1, name="Lily", size="large", styles=["Gentle"], tags=["Gentle"]),
            dict(id=2, name="Tess", size="large", styles=["Shy"], tags=["Shy"]),
            dict(id=3, name="Pip", size="small", styles=["Rough-and-tumble"], tags=["Rough-and-tumble"]),
            dict(id=4, name="Bo", size="small", styles=["Rough-and-tumble"], tags=["Wrestler"]),
        ]
        groups = RS.suggest_packs(dogs)
        names = [tuple(d["name"] for d in g["dogs"]) for g in groups]
        # Lily+Tess together (soft/large), Pip+Bo together (rough/small); never mixed
        flat = {n for g in names for n in g}
        self.assertIn("Lily", flat)
        self.assertTrue(any("Lily" in g and "Tess" in g for g in names))
        self.assertTrue(any("Pip" in g and "Bo" in g for g in names))
        self.assertFalse(any("Lily" in g and "Pip" in g for g in names))
