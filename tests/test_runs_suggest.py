"""Suggest a run: member form (new run, edit, wrong pin), validation, CSRF, daily limit, photo EXIF stripping,
duplicate + coverage checks, the owner email, the /admin/runs queue (approve/reject/remove) and the merge into /api/runs.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import html, io, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, mark, wait_mail, outbox  # noqa: E402
from test_packs import multipart  # noqa: E402
import accounts as A  # noqa: E402
import runsugg as R  # noqa: E402
import runsweb  # noqa: E402
import mailer  # noqa: E402
from PIL import Image  # noqa: E402

KEY = "test-admin-key"
E = lambda t: html.escape(t, quote=True)
OWNER = "mike.karachalios@gmail.com"


def setUpModule():
    TM.setUpModule()
    runsweb.NOTIFY_TO = OWNER


def tearDownModule():
    TM.tearDownModule()


def suggest(c, files=(), **over):
    data = {"name": "Searingtown Pup Park", "park": "Searingtown Commons", "county": "Nassau", "town": "Albertson",
            "address": "", "lat": "40.770100", "lng": "-73.650200", "fenced": "yes", "small_dog_area": "unsure", "water": "no",
            "surface": "wood chips", "hours": "Dawn to dusk", "notes": "Double gate.", "source_url": "https://example.org/parks",
            "credit": "1", "edit": ""}
    data.update(over)
    return multipart(c, "/runs/suggest", data, files)


def api_runs():
    return {r["id"]: r for r in json.loads(Client().get("/api/runs").text)["runs"]}


def sid_of(r):
    return int(r.headers["Location"].split("/s/")[1].split("?")[0])


def admin(data):
    d = {"key": KEY}; d.update(data)
    return Client().post("/admin/runs", d, csrf=False)


class SuggestTests(unittest.TestCase):
    def test_sign_in_cta_and_csrf(self):
        anon = Client("10.12.0.2")
        r = anon.get("/runs/suggest")
        self.assertEqual(r.status, 303); self.assertIn("/signin?next=%2Fruns%2Fsuggest", r.headers["Location"])
        self.assertIn('href="/signin?next=%2Fruns%2Fsuggest">+ Suggest a run', anon.get("/runs").text)
        c, *_ = member("sgc", dogs=0)
        self.assertIn('href="/runs/suggest" data-signed-in="1"', c.get("/runs").text)
        page = c.get("/runs/suggest?lat=40.8&lng=-73.6")
        self.assertEqual(page.status, 200)
        for s in ('id="sgmap"', 'name="lat" id="lat" value="40.8"', "/suggest.js", "Somewhere else in the US", 'name="photo"'):
            self.assertIn(s, page.text)
        r = c.post("/runs/suggest", {"name": "No token run", "county": "Nassau", "town": "Roslyn", "address": "1 Main St"}, csrf=False)
        self.assertEqual(r.status, 403)
        self.assertEqual(R.recent_count(A.one("SELECT id FROM users WHERE email LIKE 'sgc%'")[0]), 0)

    def test_new_suggestion_validation_photo_email_and_status(self):
        c, email, uid, _ = member("sgn", dogs=0)
        r = suggest(c, name="", county="", town="", lat="", lng="", address="", source_url="javascript:alert(1)")
        self.assertEqual(r.status, 422)
        for s in (E("What's the run called?"), "Pick an area.", "Add the town or neighborhood.", "Add an address, or drop a pin", "starting with https://"):
            self.assertIn(s, r.text)
        r = suggest(c, lat="48.8566", lng="2.3522")
        self.assertEqual(r.status, 422); self.assertIn(E("isn't in the US"), r.text)
        since = mark()
        r = suggest(c, files=[("photo", "run.jpg", jpeg_with_exif(size=(2400, 1800)))], name="Searingtown <b>Pup</b> Park")
        self.assertEqual(r.status, 303, r.text[:400])
        sid = sid_of(r)
        s = R.get(sid)
        self.assertEqual((s["status"], s["kind"], s["in_coverage"], s["user_id"]), ("pending", "new", 1, uid))
        self.assertEqual(s["data"]["lat"], 40.7701); self.assertTrue(s["data"]["credit"])
        im = Image.open(io.BytesIO(R.photo(sid)))
        self.assertLessEqual(max(im.size), 1600); self.assertFalse(im.getexif(), "EXIF/GPS must be stripped")
        mail = wait_mail("runs-suggestion", OWNER, since)[0]
        self.assertIn("New dog run suggestion", mail["subject"]); self.assertNotIn(KEY, mail["text"])
        self.assertNotIn(f"m-{sid}", api_runs(), "nothing goes live before review")
        st = c.get(f"/runs/suggest/s/{sid}?m=sent")
        self.assertIn("Suggestion sent", st.text); self.assertIn("Searingtown &lt;b&gt;Pup&lt;/b&gt; Park", st.text)
        other, *_ = member("sgo", dogs=0)
        self.assertEqual(other.get(f"/runs/suggest/s/{sid}").status, 404)
        self.assertEqual(Client().get(f"/runs/photo/{sid}.jpg").status, 404, "photos stay private until approved")
        self.assertIn("Your recent suggestions", c.get("/runs/suggest").text)

    def test_duplicate_warning_and_out_of_coverage(self):
        c, *_ = member("sgd", dogs=0)
        base = next(r for r in api_runs().values() if r.get("pin_precision") == "exact")
        lat, lng = base["lat"] + 0.0004, base["lng"]          # ~45 m north of a listed run
        n0 = len(R.pending())
        r = suggest(c, name="Totally New Run", lat=f"{lat:.6f}", lng=f"{lng:.6f}", county=base["county"] if base["county"] in R.COVERAGE else "Queens")
        self.assertEqual(r.status, 200); self.assertIn("Is it one of these?", r.text); self.assertIn(base["name"].replace("'", "&#x27;"), r.text)
        self.assertEqual(len(R.pending()), n0, "warned, not stored")
        r = suggest(c, name="Totally New Run", lat=f"{lat:.6f}", lng=f"{lng:.6f}", county="Queens", dup_ok="1")
        self.assertEqual(r.status, 303)
        self.assertIn(base["name"], R.get(sid_of(r))["dup_of"])
        r = suggest(c, name="Venice Beach Bark Park", county="other", state="CA", town="Los Angeles", lat="33.985", lng="-118.469")
        s = R.get(sid_of(r))
        self.assertEqual((s["in_coverage"], s["data"]["state"]), (0, "CA"))
        self.assertIn("outside NYC, Long Island and Westchester", c.get(f"/runs/suggest/s/{s['id']}").text)
        r = suggest(c, name="Pin Outside Box", county="Nassau", town="Somewhere", lat="42.65", lng="-73.75")  # Albany pin, "Nassau" picked
        self.assertEqual(R.get(sid_of(r))["in_coverage"], 0)

    def test_email_respects_allowlist(self):
        c, *_ = member("sgm", dogs=0)
        saved = mailer.RUNS_ALLOW
        try:
            mailer.RUNS_ALLOW = {"someone-else@example.com"}
            since = mark()
            self.assertEqual(suggest(c, name="Gate Check Run", lat="40.7311", lng="-73.5901").status, 303)
            import time; time.sleep(0.5)
            self.assertEqual(outbox("runs-suggestion", OWNER, since), [], "not on the runs allowlist: no email")
            mailer.RUNS_ALLOW = {OWNER}
            r = suggest(c, edit="", name="Gate Check Run Two", lat="40.7411", lng="-73.5801")
            self.assertEqual(r.status, 303)
            self.assertIn("Gate Check Run Two", wait_mail("runs-suggestion", OWNER, since)[0]["subject"])
        finally:
            mailer.RUNS_ALLOW = saved

    def test_daily_limit(self):
        c, *_ = member("sgl", dogs=0)
        for i in range(R.DAILY_LIMIT):
            self.assertEqual(suggest(c, name=f"Limit Run {i}", lat=f"{40.70 + i * 0.01:.4f}", lng="-73.40").status, 303)
        r = suggest(c, name="One Too Many", lat="40.80", lng="-73.30")
        self.assertEqual(r.status, 429); self.assertIn(E("That's plenty for today"), r.text)

    def test_admin_queue_reject_approve_remove(self):
        c, *_ = member("sga", dogs=0)
        A.q("UPDATE users SET display_name='Pat Q' WHERE email LIKE 'sga%'")
        r = suggest(c, files=[("photo", "p.jpg", jpeg_with_exif())], name="Approve Me <script>x</script> Run", lat="40.7801", lng="-73.6402")
        good = sid_of(r)
        bad = sid_of(suggest(c, name="Reject Me Run", lat="40.7901", lng="-73.6502"))
        self.assertEqual(Client().get("/admin/runs?key=nope").status, 404)
        q = Client().get(f"/admin/runs?key={KEY}").text
        self.assertIn("Approve Me &lt;script&gt;x&lt;/script&gt; Run", q); self.assertNotIn("<script>x</script>", q)
        self.assertIn(f"/admin/runs/photo/{good}-t.webp", q)
        self.assertEqual(Client().get(f"/admin/runs/photo/{good}-t.webp?key={KEY}").status, 200)
        self.assertEqual(Client().get(f"/admin/runs/photo/{good}-t.webp?key=bad").status, 404)
        # reject needs a real reason
        self.assertIn("Add a reason", admin({"action": "reject", "id": str(bad), "reason": ""}).text)
        self.assertEqual(R.get(bad)["status"], "pending")
        self.assertEqual(admin({"action": "reject", "id": str(bad), "reason": "Already listed as Shelter Rock"}).status, 303)
        self.assertEqual(R.get(bad)["status"], "rejected")
        self.assertIn("Already listed as Shelter Rock", c.get(f"/runs/suggest/s/{bad}").text)
        # approve with exact precision + credit
        etag0 = Client().get("/api/runs").headers.get("ETag")
        d = R.get(good)["data"]
        form = {"action": "approve", "id": str(good), "pin_precision": "exact", "credit": "1"}
        form.update({"f_" + k: str(d.get(k) if d.get(k) is not None else "") for k in
                     ("name", "park", "address", "town", "county", "state", "lat", "lng", "fenced", "small_dog_area", "water", "surface", "hours", "notes", "source_url")})
        self.assertEqual(admin(form).status, 303)
        runs = api_runs(); rid = f"m-{good}"
        self.assertIn(rid, runs)
        run = runs[rid]
        self.assertEqual((run["pin_precision"], run["added_by"], run["lat"], run["county"], run["member_suggested"]),
                         ("exact", "Pat Q", 40.7801, "Nassau", True))
        self.assertEqual(run["photo"], f"/runs/photo/{good}.jpg")
        self.assertEqual(Client().get(run["photo"]).status, 200)
        self.assertNotEqual(Client().get("/api/runs").headers.get("ETag"), etag0)
        self.assertIn("Approve Me &lt;script&gt;x&lt;/script&gt; Run", Client().get("/runs").text)
        self.assertIn(E("It's on the map!"), c.get(f"/runs/suggest/s/{good}").text)
        # meetups can use the new run
        self.assertIn(rid, __import__("webapp").run_index())
        # a second approve is refused (already reviewed)
        self.assertIn("already reviewed", admin(form).text)
        # undo
        self.assertEqual(admin({"action": "remove", "run_id": rid}).status, 303)
        self.assertNotIn(rid, api_runs())

    def test_edit_wrong_pin_and_closed(self):
        c, *_ = member("sge", dogs=0)
        target = next(r for r in api_runs().values() if r.get("pin_precision") == "exact" and r["id"].startswith("n-"))
        page = c.get(f"/runs/suggest?edit={target['id']}&pin=1").text
        self.assertIn("Suggesting a change to", page); self.assertIn('value="pin" checked', page)
        self.assertEqual(c.get("/runs/suggest?edit=nope-1").status, 404)
        # wrong pin without moving it -> error
        r = suggest(c, edit=target["id"], reason="pin", name=target["name"], lat=str(target["lat"]), lng=str(target["lng"]))
        self.assertEqual(r.status, 422); self.assertIn("Drag the pin", r.text)
        cur = {k: runsweb.RunRoutes._cur(None, target, k) for k in runsweb.EDIT_FIELDS}
        form = dict(cur); form.update(edit=target["id"], reason="pin", notes="", lat=f"{target['lat'] + 0.001:.6f}", lng=f"{target['lng']:.6f}",
                                      county="Nassau", credit="1")
        r = suggest(c, **form)
        self.assertEqual(r.status, 303, r.text[:300])
        s = R.get(sid_of(r))
        self.assertEqual((s["kind"], s["run_id"], s["reason"]), ("edit", target["id"], "pin"))
        self.assertEqual(s["data"]["_changed"], ["lat"])
        q = Client().get(f"/admin/runs?key={KEY}").text
        self.assertIn("The map pin is in the wrong spot", q)
        self.assertEqual(admin({"action": "approve", "id": str(s["id"]), "apply": ["lat"], "f_lat": form["lat"], "pin_precision": "member"}).text.count("Apply both"), 1)
        self.assertEqual(R.get(s["id"])["status"], "pending")
        r = admin({"action": "approve", "id": str(s["id"]), "apply": ["lat", "lng"], "f_lat": form["lat"], "f_lng": form["lng"], "pin_precision": "member"})
        self.assertEqual(r.status, 303)
        run = api_runs()[target["id"]]
        self.assertEqual((run["lat"], run["pin_precision"], run["name"]), (float(form["lat"]), "member", target["name"]))
        # "closed": admin removes it from the map, then reverts
        r = suggest(c, **dict(cur, edit=target["id"], reason="closed", notes="The town removed the fence in 2025.", county="Nassau"))
        sid = sid_of(r)
        self.assertEqual(admin({"action": "approve", "id": str(sid), "hide": "1"}).status, 303)
        self.assertNotIn(target["id"], api_runs())
        admin({"action": "remove", "run_id": target["id"]})
        self.assertEqual(api_runs()[target["id"]]["lat"], target["lat"], "revert restores the original pin")


if __name__ == "__main__":
    unittest.main()
