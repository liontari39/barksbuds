"""End-to-end tests for accounts, dog profiles, photos, reports and the existing waitlist.

Run:   python3 -m unittest discover -s tests -v
       TEST_DATABASE_URL=postgresql://... python3 -m unittest discover -s tests -v   (same tests against Postgres)
Starts the real server in a thread with a temporary data dir and EMAIL_PROVIDER=file (emails land in an outbox folder).
"""
import glob, http.client, io, json, os, re, sys, tempfile, threading, time, unittest, uuid
from urllib.parse import urlencode, urlsplit, parse_qs

TMP = tempfile.mkdtemp(prefix="bbtest-")
os.environ.update(DATA_DIR=TMP, EMAIL_PROVIDER="file", EMAIL_FROM="hello@barksbuds.app", ADMIN_KEY="test-admin-key",
                  SITE_URL="", DATABASE_URL=os.environ.get("TEST_DATABASE_URL", ""))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server  # noqa: E402
import accounts as A  # noqa: E402
from PIL import Image  # noqa: E402

RUN = uuid.uuid4().hex[:8]  # keeps emails/names unique when the Postgres DB is reused


def setUpModule():
    global PORT, HTTPD
    st = server.init_app()
    if os.environ.get("TEST_DATABASE_URL"):  # clean slate for a reused test database
        for t in ("reports", "photos", "dogs", "sessions", "login_tokens", "users"):
            st.q(f"DELETE FROM {t}")
    HTTPD = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    PORT = HTTPD.server_address[1]
    threading.Thread(target=HTTPD.serve_forever, daemon=True).start()


def tearDownModule():
    HTTPD.shutdown()


def jpeg_with_exif(color=(200, 30, 30), size=(900, 700)):
    im = Image.new("RGB", size, color)
    ex = Image.Exif()
    ex[0x010F] = "SecretCam"           # Make
    ex[0x8825] = {2: (40.0, 47.0, 0.0)}  # GPS IFD (latitude)
    b = io.BytesIO()
    im.save(b, "JPEG", exif=ex.tobytes())
    return b.getvalue()


class Client:
    def __init__(self, ip="10.0.0.1"):
        self.cookies, self.ip = {}, ip

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        h = {"Host": f"127.0.0.1:{PORT}", "X-Forwarded-For": self.ip}
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        r.body = r.read()
        r.text = r.body.decode("utf-8", "replace")
        r.set_cookies = r.headers.get_all("Set-Cookie") or []
        for sc in r.set_cookies:
            k, v = sc.split(";")[0].split("=", 1)
            if "Max-Age=0" in sc:
                self.cookies.pop(k, None)
            else:
                self.cookies[k] = v
        c.close()
        return r

    def get(self, path):
        return self.req("GET", path)

    def csrf(self):
        for path in ("/signin", "/me"):  # /signin redirects once signed in; /me has the sign-out form
            m = re.search(r'name="csrf" value="([0-9a-f]+)"', self.get(path).text)
            if m:
                return m.group(1)
        raise AssertionError("no csrf token")

    def post(self, path, data, csrf=True, headers=None):
        data = dict(data)
        if csrf and "csrf" not in data:
            data["csrf"] = self.csrf()
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        h.update(headers or {})
        return self.req("POST", path, urlencode(data, doseq=True), h)

    def upload(self, path, files):
        bnd = "----bb" + uuid.uuid4().hex
        parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="csrf"\r\n\r\n{self.csrf()}\r\n'.encode()]
        for name, data, ctype in files:
            parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="photos"; filename="{name}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
        parts.append(f"--{bnd}--\r\n".encode())
        return self.req("POST", path, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={bnd}"})


def last_link(email):
    files = sorted(glob.glob(os.path.join(TMP, "outbox", "*-signin-*.json")), key=os.path.getmtime)
    for fn in reversed(files):
        d = json.load(open(fn))
        if d["to"] == email:
            return re.search(r"(https?://\S+/auth\?t=[\w-]+)", d["text"]).group(1), d
    return None, None


def wait_link(email, prev=None):
    for _ in range(50):
        link, d = last_link(email)
        if link and link != prev:
            return link, d
        time.sleep(0.1)
    raise AssertionError("no sign-in email for " + email)


def sign_in(client, email):
    r = client.post("/signin", {"email": email})
    assert r.status == 200 and "Check your email" in r.text, (r.status, r.text[:300])
    link, _ = wait_link(email)
    p = urlsplit(link)
    client.get(p.path + "?" + p.query)
    r = client.post("/auth", {"t": parse_qs(p.query)["t"][0]})
    assert r.status == 303 and r.headers["Location"].startswith("/me"), (r.status, r.text[:300])
    return r


def new_dog(client, name="Biscuit", **extra):
    data = {"name": name, "breed": "Beagle", "age": "4", "size": "medium", "sex": "female",
            "temperament": ["Gentle", "Loves people"], "play_style": ["Chaser"], "vaccinated": "1",
            "runs": ["q-001"], "bio": "Loves the run."}
    data.update(extra)
    r = client.post("/me/dogs/new", data)
    assert r.status == 303, (r.status, r.text[:500])
    return int(re.search(r"/me/dogs/(\d+)/edit", r.headers["Location"]).group(1))


class AuthTests(unittest.TestCase):
    def test_magic_link_flow(self):
        c, email = Client("10.1.0.1"), f"owner-{RUN}@example.com"
        r = c.post("/signin", {"email": email.upper()})
        self.assertEqual(r.status, 200)
        self.assertIn("Check your email", r.text)
        link, msg = wait_link(email)
        self.assertEqual(msg["subject"], "Your BarksBuds sign-in link")
        self.assertTrue(glob.glob(os.path.join(TMP, "outbox", "*-signin-*.html")))
        raw = parse_qs(urlsplit(link).query)["t"][0]
        # only a hash of the token is stored
        self.assertIsNone(A.one("SELECT id FROM login_tokens WHERE token_hash=:t", t=raw))
        self.assertIsNotNone(A.one("SELECT id FROM login_tokens WHERE token_hash=:t", t=A.sha(raw)))
        # GET does not sign in (safe for link scanners); it renders an auto-submitting form
        g = c.get("/auth?t=" + raw)
        self.assertEqual(g.status, 200)
        self.assertNotIn("bb_session", c.cookies)
        r = c.post("/auth", {"t": raw})
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"], "/me?m=welcome")
        sc = [s for s in r.set_cookies if s.startswith("bb_session=")][0]
        for flag in ("HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, sc)
        self.assertIn(email, c.get("/me").text)
        # single use
        c2 = Client("10.1.0.2")
        c2.get("/auth?t=" + raw)
        r = c2.post("/auth", {"t": raw})
        self.assertEqual(r.status, 400)
        self.assertIn("already used", r.text)
        self.assertNotIn("bb_session", c2.cookies)
        # sign out kills the session server-side
        old = c.cookies["bb_session"]
        r = c.post("/signout", {})
        self.assertEqual(r.status, 303)
        self.assertEqual(c.get("/me").status, 303)
        c3 = Client("10.1.0.3")
        c3.cookies["bb_session"] = old
        self.assertEqual(c3.get("/me").status, 303)

    def test_secure_cookie_behind_https(self):
        c, email = Client("10.1.1.1"), f"https-{RUN}@example.com"
        c.post("/signin", {"email": email})
        raw = parse_qs(urlsplit(wait_link(email)[0]).query)["t"][0]
        tok = c.csrf()
        r = c.req("POST", "/auth", urlencode({"t": raw, "csrf": tok}),
                  {"Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-Proto": "https"})
        sc = [s for s in r.set_cookies if s.startswith("bb_session=")][0]
        self.assertIn("Secure", sc)

    def test_expired_link(self):
        email = f"late-{RUN}@example.com"
        raw = A.create_login_token(email, "10.1.2.1")
        A.q("UPDATE login_tokens SET expires_at=:t WHERE token_hash=:h", t=int(time.time()) - 1, h=A.sha(raw))
        c = Client("10.1.2.1")
        self.assertIn("expired", c.get("/auth?t=" + raw).text)
        r = c.post("/auth", {"t": raw})
        self.assertEqual(r.status, 400)
        self.assertNotIn("bb_session", c.cookies)

    def test_garbage_token(self):
        c = Client("10.1.3.1")
        self.assertEqual(c.post("/auth", {"t": "nope"}).status, 400)
        self.assertEqual(c.get("/auth?t=").status, 400)

    def test_rate_limits(self):
        c, email = Client("10.1.4.1"), f"spam-{RUN}@example.com"
        self.assertEqual(c.post("/signin", {"email": email}).status, 200)
        r = c.post("/signin", {"email": email})  # second link within 45s
        self.assertEqual(r.status, 429)
        with self.assertRaises(A.RateLimited):
            for i in range(30):  # per-IP cap across different emails
                A.create_login_token(f"x{i}-{RUN}@example.com", "10.9.9.9")

    def test_bad_email_and_honeypot(self):
        c = Client("10.1.5.1")
        self.assertEqual(c.post("/signin", {"email": "not-an-email"}).status, 422)
        r = c.post("/signin", {"email": f"bot-{RUN}@example.com", "website": "x"})
        self.assertEqual(r.status, 200)
        time.sleep(0.3)
        self.assertIsNone(last_link(f"bot-{RUN}@example.com")[0])

    def test_csrf_required(self):
        c = Client("10.1.6.1")
        sign_in(c, f"csrf-{RUN}@example.com")
        self.assertEqual(c.post("/me/profile", {"display_name": "X", "area": "Queens"}, csrf=False).status, 403)
        self.assertEqual(c.post("/me/profile", {"display_name": "X", "area": "Queens", "csrf": "0" * 40}).status, 403)
        r = c.post("/me/profile", {"display_name": "X", "area": "Queens"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        self.assertEqual(c.post("/signin", {"email": "a@b.co"}, csrf=False).status, 403)

    def test_waitlist_signup_is_linked(self):
        email = f"wl-{RUN}@example.com"
        c = Client("10.1.7.1")
        r = c.req("POST", "/api/waitlist", json.dumps({"first_name": "Dana", "email": email, "dog_name": "Pepper"}),
                  {"Content-Type": "application/json"})
        self.assertIn(r.status, (200, 201))
        sign_in(c, email)
        page = c.get("/me/profile").text
        self.assertIn('value="Dana"', page)
        self.assertIsNotNone(A.one("SELECT waitlist_id FROM users WHERE email=:e", e=email)[0])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.c = Client("10.2.0.%d" % (hash(self.id()) % 200 + 1))
        self.email = f"p-{uuid.uuid4().hex[:6]}-{RUN}@example.com"
        sign_in(self.c, self.email)

    def test_owner_profile_validation(self):
        r = self.c.post("/me/profile", {"display_name": "Sam", "area": "Atlantis", "town": "", "bio": ""})
        self.assertEqual(r.status, 422)
        r = self.c.post("/me/profile", {"display_name": "Sam", "area": "Brooklyn", "town": "Park Slope", "bio": "Hi"})
        self.assertEqual(r.status, 303)
        u = A.one("SELECT display_name, area, town FROM users WHERE email=:e", e=self.email)
        self.assertEqual(tuple(u), ("Sam", "Brooklyn", "Park Slope"))

    def test_dog_crud_public_page_and_escaping(self):
        self.c.post("/me/profile", {"display_name": "<b>Sam</b>", "area": "Queens", "town": "Astoria", "bio": ""})
        self.assertEqual(self.c.post("/me/dogs/new", {"name": ""}).status, 422)
        self.assertEqual(self.c.post("/me/dogs/new", {"name": "Rex", "age": "99"}).status, 422)
        self.assertEqual(self.c.post("/me/dogs/new", {"name": "Rex", "birthday": "2999-01-01"}).status, 422)
        dog_id = new_dog(self.c, name='Rex<script>alert(1)</script>', bio='"><img src=x onerror=alert(1)>')
        d = A.dog_by_id(dog_id)
        self.assertEqual(d["fav_runs"], ["q-001"])
        self.assertTrue(d["vaccinated"])
        pub = Client("10.2.9.9").get("/dogs/" + d["slug"])
        self.assertEqual(pub.status, 200)
        self.assertNotIn("<script>alert(1)", pub.text)
        self.assertNotIn("<img src=x", pub.text)
        self.assertIn("&lt;script&gt;", pub.text)
        self.assertIn("&lt;b&gt;Sam&lt;/b&gt;", pub.text)
        self.assertNotIn(self.email, pub.text)
        self.assertIn('property="og:title"', pub.text)
        self.assertIn("Astoria", pub.text)
        self.assertIn("4 years old", pub.text)
        # browse with area filter
        self.assertIn(f'/dogs/{d["slug"]}"', Client().get("/dogs?area=Queens").text)
        self.assertNotIn(f'/dogs/{d["slug"]}"', Client().get("/dogs?area=Suffolk").text)
        self.assertIn(f'/dogs/{d["slug"]}"', Client().get("/dogs?region=nyc").text)
        self.assertNotIn(self.email, Client().get("/dogs").text)
        # edit
        r = self.c.post(f"/me/dogs/{dog_id}/edit", {"name": "Rex", "birthday": "2020-05-01", "temperament": ["Chill"]})
        self.assertEqual(r.status, 303)
        d = A.dog_by_id(dog_id)
        self.assertEqual((d["name"], d["birthday"], d["temperament"], d["slug"]), ("Rex", "2020-05-01", ["Chill"], d["slug"]))
        # someone else can't touch it
        other = Client("10.2.8.8")
        sign_in(other, f"other-{uuid.uuid4().hex[:6]}-{RUN}@example.com")
        self.assertEqual(other.get(f"/me/dogs/{dog_id}/edit").status, 404)
        self.assertEqual(other.post(f"/me/dogs/{dog_id}/edit", {"name": "Hacked"}).status, 404)
        self.assertEqual(other.post(f"/me/dogs/{dog_id}/delete", {}).status, 404)
        self.assertEqual(A.dog_by_id(dog_id)["name"], "Rex")
        # delete
        self.assertEqual(self.c.post(f"/me/dogs/{dog_id}/delete", {}).status, 303)
        self.assertIsNone(A.dog_by_id(dog_id))
        self.assertEqual(Client().get("/dogs/" + d["slug"]).status, 404)

    def test_slugs_are_unique(self):
        a, b = new_dog(self.c, name="Luna"), new_dog(self.c, name="Luna")
        self.assertNotEqual(A.dog_by_id(a)["slug"], A.dog_by_id(b)["slug"])

    def test_photo_upload_strips_exif_and_rejects_non_images(self):
        dog_id = new_dog(self.c, name="Pixel")
        raw = jpeg_with_exif()
        self.assertIn(b"SecretCam", raw)
        r = self.c.upload(f"/me/dogs/{dog_id}/photos", [("a.jpg", raw, "image/jpeg"), ("b.jpg", jpeg_with_exif((0, 90, 200)), "image/jpeg")])
        self.assertEqual(r.status, 303)
        self.assertNotIn("pe=", r.headers["Location"])
        photos = A.gallery(dog_id)
        self.assertEqual(len(photos), 2)
        full = Client().get(f"/p/{photos[0]['id']}.jpg")
        self.assertEqual(full.status, 200)
        self.assertEqual(full.headers["Content-Type"], "image/jpeg")
        self.assertNotIn(b"SecretCam", full.body)
        self.assertFalse(dict(Image.open(io.BytesIO(full.body)).getexif()))
        thumb = Client().get(f"/p/{photos[0]['id']}.webp")
        self.assertEqual(thumb.headers["Content-Type"], "image/webp")
        self.assertEqual(Image.open(io.BytesIO(thumb.body)).format, "WEBP")
        etag = full.headers["ETag"]
        self.assertEqual(Client().req("GET", f"/p/{photos[0]['id']}.jpg", headers={"If-None-Match": etag}).status, 304)
        # non-images are rejected, even with an image extension and content type
        r = self.c.upload(f"/me/dogs/{dog_id}/photos", [("evil.jpg", b"<?php echo 1; ?>" * 50, "image/jpeg")])
        self.assertIn("pe=type", r.headers["Location"])
        r = self.c.upload(f"/me/dogs/{dog_id}/photos", [("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml")])
        self.assertIn("pe=type", r.headers["Location"])
        self.assertEqual(len(A.gallery(dog_id)), 2)
        # avatar + delete
        self.assertEqual(self.c.post(f"/me/dogs/{dog_id}/photos/{photos[1]['id']}/avatar", {}).status, 303)
        self.assertEqual(A.dog_by_id(dog_id)["avatar_photo_id"], photos[1]["id"])
        self.assertEqual(self.c.post(f"/me/dogs/{dog_id}/photos/{photos[0]['id']}/delete", {}).status, 303)
        self.assertEqual(len(A.gallery(dog_id)), 1)
        self.assertEqual(Client().get(f"/p/{photos[0]['id']}.jpg").status, 404)
        # another user can't upload to it
        other = Client("10.2.7.7")
        sign_in(other, f"o2-{uuid.uuid4().hex[:6]}-{RUN}@example.com")
        self.assertEqual(other.upload(f"/me/dogs/{dog_id}/photos", [("a.jpg", raw, "image/jpeg")]).status, 404)

    def test_photo_count_cap(self):
        dog_id = new_dog(self.c, name="Cappy")
        small = io.BytesIO()
        Image.new("RGB", (400, 400), (10, 120, 10)).save(small, "PNG")
        files = [(f"{i}.png", small.getvalue(), "image/png") for i in range(A.MAX_PHOTOS + 2)]
        r = self.c.upload(f"/me/dogs/{dog_id}/photos", files)
        self.assertIn("pe=count", r.headers["Location"])
        self.assertEqual(A.photo_count(dog_id), A.MAX_PHOTOS)

    def test_report_and_admin_view(self):
        dog_id = new_dog(self.c, name="Reported")
        slug = A.dog_by_id(dog_id)["slug"]
        v = Client("10.2.6.6")
        r = v.post(f"/dogs/{slug}/report", {"reason": A.REPORT_REASONS[0], "details": "<i>bad</i>"})
        self.assertEqual(r.status, 303)
        self.assertEqual(Client().get("/admin/reports").status, 404)
        self.assertEqual(Client().get("/admin/reports?key=wrong").status, 404)
        page = Client().get("/admin/reports?key=test-admin-key")
        self.assertEqual(page.status, 200)
        self.assertIn("&lt;i&gt;bad&lt;/i&gt;", page.text)
        rid = A.list_reports()[0][0]
        r = Client().post("/admin/reports", {"key": "test-admin-key", "id": rid, "dog": dog_id, "action": "hide"}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(Client().get(f"/dogs/{slug}").status, 404)
        self.assertEqual(self.c.get(f"/dogs/{slug}").status, 200)  # owner still sees it
        Client().post("/admin/reports", {"key": "test-admin-key", "id": rid, "dog": dog_id, "action": "unhide"}, csrf=False)
        self.assertEqual(Client().get(f"/dogs/{slug}").status, 200)

    def test_delete_account(self):
        new_dog(self.c, name="Bye")
        self.c.post("/me/delete", {})  # without the confirmation box nothing happens
        self.assertIsNotNone(A.one("SELECT id FROM users WHERE email=:e", e=self.email))
        r = self.c.post("/me/delete", {"confirm": "yes"})
        self.assertIn("Your account is deleted", r.text)
        self.assertIsNone(A.one("SELECT id FROM users WHERE email=:e", e=self.email))
        self.assertEqual(self.c.get("/me").status, 303)


class SiteTests(unittest.TestCase):
    def test_pages_and_nav(self):
        c = Client()
        for p in ("/", "/runs", "/signin", "/dogs", "/healthz", "/sitemap.xml", "/app.css"):
            self.assertEqual(c.get(p).status, 200, p)
        home = c.get("/").text
        self.assertIn('href="/signin"', home)
        self.assertIn('href="/dogs"', home)
        self.assertNotIn("{{NAV_ACCOUNT}}", home)
        sign_in(c, f"nav-{RUN}@example.com")
        self.assertIn('href="/me"', c.get("/").text)
        self.assertIn('href="/me"', c.get("/runs").text)
        self.assertEqual(c.get("/me").status, 200)

    def test_seed_is_idempotent(self):
        assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "barksbuds-assets")
        if not os.path.isdir(assets):
            self.skipTest("assets folder not present")
        import seed
        old = sys.argv
        try:
            sys.argv = ["seed.py", "--assets", assets]
            seed.main(); seed.main()
        finally:
            sys.argv = old
        n = A.one("SELECT COUNT(*) FROM dogs WHERE seed_key IN ('mike-lily','mike-maggie')")[0]
        self.assertEqual(n, 2)
        lily = A.dog_by_id(A.one("SELECT id FROM dogs WHERE seed_key='mike-lily'")[0])
        self.assertEqual(len(A.gallery(lily["id"])), 3)
        page = Client().get("/dogs/" + lily["slug"]).text
        self.assertIn("6 years old", page)
        self.assertIn("Manhasset", page)
        self.assertNotIn("mike.karachalios", page)


if __name__ == "__main__":
    unittest.main()
