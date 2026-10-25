"""Pixel pals (retired): the maker, its /pixel-pals showcase and landing section are gone and their old URLs redirect
to /dogs; sprites dogs already have are still stored, re-encoded, served from /px/ and shown on their pages.

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import io, os, sys, types, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, create, rsvp, mpage  # noqa: E402
from test_packs import multipart  # noqa: E402
import accounts as A  # noqa: E402
from PIL import Image, PngImagePlugin  # noqa: E402


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def sprite_png(n=48, meta=False, mode="RGBA", w=None):
    """A small checkered sprite with a transparent border, optionally carrying text + EXIF metadata."""
    im = Image.new(mode, (w or n, n), (0, 0, 0, 0) if mode == "RGBA" else (255, 255, 255))
    for y in range(4, n - 4):
        for x in range(4, (w or n) - 4):
            im.putpixel((x, y), (200, 30, 30, 255) if (x // 4 + y // 4) % 2 else (42, 38, 34, 255))
    kw = {}
    if meta:
        info = PngImagePlugin.PngInfo(); info.add_text("Comment", "GPS 40.79,-73.70 secret"); kw["pnginfo"] = info
        ex = Image.Exif(); ex[0x010F] = "PhoneCo"; kw["exif"] = ex.tobytes()
    b = io.BytesIO(); im.save(b, "PNG", **kw)
    return b.getvalue()


def upload(c, dog_id, data, primary="0"):
    """Sprites can no longer be uploaded through the site; existing ones live on, so store one directly."""
    A.set_pixel(dog_id, data, primary=primary == "1")
    return types.SimpleNamespace(status=200)


def dog(did):
    return A.dog_by_id(did)


class PixelTests(unittest.TestCase):
    def test_maker_and_showcase_retired(self):
        c, _, _, (did,) = member("pxgone")
        anon = Client("10.11.0.31")
        for path in ("/pixel-pals", "/pixel-pals/", "/pixel-pals/start", f"/me/dogs/{did}/pixel", f"/me/dogs/{did}/pixel/",
                     f"/me/dogs/{did}/pixel-ai", "/me/dogs/999999/pixel"):
            for who in (c, anon):
                r = who.get(path)
                self.assertEqual((r.status, r.headers.get("Location")), (301, "/dogs"), path)
        for path in (f"/me/dogs/{did}/pixel", f"/me/dogs/{did}/pixel/primary", f"/me/dogs/{did}/pixel/delete"):
            self.assertEqual(c.post(path, {}).status, 404, path)
        r = multipart(c, f"/me/dogs/{did}/pixel", {"primary": "1"}, [("sprite", "s.png", sprite_png())])
        self.assertEqual(r.status, 404)
        self.assertIsNone(dog(did)["pixel_photo_id"])
        for asset in ("/pixelpal.js", "/pixelmaker.js", "/pixelai-worker.js", "/vendor/mediapipe/vision_bundle.mjs",
                      "/vendor/animegan/face_paint_512_v2.onnx", "/img/pp-lily.png", "/img/style-game.png"):
            self.assertEqual(anon.get(asset).status, 404, asset)
        slug = dog(did)["slug"]
        for page in ("/", "/dogs", f"/dogs/{slug}", f"/me/dogs/{did}/edit", "/me", "/runs", "/tips", "/sitemap.xml"):
            t = c.get(page).text
            self.assertNotIn("/pixel-pals", t, page); self.assertNotIn(f"/me/dogs/{did}/pixel", t, page)
            self.assertNotIn("Make my pixel pal", t, page); self.assertNotIn('id="pixel-pals"', t, page)
        self.assertNotIn("{{PIXEL_PALS}}", anon.get("/").text)

    def test_storage_reencode_and_routes(self):
        c, _, _, (did,) = member("pxs")
        raw = sprite_png(48, meta=True)
        self.assertIn(b"secret", raw)
        r = upload(c, did, raw, primary="1")
        self.assertEqual(r.status, 200)
        d = dog(did)
        pid = d["pixel_photo_id"]
        self.assertTrue(pid and d["pixel_primary"])
        row = A.one("SELECT kind, width, height, full_jpeg, thumb_webp FROM photos WHERE id=:i", i=pid)
        self.assertEqual((row[0], row[1], row[2]), ("pixel", 48, 48))
        native, big = bytes(row[3]), bytes(row[4])
        for blob in (native, big):
            self.assertNotIn(b"secret", blob); self.assertNotIn(b"PhoneCo", blob)
            self.assertNotIn(b"tEXt", blob); self.assertNotIn(b"eXIf", blob)
        n = Image.open(io.BytesIO(native)); self.assertEqual((n.size, n.mode), ((48, 48), "RGBA"))
        self.assertEqual(n.getpixel((0, 0))[3], 0)  # transparency kept
        # routes: native, upscaled (exact nearest-neighbor), share card
        r1 = Client().get(f"/px/{pid}-1x.png")
        self.assertEqual((r1.status, r1.headers["Content-Type"]), (200, "image/png"))
        self.assertIn("immutable", r1.headers["Cache-Control"])
        rb = Client().get(f"/px/{pid}.png")
        b = Image.open(io.BytesIO(rb.body)).convert("RGBA")
        self.assertGreaterEqual(b.width, 512); self.assertEqual(b.width % 48, 0)
        k = b.width // 48
        for x, y in ((5, 5), (20, 33), (0, 0), (47, 47)):
            self.assertEqual(b.getpixel((x * k + k - 1, y * k)), n.getpixel((x, y)))
        og = Client().get(f"/px/{pid}-og.png")
        self.assertEqual(og.status, 200)
        self.assertEqual(Image.open(io.BytesIO(og.body)).size, (1200, 630))
        self.assertEqual(Client().get(f"/px/{pid}.png", ).status, 200)
        self.assertEqual(Client().req("GET", f"/px/{pid}.png", headers={"If-None-Match": f'"px{pid}"'}).status, 304)
        # the photo routes don't serve sprites, and unknown ids 404
        self.assertEqual(Client().get(f"/p/{pid}.jpg").status, 404)
        self.assertEqual(Client().get("/px/999999.png").status, 404)
        # replacing removes the old sprite row
        self.assertEqual(upload(c, did, sprite_png(32)).status, 200)
        d2 = dog(did)
        self.assertNotEqual(d2["pixel_photo_id"], pid)
        self.assertFalse(d2["pixel_primary"])
        self.assertIsNone(A.one("SELECT id FROM photos WHERE id=:i", i=pid))
        self.assertEqual(Client().get(f"/px/{pid}-1x.png").status, 404)
        # palette-mode PNGs are accepted and normalized to RGBA
        pal = io.BytesIO(); Image.open(io.BytesIO(sprite_png(64))).convert("P").save(pal, "PNG")
        self.assertEqual(upload(c, did, pal.getvalue()).status, 200)
        self.assertEqual(A.one("SELECT width FROM photos WHERE id=:i", i=dog(did)["pixel_photo_id"])[0], 64)

    def test_profile_picture_switch_and_display(self):
        c, _, _, (did,) = member("pxd")
        multipart(c, f"/me/dogs/{did}/photos", {}, [("photos", "a.jpg", jpeg_with_exif())])
        slug = dog(did)["slug"]
        self.assertEqual(upload(c, did, sprite_png()).status, 200)
        pid = dog(did)["pixel_photo_id"]
        page = Client().get(f"/dogs/{slug}").text
        self.assertIn(f"/px/{pid}-1x.png", page)          # sprite panel + toggle
        self.assertIn('class="avsw"', page)
        self.assertIn('data-v="pixel" hidden', page)       # photo is still the primary avatar
        self.assertNotIn(f"/px/{pid}-og.png", page)
        self.assertIn("pixel art", page)
        browse = Client().get("/dogs").text
        self.assertIn(f'class="pxbadge" src="/px/{pid}-1x.png"', browse)
        # make the sprite the profile picture
        A.set_pixel_primary(did, True)
        self.assertTrue(dog(did)["pixel_primary"])
        page = Client().get(f"/dogs/{slug}").text
        self.assertIn('data-v="photo" hidden', page)
        self.assertIn(f'content="http://127.0.0.1:{T.PORT}/px/{pid}-og.png"', page)
        self.assertIn(f'class="ph pxph"><img src="/px/{pid}-1x.png"', Client().get("/dogs").text)
        # attendee list shows the sprite
        mid, _ = create(c)
        rsvp(c, mid, [did])
        self.assertIn(f'class="pxav" src="/px/{pid}-1x.png"', mpage(c, mid).text)
        self.assertEqual(A.tile_img({"pixel": pid, "photo": 5}), A.tile_img({"pixel": pid}))
        # back to the photo, then remove the sprite
        A.set_pixel_primary(did, False)
        self.assertFalse(dog(did)["pixel_primary"])
        self.assertNotIn(f'class="pxav" src="/px/{pid}', mpage(c, mid).text)
        A.clear_pixel(did)
        self.assertIsNone(dog(did)["pixel_photo_id"])
        self.assertNotIn("/px/", Client().get(f"/dogs/{slug}").text)

    def test_hidden_dog_sprites_404(self):
        c, _, _, (did,) = member("pxh")
        self.assertEqual(upload(c, did, sprite_png(), primary="1").status, 200)
        pid = dog(did)["pixel_photo_id"]
        A.set_dog_hidden(did, 1)
        try:
            for v in ("", "-1x", "-og"):
                self.assertEqual(Client().get(f"/px/{pid}{v}.png").status, 404, v)
        finally:
            A.set_dog_hidden(did, 0)
        self.assertEqual(Client().get(f"/px/{pid}.png").status, 200)

    def test_delete_dog_removes_sprite(self):
        c, _, _, (did,) = member("pxk")
        upload(c, did, sprite_png())
        pid = dog(did)["pixel_photo_id"]
        A.delete_dog(did)
        self.assertIsNone(A.one("SELECT id FROM photos WHERE id=:i", i=pid))
