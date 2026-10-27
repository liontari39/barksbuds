"""Privacy settings: per-dog visibility (public / members / pack-mates / private) for every kind of viewer,
search + directory exclusions, search engines (noindex + sitemap), owner detail toggles, check-ins, birthday
shout-outs, who can message, photo access, the settings page and migration defaults for existing accounts.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import os, re, sys, unittest
from datetime import date
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, jpeg_with_exif, RUN  # noqa: E402
import accounts as A  # noqa: E402
import messages as MS  # noqa: E402
import privacy as PV  # noqa: E402
import communityweb  # noqa: E402

RUN_ID = "n-006"
_n = [0]


def setUpModule():
    communityweb.AUTO_JOBS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def member(name, dogs=(), **profile):
    _n[0] += 1
    c = Client(f"10.88.{_n[0] // 200}.{_n[0] % 200 + 1}")
    email = f"{name.lower()}{_n[0]}-{RUN}@example.com"
    sign_in(c, email)
    p = {"display_name": name, "area": "Nassau", "town": "Manhasset", "bio": ""}
    p.update(profile)
    c.post("/me/profile", p)
    ids = [new_dog(c, **d) for d in dogs]
    uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
    return c, email, uid, ids


def slug(did):
    return A.one("SELECT slug FROM dogs WHERE id=:d", d=did)[0]


def anon():
    _n[0] += 1
    return Client(f"10.89.{_n[0] // 200}.{_n[0] % 200 + 1}")


def save(c, **over):
    """POST /me/privacy with the current page's values, overridden."""
    page = c.get("/me/privacy").text
    data = {}
    for m in re.finditer(r'<input[^>]*type="radio"[^>]*name="([\w]+)"[^>]*value="([\w]+)"[^>]*checked', page):
        data[m.group(1)] = m.group(2)
    for m in re.finditer(r'<input[^>]*type="checkbox"[^>]*name="([\w]+)"[^>]*value="1"[^>]*checked', page):
        data[m.group(1)] = "1"
    m = re.search(r'<select[^>]*name="priv_default_vis".*?<option value="(\w+)" selected', page, re.S)
    if m:
        data["priv_default_vis"] = m.group(1)
    for k, v in over.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    r = c.post("/me/privacy", data)
    assert r.status == 303 and r.headers["Location"] == "/me/privacy?m=privacy", (r.status, r.text[:300])
    return data


def private_page(r):
    return r.status == 403 and "This profile is private" in r.text


class VisibilityMatrix(unittest.TestCase):
    """Every visibility level x logged-out / member / pack-mate / owner / co-owner / blocked."""

    @classmethod
    def setUpClass(cls):
        tag = RUN.lower()
        cls.breed = f"Zbreed{tag}"
        cls.owner, _, cls.ouid, (cls.dog,) = member("Ophelia", dogs=[dict(name=f"Pip{tag}", breed=cls.breed)])
        cls.member_c, _, cls.muid, _ = member("Max")
        cls.mate_c, _, cls.pmuid, (cls.mate_dog,) = member("Pam", dogs=[dict(name=f"Pamdog{tag}")])
        cls.co_c, cls.co_email, cls.couid, _ = member("Cora")
        cls.blocked_c, _, cls.buid, _ = member("Bart")
        # pack-mates: Pam joins Ophelia's open pack
        import test_packs as TP
        cls.pack, _ = TP.make_pack(cls.owner, dogs=[cls.dog], name=f"Privacy pack {tag}")
        r = TP.join(cls.mate_c, cls.pack, [cls.mate_dog])
        assert r.status == 303, r.status
        # co-owner (same row the invite flow writes)
        A.q("INSERT INTO dog_owners(dog_id,user_id,role,created_at) VALUES(:d,:u,'co-owner',:t)", d=cls.dog, u=cls.couid, t=A.now())
        MS.block(cls.ouid, cls.buid)
        cls.slug = slug(cls.dog)

    def viewers(self):
        return {"logged_out": anon(), "member": self.member_c, "packmate": self.mate_c,
                "owner": self.owner, "coowner": self.co_c, "blocked": self.blocked_c}

    EXPECT = {"public": {"logged_out", "member", "packmate", "owner", "coowner", "blocked"},
              "members": {"member", "packmate", "owner", "coowner"},
              "pack": {"packmate", "owner", "coowner"},
              "private": {"owner", "coowner"}}

    def test_matrix(self):
        self.assertTrue(PV.Viewer(self.muid).signed_in)
        self.assertIn(self.ouid, PV.Viewer(self.pmuid).packmates())
        try:
            for vis, allowed in self.EXPECT.items():
                PV.set_visibility(self.dog, vis)
                for who, c in self.viewers().items():
                    with self.subTest(vis=vis, viewer=who):
                        r = c.get(f"/dogs/{self.slug}")
                        if who in allowed:
                            self.assertEqual(r.status, 200)
                            self.assertIn(self.breed, r.text)
                        else:
                            self.assertTrue(private_page(r), (r.status, r.text[:200]))
                            body = r.text.lower().replace(self.slug.lower(), "")  # the sign-in link carries the URL they typed
                            self.assertNotIn(self.breed.lower(), body)  # nothing leaks
                            self.assertNotIn(f"pip{RUN.lower()}", body)
                            self.assertNotIn("ophelia", body)
                            self.assertIn('content="noindex"', r.text)
                            if who == "logged_out":
                                self.assertIn("Sign in", r.text)
        finally:
            PV.set_visibility(self.dog, "public")

    def test_can_view_unit(self):
        d = A.dog_by_id(self.dog)
        ids = {"logged_out": None, "member": self.muid, "packmate": self.pmuid, "owner": self.ouid,
               "coowner": self.couid, "blocked": self.buid}
        try:
            for vis, allowed in self.EXPECT.items():
                PV.set_visibility(self.dog, vis)
                d = A.dog_by_id(self.dog)
                for who, uid in ids.items():
                    self.assertEqual(PV.can_view(d, PV.Viewer(uid)), who in allowed, (vis, who))
        finally:
            PV.set_visibility(self.dog, "public")

    def test_lists_hide_dogs_the_viewer_cant_see(self):
        tag = RUN.lower()
        try:
            PV.set_visibility(self.dog, "pack")
            # pack page lists Pip for pack-mates; a member sees a count instead
            import packweb, packs as P
            path = packweb.pack_path(P.get(self.pack))
            self.assertIn(f"Pip{tag}", self.mate_c.get(path).text)
            page = self.member_c.get(path).text
            self.assertNotIn(f"Pip{tag}", page)
            self.assertIn("with a private profile", page)
            # directory / search
            self.assertNotIn(f"/dogs/{self.slug}", self.member_c.get(f"/search?q={quote('pip' + tag)}").text)
            self.assertIn(f"/dogs/{self.slug}", self.mate_c.get(f"/search?q={quote('pip' + tag)}").text)
            self.assertNotIn(f"/dogs/{self.slug}\"", self.member_c.get("/dogs?area=Nassau").text)
        finally:
            PV.set_visibility(self.dog, "public")


class SearchAndIndexing(unittest.TestCase):
    def test_search_setting(self):
        tag = RUN.lower()
        c, _, uid, (did,) = member("Sally", dogs=[dict(name=f"Sniff{tag}")])
        s = slug(did)
        q = f"/search?q={quote('sniff' + tag)}"
        other, _, _, _ = member("Sven")
        # new accounts: members only, findable by members, not by signed-out visitors or search engines
        self.assertEqual(A.dog_by_id(did)["visibility"], "public")  # test helper picks public explicitly
        self.assertIn(f"/dogs/{s}", other.get(q).text)
        self.assertIn(f"/dogs/{s}", anon().get(q).text)
        save(c, priv_search="members")
        self.assertIn(f"/dogs/{s}", other.get(q).text)
        self.assertNotIn(f"/dogs/{s}", anon().get(q).text)
        self.assertNotIn(f"/dogs/{s}\"", anon().get("/dogs?area=Nassau").text)
        save(c, priv_search="none")
        self.assertNotIn(f"/dogs/{s}", other.get(q).text)
        self.assertNotIn(f"/dogs/{s}", anon().get(q).text)
        # the profile itself still opens for people allowed to see it
        self.assertEqual(anon().get(f"/dogs/{s}").status, 200)
        save(c, priv_search="everyone")
        self.assertIn(f"/dogs/{s}", anon().get(q).text)

    def test_noindex_and_sitemap(self):
        tag = RUN.lower()
        c, _, uid, (did,) = member("Nina", dogs=[dict(name=f"Nox{tag}")])
        s = slug(did)
        sm = lambda: anon().get("/sitemap.xml").text
        # new account: search engines off by default
        self.assertIn('content="noindex"', anon().get(f"/dogs/{s}").text)
        self.assertNotIn(f"/dogs/{s}<", sm())
        save(c, priv_index="1", priv_search="everyone")
        self.assertIn('content="index,follow"', anon().get(f"/dogs/{s}").text)
        self.assertIn(f"/dogs/{s}<", sm())
        # a non-public dog is never indexed even with the toggle on
        PV.set_visibility(did, "members")
        self.assertNotIn(f"/dogs/{s}<", sm())
        self.assertIn('content="noindex"', c.get(f"/dogs/{s}").text)
        PV.set_visibility(did, "public")
        # search limited to members => not indexed either
        save(c, priv_search="members")
        self.assertNotIn(f"/dogs/{s}<", sm())
        self.assertIn('content="noindex"', anon().get(f"/dogs/{s}").text)


class DetailsCheckinsCelebrations(unittest.TestCase):
    def test_detail_toggles(self):
        tag = RUN.lower()
        bd = date.today().replace(year=date.today().year - 4).isoformat()
        c, _, uid, (did,) = member(f"Dana{tag}", dogs=[dict(name=f"Dot{tag}", birthday=bd, age="")], town="Oyster Bay")
        s = slug(did)
        page = anon().get(f"/dogs/{s}").text
        self.assertIn("Oyster Bay", page)
        self.assertIn(f"Dana{tag}", page)
        save(c, priv_town=None, priv_birthday=None, priv_owner_name=None)
        page = anon().get(f"/dogs/{s}").text
        self.assertEqual(anon().get(f"/dogs/{s}").status, 200)
        self.assertNotIn("Oyster Bay", page)
        self.assertNotIn(f"Dana{tag}", page)
        self.assertNotIn(bd, page)
        self.assertNotIn("4 years", page)
        self.assertNotIn(f"Dana{tag}", anon().get(f"/search?q={quote('dot' + tag)}").text)
        # the owner still sees everything
        own = c.get(f"/dogs/{s}").text
        self.assertIn("Oyster Bay", own)
        self.assertIn("Who can see this page", own)
        # birthday shout-outs: hidden when dates are hidden, or shout-outs are off, or the dog isn't visible
        V = PV.SIGNED_OUT
        d = A.dog_by_id(did)
        self.assertFalse(PV.can_celebrate(d, V, "birthday"))
        save(c, priv_birthday="1", priv_town="1", priv_owner_name="1")
        self.assertTrue(PV.can_celebrate(A.dog_by_id(did), V, "birthday"))
        self.assertIn(f"Dot{tag}", anon().get("/community?area=Nassau").text)
        save(c, priv_celebrate=None)
        self.assertFalse(PV.can_celebrate(A.dog_by_id(did), V, "birthday"))
        self.assertNotIn(f"Dot{tag}", anon().get("/community?area=Nassau").text)
        save(c, priv_celebrate="1")
        PV.set_visibility(did, "members")
        self.assertNotIn(f"Dot{tag}", anon().get("/community?area=Nassau").text)
        PV.set_visibility(did, "public")

    def test_checkins_hidden(self):
        tag = RUN.lower()
        c, _, uid, (did,) = member("Hank", dogs=[dict(name=f"Hush{tag}")])
        save(c, show_checkins=None)
        self.assertTrue(PV.settings(uid)["checkins_hidden"])

        r = c.post(f"/runs/{RUN_ID}/checkin", {"dogs": [str(did)]})  # even without anon=1
        self.assertEqual(r.status, 303)
        try:
            for who in (anon(), member("Ivy")[0]):
                r = who.get(f"/runs/{RUN_ID}")
                while r.status in (301, 302, 303):
                    r = who.get(r.headers["Location"])
                self.assertNotIn(f"Hush{tag}", r.text)
        finally:
            c.post(f"/runs/{RUN_ID}/leave", {})
        save(c, show_checkins="1")
        self.assertFalse(PV.settings(uid)["checkins_hidden"])


class Messaging(unittest.TestCase):
    def test_who_can_message(self):
        a, _, auid, _ = member("Amy")
        b, _, buid, (bdog,) = member("Ben", dogs=[dict(name="Bendog")])
        x, _, xuid, (xdog,) = member("Xia", dogs=[dict(name="Xiadog")])
        # default: anyone
        self.assertTrue(PV.can_message(auid, buid))
        save(b, priv_msg="none")
        self.assertFalse(PV.can_message(auid, buid))
        r = a.post(f"/messages/to/{buid}", {"body": "hi there"})
        self.assertEqual(r.status, 403)
        self.assertIn("accepting new messages", r.text)
        self.assertIn("accepting new messages", a.get(f"/messages/to/{buid}").text)
        self.assertNotIn(f'href="/messages/to/{buid}"', a.get(f"/dogs/{slug(bdog)}").text)
        # Ben can still start a conversation; Amy can then reply, and the conversation stays readable
        r = b.post(f"/messages/to/{auid}", {"body": "hello Amy"})
        self.assertEqual(r.status, 303)
        cid = int(re.match(r"/messages/(\d+)", r.headers["Location"]).group(1))
        self.assertTrue(PV.can_message(auid, buid))
        self.assertEqual(a.post(f"/messages/{cid}", {"body": "hi back"}).status, 303)
        # pack-mates only
        save(b, priv_msg="pack")
        self.assertFalse(PV.can_message(xuid, buid))
        import meetups as M, test_meetups as TM
        mid, _ = TM.create(b)
        TM.rsvp(b, mid, [bdog])
        self.assertEqual(TM.rsvp(x, mid, [xdog]).status, 303)
        self.assertTrue(PV.can_message(xuid, buid))
        # blocks still win
        MS.block(buid, xuid)
        self.assertNotIn(f'href="/messages/to/{buid}"', x.get(f"/dogs/{slug(bdog)}").text)
        self.assertNotEqual(x.post(f"/messages/to/{buid}", {"body": "hey"}).status, 303)
        MS.unblock(buid, xuid)


class Photos(unittest.TestCase):
    def test_private_photo_needs_access_or_signature(self):
        tag = RUN.lower()
        c, _, uid, (did,) = member("Pia", dogs=[dict(name=f"Pic{tag}")])
        r = c.upload(f"/me/dogs/{did}/photos", [("a.jpg", jpeg_with_exif(), "image/jpeg")])
        self.assertEqual(r.status, 303)
        pid = A.one("SELECT id FROM photos WHERE dog_id=:d", d=did)[0]
        pub = anon().get(f"/p/{pid}.webp")
        self.assertEqual(pub.status, 200)
        self.assertIn("public", pub.headers["Cache-Control"])
        PV.set_visibility(did, "private")
        self.assertEqual(anon().get(f"/p/{pid}.webp").status, 404)
        self.assertEqual(member("Quin")[0].get(f"/p/{pid}.webp").status, 404)
        own = c.get(f"/p/{pid}.webp")
        self.assertEqual(own.status, 200)
        self.assertTrue(own.headers["Cache-Control"].startswith("private"))
        self.assertEqual(anon().get(PV.signed_photo(pid)).status, 200)
        self.assertEqual(anon().get(f"/p/{pid}.webp?k=0000000000").status, 404)
        PV.set_visibility(did, "public")


class SettingsPage(unittest.TestCase):
    def test_page_login_defaults_and_save(self):
        r = anon().get("/me/privacy")
        self.assertIn(r.status, (302, 303))
        c, _, uid, (did,) = member("Rita", dogs=[dict(name="Ritadog", visibility="")])
        # new accounts: privacy-friendly defaults
        st = PV.settings(uid)
        self.assertEqual((st["priv_default_vis"], st["priv_search"], st["priv_index"], st["priv_msg"]),
                         ("members", "everyone", 0, "everyone"))
        self.assertEqual(A.dog_by_id(did)["visibility"], "members")  # a new dog takes the account default
        page = c.get("/me/privacy").text
        for anchor in ('id="profiles"', 'id="search"', 'id="details"', 'id="messages"', f'name="vis_{did}"'):
            self.assertIn(anchor, page)
        self.assertIn('href="/me/privacy"', c.get("/me").text)
        save(c, **{f"vis_{did}": "private"})
        self.assertEqual(A.dog_by_id(did)["visibility"], "private")
        save(c, priv_default_vis="pack", apply_all="1")
        self.assertEqual(A.dog_by_id(did)["visibility"], "pack")
        # bad values are ignored; csrf required
        save(c, priv_search="nonsense", **{f"vis_{did}": "nonsense"})
        self.assertEqual(PV.settings(uid)["priv_search"], "everyone")
        self.assertEqual(A.dog_by_id(did)["visibility"], "pack")
        self.assertEqual(c.post("/me/privacy", {"priv_search": "none"}, csrf=False).status, 403)
        # someone else's dog can't be changed through the form
        o, _, ouid, (odog,) = member("Omar", dogs=[dict(name="Omardog")])
        c.post("/me/privacy", {f"vis_{odog}": "private"})
        self.assertEqual(A.dog_by_id(odog)["visibility"], "public")

    def test_existing_accounts_keep_legacy_public_defaults(self):
        t = A.now()
        email = f"legacy-{RUN}@example.com"
        uid = A.one("INSERT INTO users(email,display_name,created_at) VALUES(:e,'Old',:t) RETURNING id", e=email, t=t)[0]
        A.q("""INSERT INTO dogs(user_id,slug,name,created_at,updated_at) VALUES(:u,:s,'Olddog',:t,:t)""",
            u=uid, s=f"olddog-{RUN.lower()}", t=t)
        st = PV.settings(uid)
        for k, v in PV.LEGACY.items():
            self.assertEqual(st[k], v, k)
        did = A.one("SELECT id FROM dogs WHERE user_id=:u", u=uid)[0]
        self.assertEqual(A.dog_by_id(did)["visibility"], "public")
        # running the migration again is a no-op
        PV.init_schema(A.STORE)
        self.assertEqual(PV.settings(uid)["priv_index"], 1)


if __name__ == "__main__":
    unittest.main()
