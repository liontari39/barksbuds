"""In-app account deletion confirmation, the admin review queue, and new-account limits."""
import os, re, sys, unittest
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, RUN, wait_link, last_link  # noqa: E402
import accounts as A  # noqa: E402
import messages as MS  # noqa: E402
import meetups as M  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


_n = [0]


def member(name="safe"):
    _n[0] += 1
    c = Client(f"10.71.{_n[0] // 200}.{_n[0] % 200 + 1}")
    email = f"{name.lower().replace(' ', '')}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    c.post("/me/profile", {"display_name": name, "area": "Nassau", "town": "Manhasset", "bio": ""})
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid


def future(days=3, hhmm="10:00"):
    d = (datetime.now(M.ET) + timedelta(days=days)).strftime("%Y-%m-%d")
    return d, hhmm


def create_meetup(c, **over):
    d, t = future()
    data = {"title": "Safety romp", "date": d, "time": t, "duration": "60", "loc": "run", "run_id": "n-006",
            "description": "Water and shade.", "fit": "", "capacity": ""}
    data.update(over)
    return c.post("/meetups/new", data)


class SafetyTests(unittest.TestCase):
    def test_delete_requires_typing_delete(self):
        c, email, uid = member("Del")
        new_dog(c, name="Lily")
        page = c.get("/me/delete")
        self.assertEqual(page.status, 200)
        self.assertIn("Type", page.text)
        self.assertIn("DELETE", page.text)
        self.assertIsNotNone(A.one("SELECT id FROM users WHERE id=:i", i=uid))
        r = c.post("/me/delete", {"confirm": "yes"})
        self.assertIsNotNone(A.one("SELECT id FROM users WHERE email=:e", e=email))
        self.assertIn("Delete your account", r.text)
        r = c.post("/me/delete", {"confirm": "delete"})
        self.assertIn("Your account is deleted", r.text)
        self.assertIsNone(A.one("SELECT id FROM users WHERE email=:e", e=email))

    def test_admin_review_queue_dismiss_hide_suspend(self):
        owner, oemail, oid = member("Owner")
        dog_id = new_dog(owner, name="Lily")
        slug = A.dog_by_id(dog_id)["slug"]
        viewer, _, vid = member("Viewer")
        self.assertEqual(viewer.post(f"/dogs/{slug}/report", {"reason": A.REPORT_REASONS[0], "details": "too loud"}).status, 303)
        self.assertEqual(Client().get("/admin/review").status, 404)
        self.assertEqual(Client().get("/admin/review?key=wrong").status, 404)
        page = Client().get("/admin/review?key=test-admin-key")
        self.assertEqual(page.status, 200)
        self.assertIn("Review queue", page.text)
        self.assertIn("too loud", page.text)
        self.assertIn("Dismiss", page.text)
        self.assertIn("Suspend owner", page.text)
        rid = A.list_reports()[0][0]
        r = Client().post("/admin/review", {"key": "test-admin-key", "id": rid, "dog": dog_id, "action": "dismiss"}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"].split("?")[0], "/admin/review")
        self.assertEqual(A.one("SELECT status FROM reports WHERE id=:i", i=rid)[0], "resolved")
        r = Client().post("/admin/review", {"key": "test-admin-key", "id": rid, "dog": dog_id, "action": "hide"}, csrf=False)
        self.assertEqual(Client().get(f"/dogs/{slug}").status, 404)
        Client().post("/admin/review", {"key": "test-admin-key", "id": rid, "dog": dog_id, "action": "unhide"}, csrf=False)
        self.assertEqual(Client().get(f"/dogs/{slug}").status, 200)
        # member report + hide message + suspend
        r = viewer.post(f"/messages/to/{oid}", {"body": "hello there"})
        self.assertEqual(r.status, 303)
        cid = int(re.match(r"/messages/(\d+)", r.headers["Location"]).group(1))
        mid = MS.messages(cid)[0][0]["id"]
        MS.add_report(MS.message(mid), vid, "Spam", "nope", "1.2.3.4")
        page = Client().get("/admin/review?key=test-admin-key")
        self.assertIn("Member and message reports", page.text)
        self.assertIn("hello there", page.text)
        mrid = MS.list_reports()[0]["id"]
        Client().post("/admin/review", {"key": "test-admin-key", "kind": "message", "id": mrid, "action": "hide_message"}, csrf=False)
        self.assertIsNone(A.one("SELECT id FROM messages WHERE id=:i", i=mid))
        Client().post("/admin/review", {"key": "test-admin-key", "kind": "message", "id": mrid, "user": str(oid), "action": "suspend"}, csrf=False)
        self.assertTrue(A.is_suspended(oid))
        self.assertIsNone(A.session_user(owner.cookies.get("bb_session", "x")))
        self.assertEqual(owner.get("/me").status, 303)
        # a fresh sign-in is refused (backdate the last token so the 45s email cooldown isn't in the way)
        A.q("UPDATE login_tokens SET created_at=created_at-120 WHERE email=:e", e=oemail)
        prev, _ = last_link(oemail)
        guest = Client("10.71.9.9")
        self.assertEqual(guest.post("/signin", {"email": oemail}).status, 200)
        link, _ = wait_link(oemail, prev=prev)
        p = urlsplit(link)
        guest.get(p.path + "?" + p.query)
        r = guest.post("/auth", {"t": parse_qs(p.query)["t"][0]})
        self.assertEqual(r.status, 403)
        self.assertIn("suspended", r.text.lower())
        Client().post("/admin/review", {"key": "test-admin-key", "kind": "message", "id": mrid, "user": str(oid), "action": "unsuspend"}, csrf=False)
        self.assertFalse(A.is_suspended(oid))
        A.q("UPDATE login_tokens SET created_at=created_at-120 WHERE email=:e", e=oemail)
        prev = link
        self.assertEqual(guest.post("/signin", {"email": oemail}).status, 200)
        link, _ = wait_link(oemail, prev=prev)
        p = urlsplit(link)
        guest.get(p.path + "?" + p.query)
        r = guest.post("/auth", {"t": parse_qs(p.query)["t"][0]})
        self.assertEqual(r.status, 303)
        self.assertTrue(r.headers["Location"].startswith("/me"))
        self.assertEqual(guest.get("/me").status, 200)

    def test_new_account_limits_are_tighter(self):
        new_c, _, new_id = member("Newish")
        self.assertTrue(A.is_new_account(new_id))
        self.assertEqual(A.cap(new_id, "msg_new_day"), 3)
        self.assertEqual(A.cap(new_id, "meetups_day"), 2)
        self.assertEqual(A.cap(new_id, "invites_day"), 3)
        pals = [member(f"Pal{i}")[2] for i in range(4)]
        self.assertEqual(new_c.post(f"/messages/to/{pals[0]}", {"body": "hi 1"}).status, 303)
        self.assertEqual(new_c.post(f"/messages/to/{pals[1]}", {"body": "hi 2"}).status, 303)
        self.assertEqual(new_c.post(f"/messages/to/{pals[2]}", {"body": "hi 3"}).status, 303)
        r = new_c.post(f"/messages/to/{pals[3]}", {"body": "hi 4"})
        self.assertEqual(r.status, 429)
        self.assertIn("new conversations today", r.text)
        self.assertEqual(create_meetup(new_c, title="One").status, 303)
        self.assertEqual(create_meetup(new_c, title="Two").status, 303)
        r = create_meetup(new_c, title="Three")
        self.assertEqual(r.status, 429)
        # established accounts keep the higher caps
        old_c, _, old_id = member("Older")
        A.q("UPDATE users SET created_at=:t WHERE id=:i", t=A.now() - 8 * 86400, i=old_id)
        self.assertFalse(A.is_new_account(old_id))
        self.assertEqual(A.cap(old_id, "msg_new_day"), 10)
        self.assertEqual(A.cap(old_id, "meetups_day"), 10)
        self.assertEqual(create_meetup(old_c, title="Established one").status, 303)
        self.assertEqual(create_meetup(old_c, title="Established two").status, 303)
        self.assertEqual(create_meetup(old_c, title="Established three").status, 303)


if __name__ == "__main__":
    unittest.main()
