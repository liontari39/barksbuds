"""Photo feed: posting (sign-in, limits, EXIF stripping, rate limit), feed + pagination, post page (OG, robots), likes,
comments (author / poster delete), reports + admin hide, edit/delete, privacy (dog visibility, stricter override,
signed-out, blocks, search setting), profile + run strips, account/dog deletion.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import io, json, os, re, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member  # noqa: E402
from test_packs import multipart  # noqa: E402
import accounts as A  # noqa: E402
import feed as F  # noqa: E402
import messages as MS  # noqa: E402
import privacy as PV  # noqa: E402
from PIL import Image  # noqa: E402

ADMIN = {"X-Admin-Key": "test-admin-key"}


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def share(c, dogs, n=1, caption="Zoomies!", run="", vis="", files=None, status=303):
    files = files if files is not None else [("photos", f"p{i}.jpg", jpeg_with_exif((40 * i % 255, 120, 60))) for i in range(n)]
    r = multipart(c, "/photos/new", {"dogs": [str(d) for d in dogs], "caption": caption, "run": run, "vis": vis}, files)
    assert r.status == status, (r.status, r.text[:600])
    if status == 303:
        m = re.match(r"/photos/(\d+)\?m=posted", r.headers["Location"])
        assert m, r.headers["Location"]
        return int(m.group(1))
    return r


def public_user(uid, dogs=()):
    """Make an account behave like a fully public one (public profiles, listed, indexable)."""
    A.q("UPDATE users SET priv_index=1, priv_search='everyone', priv_owner_name=1 WHERE id=:u", u=uid)
    for d in dogs:
        PV.set_visibility(d, "public")


def first_photo(pid):
    return F.photos_of([pid])[pid][0]["id"]


class PhotoFeed(unittest.TestCase):
    def test_empty_and_nav(self):
        anon = Client("10.77.0.1")
        r = anon.get("/photos?dog=nobody-here-xyz")
        self.assertEqual(r.status, 404)
        r = anon.get("/photos?before=1")
        self.assertEqual(r.status, 200)
        r = anon.get("/dogs")
        self.assertIn('href="/photos"', r.text)  # main nav + mobile menu
        self.assertGreaterEqual(r.text.count('href="/photos"'), 2)
        self.assertIn('<a href="/photos">Photos</a>', anon.get("/").text)

    def test_new_requires_signin_and_dog(self):
        anon = Client("10.77.0.2")
        r = anon.get("/photos/new")
        self.assertEqual(r.status, 303)
        self.assertIn("/signin?next=%2Fphotos%2Fnew", r.headers["Location"])
        c, _e, _u, _d = member("nodog", dogs=0)
        self.assertIn("Add your dog first", c.get("/photos/new").text)

    def test_post_and_view_public(self):
        c, email, uid, (dog,) = member("poster")
        public_user(uid, [dog])
        r = c.get("/photos/new")
        self.assertEqual(r.status, 200)
        self.assertIn('name="photos"', r.text)
        self.assertIn('value="n-006"', r.text)
        pid = share(c, [dog], n=2, caption="Zoomies at the run!", run="n-006")
        post = F.get(pid)
        self.assertEqual(post["caption"], "Zoomies at the run!")
        self.assertEqual(post["run_id"], "n-006")
        self.assertEqual(len(F.photos_of([pid])[pid]), 2)
        anon = Client("10.77.0.3")
        r = anon.get(f"/photos/{pid}")
        self.assertEqual(r.status, 200)
        self.assertIn("Zoomies at the run!", r.text)
        self.assertIn(f'/fp/{first_photo(pid)}.jpg"', r.text)  # og:image
        self.assertIn('property="og:image"', r.text)
        self.assertIn('content="index,follow"', r.text)
        self.assertNotIn(email, r.text)
        self.assertIn("Poster", r.text)  # display name allowed by priv_owner_name
        # the photo file is public and has no EXIF/GPS
        r = anon.get(f"/fp/{first_photo(pid)}.jpg")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        self.assertIn("public", r.headers["Cache-Control"])
        im = Image.open(io.BytesIO(r.body))
        self.assertEqual(len(im.getexif()), 0)
        self.assertNotIn(b"SecretCam", r.body)
        self.assertEqual(anon.get(f"/fp/{first_photo(pid)}.webp").status, 200)
        # feed (signed out), profile strip, run strip, sitemap
        self.assertIn(f'id="post-{pid}"', anon.get("/photos").text)
        slug = A.dog_by_id(dog)["slug"]
        self.assertIn(f'href="/photos/{pid}"', anon.get(f"/dogs/{slug}").text)
        self.assertIn(f'id="post-{pid}"', anon.get(f"/photos?dog={slug}").text)
        self.assertIn(f'id="post-{pid}"', anon.get("/photos?run=n-006").text)
        import runpageweb, webapp
        run = webapp.run_index()["n-006"]
        self.assertIn(f'href="/photos/{pid}"', anon.get(runpageweb.run_path(run)).text)
        self.assertIn(f"/photos/{pid}</loc>", anon.get("/sitemap.xml").text)

    def test_limits_and_validation(self):
        c, _e, uid, (dog,) = member("limits")
        other, _e2, _u2, (odog,) = member("otherdog")
        r = share(c, [dog], n=5, status=400)
        self.assertIn("up to 4 photos", r.text)
        r = share(c, [odog], n=1, status=400)  # not your dog
        self.assertIn("Tag at least one of your dogs", r.text)
        r = share(c, [dog], files=[], status=400)
        r = share(c, [dog], files=[("photos", "x.txt", b"hello not an image")], status=400)
        self.assertIn("JPEG", r.text)
        r = share(c, [dog], run="no-such-run", status=400)
        long = "x" * 500
        pid = share(c, [dog], caption=long)
        self.assertEqual(len(F.get(pid)["caption"]), F.MAX_CAPTION)

    def test_rate_limit(self):
        c, _e, uid, (dog,) = member("speedy")
        for _ in range(5):
            share(c, [dog])
        r = share(c, [dog], status=429)
        self.assertIn("try again", r.text)

    def test_privacy_visibility_and_override(self):
        c, _e, uid, (dog,) = member("priv")
        public_user(uid, [dog])
        PV.set_visibility(dog, "members")
        pid = share(c, [dog])
        anon, (m, _e2, _u2, _d2) = Client("10.77.0.4"), member("viewer")
        self.assertEqual(anon.get(f"/photos/{pid}").status, 403)
        self.assertEqual(anon.get(f"/fp/{first_photo(pid)}.jpg").status, 404)
        self.assertNotIn(f'id="post-{pid}"', anon.get("/photos").text)
        self.assertEqual(m.get(f"/photos/{pid}").status, 200)
        self.assertIn('content="noindex"', m.get(f"/photos/{pid}").text)
        r = m.get(f"/fp/{first_photo(pid)}.jpg")
        self.assertEqual(r.status, 200)
        self.assertIn("private", r.headers["Cache-Control"])
        self.assertIn(f'id="post-{pid}"', m.get("/photos").text)
        # public dog, stricter per-post override
        PV.set_visibility(dog, "public")
        pid2 = share(c, [dog], vis="members")
        self.assertEqual(anon.get(f"/photos/{pid2}").status, 403)
        self.assertEqual(m.get(f"/photos/{pid2}").status, 200)
        pid3 = share(c, [dog], vis="private")
        self.assertEqual(m.get(f"/photos/{pid3}").status, 403)
        self.assertEqual(c.get(f"/photos/{pid3}").status, 200)
        pid4 = share(c, [dog], vis="pack")
        self.assertEqual(m.get(f"/photos/{pid4}").status, 403)
        # a looser override can't open up a stricter dog profile
        PV.set_visibility(dog, "private")
        self.assertEqual(m.get(f"/photos/{pid2}").status, 403)
        self.assertEqual(anon.get(f"/photos/{pid}").status, 403)
        PV.set_visibility(dog, "public")
        # search setting "none" keeps posts out of the feed but not off the post page
        A.q("UPDATE users SET priv_search='none' WHERE id=:u", u=uid)
        self.assertNotIn(f'id="post-{pid}"', anon.get("/photos").text)
        self.assertEqual(anon.get(f"/photos/{pid}").status, 200)
        self.assertIn('content="noindex"', anon.get(f"/photos/{pid}").text)
        self.assertIn(f'id="post-{pid}"', c.get("/photos").text)  # the poster still sees their own
        A.q("UPDATE users SET priv_search='everyone' WHERE id=:u", u=uid)

    def test_blocks(self):
        c, _e, uid, (dog,) = member("blockp")
        public_user(uid, [dog])
        pid = share(c, [dog])
        b, _e2, buid, _d = member("blocker")
        self.assertEqual(b.get(f"/photos/{pid}").status, 200)
        MS.block(buid, uid)
        self.assertEqual(b.get(f"/photos/{pid}").status, 403)
        self.assertEqual(b.get(f"/fp/{first_photo(pid)}.jpg").status, 404)
        self.assertNotIn(f'id="post-{pid}"', b.get("/photos").text)
        r = b.post(f"/photos/{pid}/like", {}, headers={"Accept": "application/json"})
        self.assertEqual(r.status, 403)
        r = b.post(f"/photos/{pid}/comments", {"body": "hi"})
        self.assertEqual(r.status, 403)
        self.assertEqual(F.comments(pid), [])
        # the blocked poster can't see the blocker's posts either
        bdog = _d[0]
        public_user(buid, [bdog])
        MS.unblock(buid, uid)
        bpid = share(b, [bdog])
        MS.block(buid, uid)
        self.assertEqual(c.get(f"/photos/{bpid}").status, 403)

    def test_likes_and_comments(self):
        c, _e, uid, (dog,) = member("social")
        public_user(uid, [dog])
        pid = share(c, [dog])
        m, _e2, muid, _d = member("liker")
        r = m.post(f"/photos/{pid}/like", {}, headers={"Accept": "application/json"})
        self.assertEqual(json.loads(r.text), {"liked": True, "count": 1})
        self.assertIn('aria-pressed="true"', m.get(f"/photos/{pid}").text)
        r = m.post(f"/photos/{pid}/like", {}, headers={"Accept": "application/json"})
        self.assertEqual(json.loads(r.text), {"liked": False, "count": 0})
        r = m.post(f"/photos/{pid}/like", {})  # no-JS: redirect back
        self.assertEqual(r.status, 303)
        anon = Client("10.77.0.5")
        self.assertEqual(anon.post(f"/photos/{pid}/like", {}).status, 303)  # to sign in
        self.assertEqual(F.counts([pid])[0].get(pid), 1)
        # comments: author or poster can delete; others can't
        r = m.post(f"/photos/{pid}/comments", {"body": "What a good dog!"})
        self.assertEqual(r.status, 303)
        cid = F.comments(pid)[0]["id"]
        self.assertIn("What a good dog!", anon.get(f"/photos/{pid}").text)
        x, _e3, _u3, _d3 = member("thirdp")
        self.assertEqual(x.post(f"/photos/comments/{cid}/delete", {}).status, 403)
        self.assertEqual(c.post(f"/photos/comments/{cid}/delete", {}).status, 303)
        self.assertEqual(F.comments(pid), [])
        m.post(f"/photos/{pid}/comments", {"body": "Again!"})
        cid = F.comments(pid)[0]["id"]
        self.assertEqual(m.post(f"/photos/comments/{cid}/delete", {}).status, 303)
        # empty + rate limit
        r = m.post(f"/photos/{pid}/comments", {"body": "   "})
        self.assertIn("e=empty", r.headers["Location"])
        locs = [m.post(f"/photos/{pid}/comments", {"body": f"c{i}"}).headers["Location"] for i in range(9)]
        self.assertIn("e=cslow", locs[-1])

    def test_reports_and_admin_hide(self):
        c, _e, uid, (dog,) = member("reported")
        public_user(uid, [dog])
        pid = share(c, [dog], caption="Report me")
        m, _e2, _u2, _d = member("reporter")
        m.post(f"/photos/{pid}/comments", {"body": "rude comment"})
        cid = F.comments(pid)[0]["id"]
        self.assertEqual(m.post(f"/photos/{pid}/report", {"reason": A.REPORT_REASONS[0], "details": "x"}).status, 303)
        self.assertEqual(c.post(f"/photos/comments/{cid}/report", {"reason": A.REPORT_REASONS[0]}).status, 303)
        admin = Client("10.77.0.6")
        r = admin.req("GET", "/admin/reports", headers=ADMIN)
        self.assertIn(f'/photos/{pid}"', r.text)
        self.assertIn("Hide photo post", r.text)
        self.assertIn("rude comment", r.text)
        rid = A.one("SELECT id FROM reports WHERE photo_post_id=:p", p=pid)[0]
        r = admin.post("/admin/reports", {"key": "test-admin-key", "id": str(rid), "dog": "", "fpost": str(pid), "action": "hide_fpost"}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(F.get(pid)["hidden"], 1)
        anon = Client("10.77.0.7")
        self.assertEqual(anon.get(f"/photos/{pid}").status, 404)
        self.assertNotIn(f'id="post-{pid}"', m.get("/photos").text)
        self.assertIn("Hidden by our team", c.get(f"/photos/{pid}").text)
        admin.post("/admin/reports", {"key": "test-admin-key", "id": str(rid), "fpost": str(pid), "action": "unhide_fpost"}, csrf=False)
        self.assertEqual(F.get(pid)["hidden"], 0)
        crid = A.one("SELECT id FROM reports WHERE photo_comment_id=:c", c=cid)[0]
        admin.post("/admin/reports", {"key": "test-admin-key", "id": str(crid), "fcomment": str(cid), "action": "hide_fcomment"}, csrf=False)
        self.assertNotIn("rude comment", anon.get(f"/photos/{pid}").text)

    def test_edit_and_delete(self):
        c, _e, uid, (dog,) = member("editor")
        public_user(uid, [dog])
        pid = share(c, [dog], caption="Old caption")
        self.assertEqual(c.get(f"/photos/{pid}/edit").status, 200)
        r = c.post(f"/photos/{pid}/edit", {"caption": "New caption", "vis": "members"})
        self.assertEqual(r.status, 303)
        self.assertEqual(F.get(pid)["caption"], "New caption")
        self.assertEqual(F.get(pid)["vis"], "members")
        m, _e2, _u2, _d = member("notowner")
        self.assertEqual(m.get(f"/photos/{pid}/edit").status, 404)
        self.assertEqual(m.post(f"/photos/{pid}/edit", {"caption": "hijack"}).status, 403)
        self.assertEqual(m.post(f"/photos/{pid}/delete", {}).status, 403)
        ph = first_photo(pid)
        self.assertEqual(c.post(f"/photos/{pid}/delete", {}).status, 303)
        self.assertIsNone(F.get(pid))
        self.assertEqual(c.get(f"/fp/{ph}.jpg").status, 404)
        self.assertEqual(c.get(f"/photos/{pid}").status, 404)

    def test_pagination(self):
        c, _e, uid, (dog,) = member("pager")
        public_user(uid, [dog])
        processed = [A.process_image(jpeg_with_exif())]
        ids = [F.create(uid, [dog], "", f"page post {i}", "", processed) for i in range(F.PAGE + 3)]
        anon = Client("10.77.0.8")
        slug = A.dog_by_id(dog)["slug"]
        r = anon.get(f"/photos?dog={slug}")
        self.assertEqual(len(re.findall(r'<article class="fpost"', r.text)), F.PAGE)
        m = re.search(r'href="(/photos\?[^"]*before=\d+)" data-more', r.text)
        self.assertTrue(m)
        r2 = anon.req("GET", m.group(1).replace("&amp;", "&"), headers={"X-Partial": "1"})
        self.assertNotIn("<html", r2.text)
        self.assertEqual(len(re.findall(r'<article class="fpost"', r2.text)), 3)
        self.assertIn(f'id="post-{ids[0]}"', r2.text)

    def test_dog_and_account_deletion(self):
        c, _e, uid, dogs = member("leaver", dogs=2)
        p1 = share(c, [dogs[0]])
        p2 = share(c, dogs)
        m, _e2, muid, (mdog,) = member("commenter")
        public_user(uid, dogs)
        m.post(f"/photos/{p2}/comments", {"body": "bye"})
        m.post(f"/photos/{p2}/like", {})
        A.delete_dog(dogs[0])
        self.assertIsNone(F.get(p1))
        self.assertEqual(F.dogs_of([p2])[p2], [dogs[1]])
        A.delete_user(muid)
        self.assertEqual(F.comments(p2), [])
        self.assertEqual(F.counts([p2])[0].get(p2, 0), 0)
        A.delete_user(uid)
        self.assertIsNone(F.get(p2))
        self.assertEqual(A.one("SELECT COUNT(*) FROM feed_photos WHERE post_id IN (:a,:b)", a=p1, b=p2)[0], 0)


if __name__ == "__main__":
    unittest.main()
