"""Members-only owner cards (/humans/<id>-<hmac>): privacy, blocks, links, noindex.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, RUN  # noqa: E402
import accounts as A  # noqa: E402
import humans as H  # noqa: E402
import messages as MS  # noqa: E402
import privacy as PV  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402
from test_meetups import create as create_meetup  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


_n = [0]


def member(name="Sam", town="Manhasset", bio="Lily's person.", dog="Lily"):
    _n[0] += 1
    c = Client(f"10.44.{_n[0] // 200}.{(_n[0] % 200) + 1}")
    email = f"{name.lower().replace(' ', '')}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    c.post("/me/profile", {"display_name": name, "area": "Nassau", "town": town, "bio": bio})
    did = new_dog(c, dog, breed="Cairn Terrier") if dog else None
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid, did


class OwnerCard(unittest.TestCase):
    def test_signed_out_is_sent_to_signin(self):
        c, email, uid, did = member()
        path = H.card_path(uid)
        r = Client().get(path)
        self.assertEqual(r.status, 303)
        self.assertIn("/signin", r.headers["Location"])
        self.assertIn("next=", r.headers["Location"])

    def test_signed_in_sees_first_name_town_bio_dog_not_email(self):
        owner, email, uid, did = member("Sam Smith", town="Glen Cove", bio="Lily's person in town.")
        viewer, *_ = member("Alex", dog="Pepper")
        r = viewer.get(H.card_path(uid))
        self.assertEqual(r.status, 200)
        self.assertIn("Sam", r.text)
        self.assertNotIn("Smith", r.text)  # never a surname
        self.assertIn("Glen Cove", r.text)
        self.assertIn("person in town.", r.text)
        self.assertIn("Lily", r.text)
        self.assertNotIn(email, r.text)
        self.assertNotIn("@example.com", r.text)
        self.assertNotIn("last_login", r.text.lower())
        self.assertNotIn("last login", r.text.lower())
        self.assertIn("Message Sam", r.text)
        self.assertIn("Report", r.text)
        self.assertIn("Block this member", r.text)
        # no check-ins or favorite-run tracking
        self.assertNotIn("At the run", r.text)
        self.assertNotIn("check-in", r.text.lower())
        self.assertNotIn("Cunningham", r.text)
        self.assertIn('name="robots" content="noindex"', r.text)
        self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""))

    def test_own_card_has_see_your_card_and_no_message_button(self):
        c, email, uid, did = member("Sam")
        me = c.get("/me").text
        self.assertIn("See your card", me)
        self.assertIn(H.card_path(uid), me)
        self.assertNotIn(email.split("@")[0] + "@", c.get(H.card_path(uid)).text.replace(email, ""))  # belt
        r = c.get(H.card_path(uid))
        self.assertEqual(r.status, 200)
        self.assertIn("Sam", r.text)
        self.assertNotIn("Message Sam", r.text)
        self.assertNotIn("Block this member", r.text)
        self.assertIn("how signed-in members see your card", r.text)

    def test_enumerable_id_and_bad_token_are_404(self):
        c, email, uid, did = member()
        viewer, *_ = member("Alex", dog="Pepper")
        self.assertEqual(viewer.get(f"/humans/{uid}").status, 404)
        self.assertEqual(viewer.get(f"/humans/{uid}-" + ("0" * 20)).status, 404)
        self.assertNotIn("Sam", viewer.get(f"/humans/{uid}").text)
        self.assertEqual(viewer.get("/humans/not-a-token").status, 404)

    def test_blocks_both_ways_look_like_missing(self):
        a, ae, aid, _ = member("Sam")
        b, be, bid, _ = member("Alex", dog="Pepper")
        path = H.card_path(aid)
        self.assertEqual(b.get(path).status, 200)
        MS.block(aid, bid)  # Sam blocked Alex
        r = b.get(path)
        self.assertEqual(r.status, 404)
        self.assertNotIn("Sam", r.text)
        self.assertNotIn(ae, r.text)
        MS.unblock(aid, bid)
        MS.block(bid, aid)  # Alex blocked Sam
        r = b.get(path)
        self.assertEqual(r.status, 404)
        self.assertNotIn("Sam", r.text)

    def test_hidden_and_private_dogs_are_omitted(self):
        owner, email, uid, lily = member("Sam", dog="Lily")
        secret = new_dog(owner, "Secret", visibility="private")
        A.q("UPDATE dogs SET hidden=1 WHERE id=:i", i=secret)
        # another dog that's members-only is visible to signed-in members
        pals = new_dog(owner, "Pals", visibility="members")
        viewer, *_ = member("Alex", dog="Pepper")
        text = viewer.get(H.card_path(uid)).text
        self.assertIn("Lily", text)
        self.assertIn("Pals", text)
        self.assertNotIn("Secret", text)

    def test_private_card_setting_hides_details_keeps_message(self):
        owner, email, uid, _ = member("Sam", town="Glen Cove")
        # turn the card off; leave other flags
        page = owner.get("/me/privacy").text
        self.assertIn("Show my card to members", page)
        data = {}
        for m in re.finditer(r'<input[^>]*type="checkbox"[^>]*name="([\w]+)"[^>]*value="1"[^>]*checked', page):
            if m.group(1) != "priv_card":
                data[m.group(1)] = "1"
        for m in re.finditer(r'<input[^>]*type="radio"[^>]*name="([\w]+)"[^>]*value="([\w]+)"[^>]*checked', page):
            data[m.group(1)] = m.group(2)
        m = re.search(r'<select[^>]*name="priv_default_vis".*?<option value="(\w+)" selected', page, re.S)
        if m:
            data["priv_default_vis"] = m.group(1)
        self.assertEqual(owner.post("/me/privacy", data).status, 303)
        self.assertEqual(PV.settings(uid)["priv_card"], 0)
        viewer, *_ = member("Alex", dog="Pepper")
        r = viewer.get(H.card_path(uid))
        self.assertEqual(r.status, 200)
        self.assertIn("This member keeps their card private", r.text)
        self.assertNotIn("person in town.", r.text)
        self.assertNotIn("Glen Cove", r.text)
        self.assertIn("Message", r.text)
        # owner still sees their own full card
        mine = owner.get(H.card_path(uid)).text
        self.assertIn("Sam", mine)
        self.assertIn("Lily", mine)

    def test_default_is_on_and_schema_adds_column(self):
        _, _, uid, _ = member("Sam")
        self.assertEqual(PV.settings(uid)["priv_card"], 1)
        self.assertIn("priv_card", PV.FLAG_KEYS)
        self.assertIn("priv_card", PV.SET_COLS)

    def test_dog_page_and_meetup_host_link_to_the_card(self):
        owner, email, uid, did = member("Sam")
        slug = A.one("SELECT slug FROM dogs WHERE id=:d", d=did)[0]
        path = H.card_path(uid)
        # signed-out dog page: link goes to sign-in
        dog = Client().get(f"/dogs/{slug}").text
        self.assertIn("Lily's human", dog)
        self.assertIn("Sam", dog)
        self.assertIn("/signin", dog)
        # signed-in viewer: direct card link
        viewer, *_ = member("Alex", dog="Pepper")
        dog = viewer.get(f"/dogs/{slug}").text
        self.assertIn(path, dog)
        mid, _ = create_meetup(owner, title="Morning romp")
        page = viewer.get(meetweb.meetup_path(M.get(mid))).text
        self.assertIn("Hosted by", page)
        self.assertIn(path, page)
        self.assertIn("Sam", page)

    def test_sitemap_and_robots_exclude_cards(self):
        _, _, uid, _ = member("Sam")
        path = H.card_path(uid)
        sm = Client().get("/sitemap.xml").text
        self.assertNotIn("/humans", sm)
        self.assertNotIn(path, sm)
        rb = Client().get("/robots.txt").text
        self.assertIn("Disallow: /humans", rb)

    def test_report_and_block_from_the_card(self):
        owner, email, uid, _ = member("Sam")
        viewer, ve, vid, _ = member("Alex", dog="Pepper")
        path = H.card_path(uid)
        r = viewer.post(path + "/report", {"reason": "Safety concern", "details": "Nope"})
        self.assertEqual(r.status, 303)
        self.assertTrue(r.headers["Location"].startswith(path))
        rows = A.q("SELECT reason, reported_user_id, message_id FROM message_reports WHERE reporter_user_id=:u", u=vid)
        self.assertTrue(rows)
        self.assertEqual(rows[0][0], "Safety concern")
        self.assertEqual(rows[0][1], uid)
        self.assertIsNone(rows[0][2])
        r = viewer.post(path + "/block", {})
        self.assertEqual(r.status, 303)
        self.assertTrue(MS.blocked(vid, uid))
        self.assertEqual(viewer.get(path).status, 404)
