"""Packs: create/edit, browse + API, join (open and request), approve/deny, roles and permissions, leave, the pack board
(posts, photos, comments, pinning, reports), pack meetups (members-only RSVP, notices), emails + unsubscribe, the sign-in
`next` return path and samples.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import json, os, re, sys, unittest, uuid
from urllib.parse import quote, urlsplit, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif, wait_link  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, mark, outbox, wait_mail, future  # noqa: E402
import accounts as A  # noqa: E402
import meetups as M  # noqa: E402
import packs as P  # noqa: E402
import packweb  # noqa: E402
import webapp as W  # noqa: E402


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def multipart(c, path, fields, files=()):
    bnd = "----bbp" + uuid.uuid4().hex
    fields = dict(fields)
    fields.setdefault("csrf", c.csrf())
    parts = []
    for k, v in fields.items():
        for one in (v if isinstance(v, list) else [v]):
            parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{one}\r\n'.encode())
    for name, fn, data in files:
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                     + data + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    return c.req("POST", path, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={bnd}"})


def make_pack(c, dogs=(), cover=None, **over):
    data = {"name": "Morning Crew", "area": "Nassau", "town": "Manhasset", "run_id": "n-006",
            "description": "We meet most mornings at the run.", "fit": "", "visibility": "open",
            "dogs": [str(d) for d in dogs]}
    data.update(over)
    r = multipart(c, "/packs/new", data, [("cover", "c.jpg", cover)] if cover else [])
    assert r.status == 303, (r.status, r.text[:800])
    return int(re.match(r"/packs/(\d+)", r.headers["Location"]).group(1)), r


def ppage(c, pid):
    return c.get(packweb.pack_path(P.get(pid)))


def join(c, pid, dogs, message=""):
    return c.post(f"/packs/{pid}/join", {"dogs": [str(d) for d in dogs], "message": message})


class PackTests(unittest.TestCase):
    def test_create_page_browse_and_api(self):
        r = Client("10.7.0.1").get("/packs/new")
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"], "/signin?next=" + quote("/packs/new", safe=""))
        org, _, oid, dogs = member("org")
        self.assertEqual(org.get("/packs/new").status, 200)
        bad = multipart(org, "/packs/new", {"name": "x", "area": "Nowhere", "town": "", "description": ""})
        self.assertEqual(bad.status, 422)
        self.assertIn("Please fix", bad.text)
        pid, r = make_pack(org, dogs, cover=jpeg_with_exif(size=(2400, 1350)), name="Crew <script>x</script>")
        p = P.get(pid)
        self.assertEqual((p["owner_user_id"], p["area"], p["run_id"], p["visibility"]), (oid, "Nassau", "n-006", "open"))
        self.assertTrue(P.is_organizer(pid, oid))
        self.assertEqual(P.membership(pid, oid)["dogs"], dogs)
        self.assertTrue(p["cover_photo_id"])
        img = Client().get(f"/pp/{p['cover_photo_id']}.jpg")
        self.assertEqual(img.status, 200)
        self.assertNotIn(b"SecretCam", img.body)
        self.assertLessEqual(P.photo_size(p["cover_photo_id"])[0], 1600)
        page = Client("10.7.0.2").get(r.headers["Location"].split("?")[0])
        self.assertEqual(page.status, 200)
        self.assertNotIn("<script>x</script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        self.assertIn('property="og:title"', page.text)
        self.assertIn(f"/pp/{p['cover_photo_id']}.jpg", page.text)
        self.assertIn("Christopher Morley Park Dog Run", page.text)
        self.assertIn("1 member", page.text)
        self.assertIn("Sign in to join", page.text)
        self.assertIn(f'/dogs/{A.dog_by_id(dogs[0])["slug"]}', page.text)
        # slug mismatch redirects to the canonical URL
        r2 = Client().get(f"/packs/{pid}-old-name")
        self.assertEqual(r2.status, 301)
        self.assertEqual(r2.headers["Location"], packweb.pack_path(p))
        self.assertIn(f"/packs/{pid}-", Client().get("/packs").text)
        self.assertIn(f"/packs/{pid}-", Client().get("/packs?region=li").text)
        self.assertIn(f"/packs/{pid}-", Client().get("/packs?region=northshore").text)
        self.assertNotIn(f"/packs/{pid}-", Client().get("/packs?area=Queens").text)
        api = json.loads(Client().get("/api/packs").text)
        self.assertTrue(any(x["url"] == packweb.pack_path(p) for x in api["runs"]["n-006"]))
        # nav + mobile menu everywhere
        for path in ("/", "/runs", "/packs", "/dogs"):
            t = Client().get(path).text
            self.assertIn('href="/packs"', t, path)
            self.assertIn('class="mmenu"', t, path)
        # "Packs near you" on /me for another Nassau member
        other, *_ = member("near")
        self.assertIn("Packs near you", other.get("/me").text)

    def test_edit_permissions_and_delete(self):
        org, _, oid, dogs = member("ed")
        mem, _, mid_, mdogs = member("edm")
        pid, _ = make_pack(org, dogs)
        self.assertEqual(join(mem, pid, mdogs).status, 303)
        self.assertEqual(mem.get(f"/packs/{pid}/edit").status, 403)
        r = multipart(mem, f"/packs/{pid}/edit", {"name": "Hijack", "area": "Nassau", "town": "X", "description": "hijacked pack"})
        self.assertEqual(r.status, 403)
        self.assertEqual(P.get(pid)["name"], "Morning Crew")
        r = multipart(org, f"/packs/{pid}/edit", {"name": "Evening Crew", "area": "Nassau", "town": "Manhasset", "run_id": "n-006",
                                                   "description": "Evenings now, same run.", "visibility": "request"})
        self.assertEqual(r.status, 303)
        self.assertEqual((P.get(pid)["name"], P.get(pid)["visibility"]), ("Evening Crew", "request"))
        self.assertEqual(mem.post(f"/packs/{pid}/delete", {}).status, 403)
        # a pack meetup survives pack deletion, detached
        mtg, _ = TM.create(org, pack_id=str(pid))
        self.assertEqual(M.get(mtg)["pack_id"], pid)
        self.assertEqual(org.post(f"/packs/{pid}/delete", {}).status, 303)
        self.assertIsNone(P.get(pid))
        self.assertIsNone(M.get(mtg)["pack_id"])
        self.assertEqual(Client().get(f"/packs/{pid}").status, 404)

    def test_join_open_and_request(self):
        org, oemail, oid, odogs = member("jo")
        a, aemail, aid, adogs = member("ja", dogs=2)
        pid, _ = make_pack(org, odogs)
        page = ppage(a, pid).text
        self.assertIn("Join the pack", page)
        self.assertEqual(join(a, pid, []).headers["Location"].split("?")[1].split("#")[0], "e=nodogs")
        foreign = join(a, pid, odogs)  # someone else's dog is ignored
        self.assertIn("e=nodogs", foreign.headers["Location"])
        r = join(a, pid, adogs[:1])
        self.assertIn("m=p_joined", r.headers["Location"])
        self.assertTrue(P.is_member(pid, aid))
        self.assertEqual(P.membership(pid, aid)["dogs"], adogs[:1])
        self.assertEqual(a.post(f"/packs/{pid}/dogs", {"dogs": [str(x) for x in adogs]}).status, 303)
        self.assertEqual(P.membership(pid, aid)["dogs"], adogs)
        self.assertIn("2 members", ppage(Client(), pid).text)
        self.assertIn("m=p_left", a.post(f"/packs/{pid}/leave", {}).headers["Location"])
        self.assertIsNone(P.membership(pid, aid))
        # owner can't leave without transferring
        self.assertIn("e=owner", org.post(f"/packs/{pid}/leave", {}).headers["Location"])
        self.assertTrue(P.is_organizer(pid, oid))
        # request-to-join pack
        rp, _ = make_pack(org, odogs, name="Quiet Crew", visibility="request")
        b, bemail, bid, bdogs = member("jb")
        since = mark()
        r = join(b, rp, bdogs, message="Hi <b>there</b>")
        self.assertIn("m=p_requested", r.headers["Location"])
        self.assertEqual(P.membership(rp, bid)["status"], "pending")
        self.assertFalse(P.is_member(rp, bid))
        mail = wait_mail("pack-request", oemail, since)[0]
        self.assertIn("asked to join Quiet Crew", mail["subject"])
        self.assertIn("/emails/packs?u=", mail["text"])
        self.assertIn("Hi <b>there</b>", mail["text"])
        import glob
        htmls = [open(f).read() for f in glob.glob(os.path.join(T.TMP, "outbox", "*-pack-request-*.html"))]
        self.assertTrue(any("Hi &lt;b&gt;there&lt;/b&gt;" in h for h in htmls))
        self.assertFalse(any("Hi <b>there</b>" in h for h in htmls))
        self.assertIn("waiting for an organizer", ppage(b, rp).text)
        self.assertIn("e=members", b.post(f"/packs/{rp}/posts", {"body": "hello"}).headers["Location"])
        # only organizers can approve
        self.assertEqual(b.post(f"/packs/{rp}/requests/{bid}/approve", {}).status, 403)
        members_page = org.get(f"/packs/{rp}/members")
        self.assertEqual(members_page.status, 200)
        self.assertIn("Approve", members_page.text)
        self.assertEqual(b.get(f"/packs/{rp}/members").status, 403)
        since = mark()
        self.assertEqual(org.post(f"/packs/{rp}/requests/{bid}/approve", {}).status, 303)
        self.assertTrue(P.is_member(rp, bid))
        self.assertIn("welcome to Quiet Crew", wait_mail("pack-approved", bemail, since)[0]["subject"])
        # deny removes the request
        c, cemail, cid, cdogs = member("jc")
        join(c, rp, cdogs)
        self.assertEqual(org.post(f"/packs/{rp}/requests/{cid}/deny", {}).status, 303)
        self.assertIsNone(P.membership(rp, cid))
        # withdraw a request
        join(c, rp, cdogs)
        self.assertIn("m=p_cancelled", c.post(f"/packs/{rp}/leave", {}).headers["Location"])
        # CSRF is required
        self.assertEqual(c.post(f"/packs/{pid}/join", {"dogs": [str(cdogs[0])], "csrf": "bad"}).status, 403)
        self.assertFalse(P.is_member(pid, cid))

    def test_roles(self):
        own, _, oid, odogs = member("ro")
        co, _, cid, cdogs = member("rc")
        m1, _, m1id, m1dogs = member("rm")
        m2, _, m2id, m2dogs = member("rn")
        pid, _ = make_pack(own, odogs)
        for c, d in ((co, cdogs), (m1, m1dogs), (m2, m2dogs)):
            join(c, pid, d)
        # only the owner changes roles
        self.assertEqual(m1.post(f"/packs/{pid}/members/{cid}/promote", {}).status, 403)
        self.assertEqual(own.post(f"/packs/{pid}/members/{cid}/promote", {}).status, 303)
        self.assertTrue(P.is_organizer(pid, cid))
        self.assertEqual(co.post(f"/packs/{pid}/members/{m1id}/promote", {}).status, 403)
        # co-organizer can edit, see members, remove members, but not the owner or delete the pack
        self.assertEqual(co.get(f"/packs/{pid}/edit").status, 200)
        self.assertEqual(co.post(f"/packs/{pid}/members/{m2id}/remove", {}).status, 303)
        self.assertIsNone(P.membership(pid, m2id))
        co.post(f"/packs/{pid}/members/{oid}/remove", {})
        self.assertTrue(P.is_organizer(pid, oid))
        self.assertEqual(co.post(f"/packs/{pid}/delete", {}).status, 403)
        self.assertEqual(m1.post(f"/packs/{pid}/members/{cid}/remove", {}).status, 403)
        # transfer ownership
        self.assertEqual(own.post(f"/packs/{pid}/members/{m1id}/owner", {}).status, 303)
        p = P.get(pid)
        self.assertEqual(p["owner_user_id"], m1id)
        self.assertEqual(P.membership(pid, oid)["role"], "organizer")
        self.assertEqual(P.membership(pid, m1id)["role"], "owner")
        # demote; a regular member gets no organizer tools
        self.assertEqual(m1.post(f"/packs/{pid}/members/{oid}/demote", {}).status, 303)
        self.assertEqual(P.membership(pid, oid)["role"], "member")
        self.assertNotIn("You organize this pack", ppage(own, pid).text)
        self.assertIn("m=p_left", own.post(f"/packs/{pid}/leave", {}).headers["Location"])

    def test_board_posts_comments_reports(self):
        org, _, oid, odogs = member("bo")
        a, _, aid, adogs = member("ba")
        out, _, xid, xdogs = member("bx")
        pid, _ = make_pack(org, odogs)
        join(a, pid, adogs)
        # non-members don't see the board and can't post
        self.assertIn("The pack board is for members", ppage(out, pid).text)
        self.assertIn("e=members", out.post(f"/packs/{pid}/posts", {"body": "hi"}).headers["Location"])
        self.assertIn("e=empty", multipart(a, f"/packs/{pid}/posts", {"body": "   "}).headers["Location"])
        r = multipart(a, f"/packs/{pid}/posts", {"body": "Run at 9? <img src=x onerror=alert(1)>"},
                      [("photo", "p.jpg", jpeg_with_exif((10, 120, 40)))])
        self.assertEqual(r.status, 303, r.text[:500])
        post_id = int(re.search(r"#post-(\d+)", r.headers["Location"]).group(1))
        po = P.get_post(post_id)
        self.assertTrue(po["photo_id"])
        page = ppage(a, pid).text
        self.assertIn("Run at 9?", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x", page)
        img = a.get(f"/pp/{po['photo_id']}.jpg")
        self.assertEqual(img.status, 200)
        self.assertNotIn(b"SecretCam", img.body)
        self.assertEqual(out.get(f"/pp/{po['photo_id']}.jpg").status, 404)   # board photos are members-only
        self.assertEqual(Client().get(f"/pp/{po['photo_id']}.webp").status, 404)
        # comments
        self.assertIn("m=p_commented", org.post(f"/packs/{pid}/posts/{post_id}/comments", {"body": "See you there"}).headers["Location"])
        self.assertIn("e=members", out.post(f"/packs/{pid}/posts/{post_id}/comments", {"body": "x"}).headers["Location"])
        self.assertIn("See you there", ppage(a, pid).text)
        cid = A.one("SELECT id FROM pack_comments WHERE post_id=:p", p=post_id)[0]
        # pinning is for organizers
        self.assertEqual(a.post(f"/packs/{pid}/posts/{post_id}/pin", {}).status, 403)
        self.assertEqual(org.post(f"/packs/{pid}/posts/{post_id}/pin", {}).status, 303)
        self.assertEqual(P.get_post(post_id)["pinned"], 1)
        second = multipart(org, f"/packs/{pid}/posts", {"body": "Newer post"})
        self.assertEqual(P.posts(pid)[0]["id"], post_id)  # pinned stays first
        new_id = int(re.search(r"#post-(\d+)", second.headers["Location"]).group(1))
        # only the author or an organizer deletes
        self.assertEqual(a.post(f"/packs/{pid}/posts/{new_id}/delete", {}).status, 403)
        self.assertEqual(a.post(f"/packs/{pid}/comments/{cid}/delete", {}).status, 403)
        # reports feed /admin/reports, with hide actions
        self.assertEqual(org.post(f"/packs/{pid}/posts/{post_id}/report", {"reason": A.REPORT_REASONS[0]}).status, 303)
        self.assertEqual(a.post(f"/packs/{pid}/comments/{cid}/report", {"reason": "Something else"}).status, 303)
        self.assertEqual(Client("10.7.9.9").post(f"/packs/{pid}/report", {"reason": A.REPORT_REASONS[0], "details": "spam"}).status, 303)
        adm = Client().get("/admin/reports?key=test-admin-key").text
        self.assertIn("Post in pack", adm)
        self.assertIn("Comment in pack", adm)
        self.assertIn("hide_post", adm)
        self.assertIn("hide_pack", adm)
        r = Client().post("/admin/reports", {"key": "test-admin-key", "action": "hide_post", "id": "0", "post": str(post_id)}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(P.get_post(post_id)["hidden"], 1)
        self.assertNotIn("Run at 9?", ppage(a, pid).text)
        self.assertEqual(a.get(f"/pp/{po['photo_id']}.jpg").status, 404)
        Client().post("/admin/reports", {"key": "test-admin-key", "action": "hide_pcomment", "id": "0", "pcomment": str(cid)}, csrf=False)
        self.assertEqual(P.get_comment(cid)["hidden"], 1)
        Client().post("/admin/reports", {"key": "test-admin-key", "action": "hide_pack", "id": "0", "pack": str(pid)}, csrf=False)
        self.assertEqual(Client().get(f"/packs/{pid}").status, 404)
        self.assertEqual(ppage(a, pid).status, 200)  # members still see it, with a notice
        self.assertNotIn(f"/packs/{pid}-", Client().get("/packs").text)
        # deleting a post removes its photo
        self.assertEqual(a.post(f"/packs/{pid}/posts/{post_id}/delete", {}).status, 303)
        self.assertIsNone(P.get_post(post_id))
        self.assertIsNone(P.photo_info(po["photo_id"]))

    def test_pack_meetups_and_members_only(self):
        org, oemail, oid, odogs = member("mo")
        a, aemail, aid, adogs = member("ma")
        q, qemail, qid, qdogs = member("mq")
        out, _, xid, xdogs = member("mx")
        pid, _ = make_pack(org, odogs, name="Meet Crew")
        join(a, pid, adogs)
        join(q, pid, qdogs)
        q.post("/me/pack-emails", {"on": "0"})
        self.assertFalse(P.emails_on(qid))
        # host form from the pack page: prefilled home run and pack
        form = a.get(f"/meetups/new?pack={pid}").text
        self.assertIn('value="n-006" selected', form)
        self.assertIn(f'value="{pid}" selected', form)
        self.assertNotIn(f'value="{pid}" selected', out.get(f"/meetups/new?pack={pid}").text)
        # non-members can't attach a meetup to the pack
        d, t = future()
        bad = out.post("/meetups/new", {"title": "Sneaky", "date": d, "time": t, "duration": "60", "loc": "run", "run_id": "n-006",
                                        "pack_id": str(pid)})
        self.assertEqual(bad.status, 400)
        since = mark()
        mid, _ = TM.create(a, title="Pack romp", pack_id=str(pid), members_only="1")
        m = M.get(mid)
        self.assertEqual((m["pack_id"], m["members_only"]), (pid, 1))
        got = wait_mail("pack-meetup", oemail, since)
        self.assertIn("New Meet Crew meetup: Pack romp", got[0]["subject"])
        self.assertEqual(outbox("pack-meetup", aemail, since), [])   # not the host
        self.assertEqual(outbox("pack-meetup", qemail, since), [])   # opted out
        # shown on the pack page and badged on /meetups and the meetup page
        self.assertIn("Pack romp", ppage(Client(), pid).text)
        lst = Client().get("/meetups").text
        self.assertIn('class="badge pack"', lst)
        self.assertIn("Pack members only", lst)
        mp = TM.mpage(out, mid).text
        self.assertIn("Meet Crew", mp)
        self.assertIn("Join the pack to RSVP", mp)
        # members-only RSVP
        r = TM.rsvp(out, mid, xdogs)
        self.assertIn("e=packonly", r.headers["Location"])
        self.assertIsNone(M.rsvp_of(mid, xid))
        self.assertEqual(TM.rsvp(q, mid, qdogs).status, 303)
        self.assertEqual(M.rsvp_of(mid, qid)["status"], "going")
        # editing without changing the pack doesn't re-notify
        since = mark()
        a.post(f"/meetups/{mid}/edit", {"title": "Pack romp 2", "date": d, "time": t, "duration": "60", "loc": "run",
                                        "run_id": "n-006", "pack_id": str(pid), "members_only": "1"})
        self.assertEqual(M.get(mid)["title"], "Pack romp 2")
        import time as _t
        _t.sleep(0.4)
        self.assertEqual(outbox("pack-meetup", oemail, since), [])
        # unsubscribe link from the email
        link = re.search(r"(/emails/packs\?u=\d+&t=\w+)", got[0]["text"]).group(1)
        self.assertEqual(Client().get(link).status, 200)
        u, tk = parse_qs(urlsplit(link).query)["u"][0], parse_qs(urlsplit(link).query)["t"][0]
        self.assertEqual(Client().post(link, {"List-Unsubscribe": "One-Click"}, csrf=False).status, 200)
        self.assertFalse(P.emails_on(oid))
        self.assertEqual(Client().post("/emails/packs", {"u": u, "t": "bad", "action": "on"}, csrf=False).status, 400)
        Client().post("/emails/packs", {"u": u, "t": tk, "action": "on"}, csrf=False)
        self.assertTrue(P.emails_on(oid))

    def test_samples_send_no_email_and_admin(self):
        org, oemail, oid, odogs = member("so")
        pid = P.save(oid, {"name": "Sample Crew", "area": "Nassau", "town": "Manhasset", "run_id": "n-006",
                           "description": "A sample pack.", "fit": "", "visibility": "request", "dogs": odogs},
                     seed_key="test-sample-" + T.RUN, is_sample=1)
        b, _, bid, bdogs = member("sb")
        since = mark()
        join(b, pid, bdogs)
        org.post(f"/packs/{pid}/requests/{bid}/approve", {})
        import time as _t
        _t.sleep(0.4)
        self.assertEqual(outbox("pack-request", oemail, since), [])
        self.assertTrue(P.is_member(pid, bid))
        self.assertIn("Sample pack.", ppage(Client(), pid).text)
        self.assertEqual(Client().get("/admin/packs?key=wrong").status, 404)
        self.assertIn("Sample Crew", Client().get("/admin/packs?key=test-admin-key").text)
        # test email endpoint goes only to the pack organizer, and is admin-only
        self.assertEqual(Client().post("/admin/packs/test-email", {"key": "nope", "id": str(pid), "kind": "approved"}, csrf=False).status, 404)
        since = mark()
        r = Client().post("/admin/packs/test-email", {"key": "test-admin-key", "id": str(pid), "kind": "approved"}, csrf=False)
        self.assertEqual(json.loads(r.text)["ok"], True)
        self.assertTrue(wait_mail("pack-approved", oemail, since)[0]["subject"].startswith("[Test] "))
        r = Client().post("/admin/packs", {"key": "test-admin-key", "action": "delete_samples"}, csrf=False)
        self.assertEqual(r.status, 303)
        self.assertIsNone(P.get(pid))


class NextParamTests(unittest.TestCase):
    def test_safe_next(self):
        ok = ["/meetups/new?run=n-006", "/packs/3-crew#join", "/me"]
        bad = ["", "//evil.com", "https://evil.com/x", "/\\evil.com", "javascript:alert(1)", "/signin?next=/x", "/auth?t=1",
               "/me\r\nSet-Cookie: x", "/" + "a" * 500, "/admin/reports?key=1", "evil.com"]
        for x in ok:
            self.assertEqual(W.safe_next(x), x)
        for x in bad:
            self.assertEqual(W.safe_next(x), "", x)

    def test_host_here_returns_to_form(self):
        c = Client("10.7.5.1")
        r = c.get("/meetups/new?run=n-006")
        self.assertEqual(r.status, 303)
        loc = r.headers["Location"]
        self.assertEqual(loc, "/signin?next=" + quote("/meetups/new?run=n-006", safe=""))
        nxt = parse_qs(urlsplit(loc).query)["next"][0]
        page = c.get(loc).text
        self.assertIn('name="next" value="/meetups/new?run=n-006"', page)
        email = f"next-{T.RUN}@example.com"
        self.assertEqual(c.post("/signin", {"email": email, "next": nxt}).status, 200)
        _, d = wait_link(email)
        link = re.search(r"(https?://\S+/auth\?t=[\w-]+&next=\S+)", d["text"]).group(1)
        p = urlsplit(link)
        self.assertEqual(parse_qs(p.query)["next"][0], "/meetups/new?run=n-006")
        auth = c.get(p.path + "?" + p.query).text
        self.assertIn('name="next" value="/meetups/new?run=n-006"', auth)
        r = c.post("/auth", {"t": parse_qs(p.query)["t"][0], "next": parse_qs(p.query)["next"][0]})
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"], "/meetups/new?run=n-006")
        form = c.get(r.headers["Location"]).text
        self.assertIn('value="n-006" selected', form)
        # signed-in visitors to /signin?next= go straight there; unsafe values fall back to /me
        self.assertEqual(c.get("/signin?next=%2Fpacks").headers["Location"], "/packs")
        self.assertEqual(c.get("/signin?next=https%3A%2F%2Fevil.com").headers["Location"], "/me")

    def test_unsafe_next_ignored_in_auth(self):
        c = Client("10.7.5.2")
        email = f"next2-{T.RUN}@example.com"
        c.post("/signin", {"email": email, "next": "//evil.com/x"})
        link, d = wait_link(email)
        self.assertNotIn("next=", d["text"])
        p = urlsplit(link)
        r = c.post("/auth", {"t": parse_qs(p.query)["t"][0], "next": "https://evil.com"})
        self.assertTrue(r.headers["Location"].startswith("/me"))


if __name__ == "__main__":
    unittest.main()
