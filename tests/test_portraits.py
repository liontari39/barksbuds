"""Pixel portraits: owners request one hand-made portrait per dog (1 to 3 reference photos); the team completes or rejects it via the admin API.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import io, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, outbox, mark as snap  # noqa: E402
from test_packs import multipart  # noqa: E402
import accounts as A  # noqa: E402
import mailer  # noqa: E402
import portraits as P  # noqa: E402
from PIL import Image  # noqa: E402

KEY = {"X-Admin-Key": "test-admin-key"}


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def png(n=256, color=(200, 30, 30)):
    b = io.BytesIO(); Image.new("RGB", (n, n), color).save(b, "PNG"); return b.getvalue()


def admin_get(path, key=KEY):
    return Client("10.12.0.9").req("GET", path, headers=key)


def admin_post(path, fields=None, files=(), key=KEY):
    import uuid
    bnd = "----bbq" + uuid.uuid4().hex
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (fields or {}).items()]
    for name, fn, data in files:
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\nContent-Type: image/png\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    h = {"Content-Type": f"multipart/form-data; boundary={bnd}"}; h.update(key)
    return Client("10.12.0.9").req("POST", path, b"".join(parts), h)


def with_photo(name):
    c, email, uid, (did,) = member(name)
    multipart(c, f"/me/dogs/{did}/photos", {}, [("photos", "a.jpg", jpeg_with_exif())])
    return c, email, uid, did, A.gallery(did)[0]["id"]


def request(c, did, **fields):
    return multipart(c, f"/me/dogs/{did}/portrait", fields, fields.pop("_files", ()))


class PortraitTests(unittest.TestCase):
    def test_full_flow(self):
        c, email, uid, did, ph = with_photo("prt")
        A.set_avatar(did, ph)
        edit = c.get(f"/me/dogs/{did}/edit").text
        self.assertIn('id="portrait-panel"', edit)
        self.assertIn("Our team hand-makes a pixel-art portrait of your pup, usually within a day", edit)
        self.assertIn("Add up to 3 photos. Best results: one full-body shot (standing, facing the camera) plus a clear close-up "
                      "of the face, in good light. More angles help us get markings and ears just right.", edit)
        self.assertIn('type="checkbox" name="photo_id"', edit); self.assertIn('name="photo" type="file" multiple', edit)
        self.assertIn("Get a pixel portrait", c.get(f"/dogs/{A.dog_by_id(did)['slug']}").text)
        self.assertNotIn("Get a pixel portrait", Client().get(f"/dogs/{A.dog_by_id(did)['slug']}").text)
        s = snap()
        r = request(c, did, photo_id=str(ph), note="Brown and white, red collar")
        self.assertEqual(r.status, 303); self.assertIn("m=portrait", r.headers["Location"])
        req = P.latest(did)
        self.assertEqual((req["status"], req["photo_id"], req["owner_note"], req["avatar_at_request"]),
                         ("pending", ph, "Brown and white, red collar", ph))
        notice = TM.wait_mail("portrait-request", "hello@barksbuds.app", s)
        self.assertTrue(notice[0]["subject"].startswith("New pixel portrait request: "))
        self.assertIn("1 reference photo.", notice[0]["text"])
        self.assertNotIn("test-admin-key", json.dumps(notice))
        self.assertIn("Requested on", c.get(f"/me/dogs/{did}/edit").text)
        self.assertIn("in progress", c.get(f"/me/dogs/{did}/edit").text)
        # one per dog
        r = request(c, did, photo_id=str(ph))
        self.assertIn("pre=taken", r.headers["Location"])
        self.assertEqual(len([x for x in P.pending() if x["dog_id"] == did]), 1)
        # admin JSON + photo download
        self.assertEqual(admin_get("/admin/portraits/pending", {}).status, 404)
        self.assertEqual(admin_get("/admin/portraits/pending", {"X-Admin-Key": "wrong"}).status, 404)
        rows = json.loads(admin_get("/admin/portraits/pending").body)
        mine = [x for x in rows if x["id"] == req["id"]][0]
        self.assertEqual(mine["dog"]["id"], did); self.assertEqual(mine["coat_notes"], "Brown and white, red collar")
        self.assertEqual(mine["owner"]["email"], email)
        self.assertTrue(mine["photo_url"].endswith(f"/admin/portraits/{req['id']}/photo.jpg"))
        self.assertEqual((mine["photo_count"], mine["photo_ids"]), (1, [ph]))
        self.assertTrue(mine["photo_urls"][0].endswith(f"/admin/portraits/{req['id']}/photo/1.jpg"))
        self.assertEqual(admin_get(f"/admin/portraits/{req['id']}/photo/1.jpg").body, admin_get(f"/admin/portraits/{req['id']}/photo.jpg").body)
        self.assertEqual(admin_get(f"/admin/portraits/{req['id']}/photo/2.jpg").status, 404)
        ph_r = admin_get(f"/admin/portraits/{req['id']}/photo.jpg")
        self.assertEqual((ph_r.status, ph_r.headers["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(admin_get(f"/admin/portraits/{req['id']}/photo.jpg", {}).status, 404)
        self.assertEqual(Client().get(f"/admin/portraits/{req['id']}/photo.jpg?key=test-admin-key").status, 200)
        self.assertIn("Pixel portrait requests", admin_get("/admin/portraits").text)
        self.assertEqual(Client().get("/admin/portraits").status, 404)
        # complete: stored as kind 'portrait', becomes the main picture, gated ready email
        self.assertEqual(admin_post(f"/admin/portraits/{req['id']}/complete").status, 400)   # no image
        self.assertEqual(admin_post(f"/admin/portraits/{req['id']}/complete", files=[("image", "p.png", png())], key={}).status, 404)
        old_allow = set(mailer.MEETUP_ALLOW)
        mailer.MEETUP_ALLOW.clear(); mailer.MEETUP_ALLOW.add("someone-else@example.com")
        try:
            s = snap()
            r = admin_post(f"/admin/portraits/{req['id']}/complete", files=[("image", "p.png", png())])
            self.assertEqual(r.status, 200)
            out = json.loads(r.body)
            self.assertTrue(out["made_main"]); self.assertFalse(out["emailed"])   # not on the allowlist
        finally:
            mailer.MEETUP_ALLOW.clear(); mailer.MEETUP_ALLOW.update(old_allow)
        self.assertEqual(outbox("portrait-ready", email, s), [])
        pid = out["request"]["portrait_photo_id"]
        self.assertEqual(A.one("SELECT kind FROM photos WHERE id=:i", i=pid)[0], "portrait")
        self.assertEqual(A.dog_by_id(did)["avatar_photo_id"], pid)
        self.assertEqual(P.get(req["id"])["status"], "done")
        self.assertEqual(Client().get(f"/p/{pid}.webp").status, 200)
        self.assertIn(f"/p/{pid}.webp", Client().get("/pixel-pals").text)
        self.assertIn(f"/p/{pid}.webp", Client().get(f"/dogs/{A.dog_by_id(did)['slug']}").text)
        self.assertEqual(json.loads(admin_post(f"/admin/portraits/{req['id']}/complete", files=[("image", "p.png", png())]).body).get("error")[:7], "request")
        self.assertIn("pixel portrait", c.get(f"/me/dogs/{did}/edit").text)
        self.assertIn("pre=taken", request(c, did, photo_id=str(ph)).headers["Location"])
        # owner switches the main picture between the portrait and photos; the portrait is never dropped
        c.post(f"/me/dogs/{did}/photos/{ph}/avatar", {})
        self.assertEqual(A.dog_by_id(did)["avatar_photo_id"], ph)
        self.assertIn("Make it the profile pic", c.get(f"/me/dogs/{did}/edit").text)
        c.post(f"/me/dogs/{did}/photos/{pid}/avatar", {})
        self.assertEqual(A.dog_by_id(did)["avatar_photo_id"], pid)
        c.post(f"/me/dogs/{did}/photos/{pid}/delete", {})
        self.assertIsNotNone(A.one("SELECT id FROM photos WHERE id=:i", i=pid))
        # admin reset frees the slot
        self.assertEqual(admin_post(f"/admin/portraits/{req['id']}/reset").status, 200)
        self.assertIsNone(P.latest(did))
        self.assertIsNotNone(A.one("SELECT id FROM photos WHERE id=:i", i=pid))

    def test_upload_reject_and_no_flip(self):
        c, email, uid, did, ph = with_photo("prr")
        A.set_avatar(did, ph)
        r = request(c, did, _files=[("photo", "new.jpg", jpeg_with_exif())])
        self.assertEqual(r.status, 303); self.assertIn("m=portrait", r.headers["Location"])
        req = P.latest(did)
        self.assertEqual(A.one("SELECT kind FROM photos WHERE id=:i", i=req["photo_id"])[0], "request")
        self.assertEqual(Client().get(f"/p/{req['photo_id']}.webp").status, 404)   # sent-in photos aren't public
        self.assertEqual(A.photo_count(did), 1)
        # reject with a note: shown to the owner, emailed (no allowlist in tests), slot freed
        s = snap()
        r = admin_post(f"/admin/portraits/{req['id']}/reject", {"note": "photo too dark, please try another"})
        self.assertEqual(r.status, 200)
        self.assertEqual(P.get(req["id"])["status"], "rejected")
        self.assertIn("photo too dark, please try another", c.get(f"/me/dogs/{did}/edit").text)
        self.assertEqual(len(TM.wait_mail("portrait-rejected", email, s)), 1)
        self.assertEqual(admin_post(f"/admin/portraits/{req['id']}/reject", {"note": "x"}).status, 409)
        # a new request is allowed; then the owner picks another main picture before it's done
        multipart(c, f"/me/dogs/{did}/photos", {}, [("photos", "b.jpg", jpeg_with_exif())])
        ph2 = A.gallery(did)[1]["id"]
        self.assertEqual(request(c, did, photo_id=str(ph)).status, 303)
        req2 = P.latest(did)
        self.assertEqual(req2["status"], "pending")
        c.post(f"/me/dogs/{did}/photos/{ph2}/avatar", {})
        s = snap()
        out = json.loads(admin_post(f"/admin/portraits/{req2['id']}/complete", files=[("image", "p.png", png())]).body)
        self.assertFalse(out["made_main"]); self.assertTrue(out["emailed"])
        self.assertEqual(A.dog_by_id(did)["avatar_photo_id"], ph2)
        self.assertEqual(len(TM.wait_mail("portrait-ready", email, s)), 1)

    def test_multiple_photos(self):
        c, email, uid, did, ph = with_photo("prm")
        multipart(c, f"/me/dogs/{did}/photos", {}, [("photos", "b.jpg", jpeg_with_exif())])
        ph2 = A.gallery(did)[1]["id"]
        nphotos = A.photo_count(did)
        # more than 3 in total is refused before anything is stored
        r = request(c, did, photo_id=[str(ph), str(ph2)], _files=[("photo", "u1.jpg", jpeg_with_exif()), ("photo", "u2.jpg", jpeg_with_exif())])
        self.assertIn("pre=many", r.headers["Location"])
        self.assertIn("up to 3 photos in total", c.get(r.headers["Location"]).text)
        self.assertIsNone(P.latest(did))
        self.assertEqual(A.one("SELECT COUNT(*) FROM photos WHERE dog_id=:d AND kind='request'", d=did)[0], 0)
        # a bad upload among good ones stores nothing
        r = request(c, did, photo_id=str(ph), _files=[("photo", "u1.jpg", jpeg_with_exif()), ("photo", "x.jpg", b"not an image")])
        self.assertIn("pre=type", r.headers["Location"])
        self.assertIsNone(P.latest(did))
        self.assertEqual(A.one("SELECT COUNT(*) FROM photos WHERE dog_id=:d AND kind='request'", d=did)[0], 0)
        # 2 gallery photos (one repeated) + 1 upload = 3, in order
        s = snap()
        r = request(c, did, photo_id=[str(ph2), str(ph), str(ph2)], _files=[("photo", "u1.jpg", jpeg_with_exif())])
        self.assertEqual(r.status, 303); self.assertIn("m=portrait", r.headers["Location"])
        req = P.latest(did)
        ids = P.photo_ids(req["id"])
        self.assertEqual(len(ids), 3); self.assertEqual(ids[:2], [ph2, ph]); self.assertEqual(req["photo_id"], ph2)
        self.assertEqual(A.one("SELECT kind FROM photos WHERE id=:i", i=ids[2])[0], "request")
        self.assertEqual(Client().get(f"/p/{ids[2]}.webp").status, 404)          # uploads stay private
        self.assertEqual(Client().get(f"/p/{ids[2]}.jpg").status, 404)
        self.assertEqual(A.photo_count(did), nphotos)                            # not added to the gallery
        self.assertIn("3 reference photos", TM.wait_mail("portrait-request", "hello@barksbuds.app", s)[0]["text"])
        j = json.loads(admin_get(f"/admin/portraits/{req['id']}").body)
        self.assertEqual((j["photo_count"], j["photo_ids"]), (3, ids))
        self.assertEqual([u.rsplit("/", 2)[1:] for u in j["photo_urls"]], [["photo", f"{n}.jpg"] for n in (1, 2, 3)])
        self.assertIn(req["id"], [x["id"] for x in json.loads(admin_get("/admin/portraits/pending").body) if x["photo_count"] == 3])
        bodies = [admin_get(f"/admin/portraits/{req['id']}/photo/{n}.jpg") for n in (1, 2, 3)]
        self.assertEqual([b.status for b in bodies], [200] * 3)
        self.assertEqual([b.headers["Content-Disposition"] for b in bodies],
                         [f'inline; filename="portrait-request-{req["id"]}-{n}.jpg"' for n in (1, 2, 3)])
        self.assertEqual(bodies[2].body, bytes(A.one("SELECT full_jpeg FROM photos WHERE id=:i", i=ids[2])[0]))
        self.assertEqual(admin_get(f"/admin/portraits/{req['id']}/photo/4.jpg").status, 404)
        self.assertEqual(admin_get(f"/admin/portraits/{req['id']}/photo/0.jpg").status, 404)
        self.assertEqual(Client().get(f"/admin/portraits/{req['id']}/photo/2.jpg").status, 404)   # no key
        self.assertEqual(admin_get("/admin/portraits").text.count(f"/admin/portraits/{req['id']}/photo/"), 6)   # 3 links + 3 imgs
        self.assertIn("pre=taken", request(c, did, photo_id=str(ph)).headers["Location"])      # still one per dog
        # reset forgets the photo list too; delete_dog cleans up
        admin_post(f"/admin/portraits/{req['id']}/reset")
        self.assertEqual(A.one("SELECT COUNT(*) FROM portrait_request_photos WHERE request_id=:i", i=req["id"])[0], 0)
        request(c, did, photo_id=str(ph))
        rid = P.latest(did)["id"]
        A.delete_dog(did)
        self.assertEqual(A.one("SELECT COUNT(*) FROM portrait_request_photos WHERE request_id=:i", i=rid)[0], 0)

    def test_migrates_single_photo_requests(self):
        c, _, uid, did, ph = with_photo("prg")
        # a request as the single-photo version stored it: only portrait_requests.photo_id
        rid = A.one("""INSERT INTO portrait_requests(dog_id,user_id,photo_id,status,owner_note,avatar_at_request,created_at)
                       VALUES(:d,:u,:p,'pending','',NULL,:t) RETURNING id""", d=did, u=uid, p=ph, t=A.now())[0]
        self.assertEqual(P.photo_ids(rid), [ph])   # falls back to photo_id even before the migration
        P.init_schema(A.STORE) if A.STORE else P._backfill(A.q)   # the startup migration
        P._backfill(A.q)                           # idempotent
        self.assertEqual([tuple(r) for r in A.q("SELECT n, photo_id FROM portrait_request_photos WHERE request_id=:i", i=rid)], [(1, ph)])
        j = json.loads(admin_get(f"/admin/portraits/{rid}").body)
        self.assertEqual((j["photo_count"], j["photo_ids"]), (1, [ph]))
        self.assertEqual(admin_get(f"/admin/portraits/{rid}/photo/1.jpg").status, 200)
        A.delete_dog(did)

    def test_bad_requests(self):
        c, _, _, did, ph = with_photo("prb")
        other, _, _, (odid,) = member("prb2")
        self.assertIn("pre=photo", request(c, did).headers["Location"])                     # nothing picked
        self.assertIn("pre=photo", request(c, did, photo_id="999999").headers["Location"])  # not this dog's photo
        self.assertEqual(request(other, did, photo_id=str(ph)).status, 404)                  # not the owner
        self.assertIn("pre=type", request(c, did, _files=[("photo", "x.jpg", b"not an image")]).headers["Location"])
        self.assertEqual(multipart(c, f"/me/dogs/{did}/portrait", {"photo_id": str(ph), "csrf": "bad"}).status, 403)
        self.assertIsNone(P.latest(did))
        self.assertEqual(admin_post("/admin/portraits/999999/complete", files=[("image", "p.png", png())]).status, 404)
        self.assertEqual(admin_get("/admin/portraits/999999").status, 404)

    def test_seeded_done_and_delete(self):
        c, _, uid, did, ph = with_photo("prs")
        av = A.add_photo(did, png(), kind="avatar"); A.set_avatar(did, av)
        A.q("UPDATE dogs SET seed_key='mike-lily' WHERE id=:d AND NOT EXISTS (SELECT 1 FROM dogs WHERE seed_key='mike-lily')", d=did)
        if A.one("SELECT seed_key FROM dogs WHERE id=:d", d=did)[0] != "mike-lily":   # the seeded Lily exists: her portrait already counts as done
            A.delete_dog(did)
            lily = A.one("SELECT id, avatar_photo_id FROM dogs WHERE seed_key='mike-lily'")
            rows = [r for r in P.recent() if r["dog_id"] == lily[0]]
            self.assertEqual([r["status"] for r in rows], ["done"])   # (other tests may have changed her main picture)
            self.assertEqual(A.one("SELECT kind FROM photos WHERE id=:i", i=rows[0]["result_photo_id"])[0], "portrait")
            return
        try:
            P.mark_seeded_done(); P.mark_seeded_done()
            rows = [r for r in P.recent() if r["dog_id"] == did]
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["status"], rows[0]["result_photo_id"]), ("done", av))
            self.assertEqual(A.one("SELECT kind FROM photos WHERE id=:i", i=av)[0], "portrait")
            self.assertIn(f"/p/{av}.webp", Client().get("/pixel-pals").text)
            c.post(f"/me/dogs/{did}/photos/{ph}/avatar", {})
            self.assertIsNotNone(A.one("SELECT id FROM photos WHERE id=:i", i=av))   # kept when the main picture changes
        finally:
            A.delete_dog(did)
        self.assertEqual([r for r in P.recent() if r["dog_id"] == did], [])
