"""Pixel pals: sprite upload validation, owner-only permissions, storage + re-encoding (metadata stripped), the /px image
routes and share card, profile-picture switching, display on dog cards / pages / attendee lists, hidden dogs, and the
shared JavaScript pipeline (tests/test_pixelpal.js, run with node when it's installed).

Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import io, os, re, shutil, subprocess, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, create, rsvp, mpage  # noqa: E402
from test_packs import multipart  # noqa: E402
import accounts as A  # noqa: E402
from PIL import Image, PngImagePlugin  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


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


def upload(c, dog_id, data, primary="0", fn="sprite.png", **extra):
    fields = {"primary": primary}; fields.update(extra)
    return multipart(c, f"/me/dogs/{dog_id}/pixel", fields, [("sprite", fn, data)])


def dog(did):
    return A.dog_by_id(did)


class PixelTests(unittest.TestCase):
    def test_maker_page_owner_only(self):
        c, _, _, (did,) = member("pxo")
        other, _, _, (oid,) = member("pxx")
        r = c.get(f"/me/dogs/{did}/pixel")
        self.assertEqual(r.status, 200)
        for s in ('id="pxm"', "/pixelpal.js", "/pixelmaker.js", "Tap to select", "Keep brush", "Erase brush", "Crop",
                  "Use as avatar", "Download PNG", "Start over", 'aria-label="Pixel art preview',
                  "Game Sprite", 'value="eyes"', 'value="nose"', 'id="pxface"', 'id="pxblush"', 'id="pxmouth"', 'id="pxchibi"',
                  "Reset eyes &amp; nose", '<option value="ink">', 'id="pxeyes"', '<option value="friendly" selected>',
                  '<option value="48" selected>', "Small (32 px)", "Large (64 px)", "Chunky", "32 px, extra cute",
                  '/img/style-game.png', '/img/style-chunky.png', '<details class="pxadjust"><summary>Adjust</summary>'):
            self.assertIn(s, r.text)
        # exactly two styles: Game Sprite (default, first, pressed) and Chunky; the old presets are code-only
        self.assertIn('data-preset="game" aria-pressed="true"', r.text)
        self.assertIn('data-preset="chunky" aria-pressed="false"', r.text)
        self.assertEqual(r.text.count("data-preset="), 2)
        self.assertLess(r.text.index('data-preset="game"'), r.text.index('data-preset="chunky"'))
        for gone in ('data-preset="classic"', 'data-preset="retro"', 'data-preset="soft"', "Retro 8-bit"):
            self.assertNotIn(gone, r.text)
        # the fine-tune controls sit inside the Adjust expander
        a0 = r.text.index('<details class="pxadjust">'); adj = r.text[a0:r.text.index("</details>", a0)]
        for ctl in ('id="pxsize"', 'id="pxdetail"', 'id="pxcolors"', 'id="pxoutline"', 'id="pxeyes"', 'id="pxchibi"'):
            self.assertIn(ctl, adj)
        self.assertEqual(other.get(f"/me/dogs/{did}/pixel").status, 404)
        anon = Client("10.11.0.9").get(f"/me/dogs/{did}/pixel")
        self.assertEqual(anon.status, 303)
        self.assertTrue(anon.headers["Location"].startswith("/signin?next="))
        # owner's dog page + edit page link to the maker
        self.assertIn(f"/me/dogs/{did}/pixel", c.get(f"/dogs/{dog(did)['slug']}").text)
        self.assertIn("Make my pixel pal", c.get(f"/me/dogs/{did}/edit").text)
        self.assertNotIn(f"/me/dogs/{did}/pixel", other.get(f"/dogs/{dog(did)['slug']}").text)

    def test_upload_validation(self):
        c, _, _, (did,) = member("pxv")
        bad = {
            "jpeg": jpeg_with_exif(size=(48, 48)),
            "not square": sprite_png(48, w=60),
            "too small": sprite_png(8),
            "too large": sprite_png(160),
            "empty": (lambda b: (Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(b, "PNG"), b.getvalue())[1])(io.BytesIO()),
            "garbage": b"\x89PNG\r\n\x1a\n" + b"nope" * 50,
        }
        for label, data in bad.items():
            r = upload(c, did, data)
            self.assertEqual(r.status, 400, label)
            self.assertFalse(r.json()["ok"] if hasattr(r, "json") else '"ok": true' in r.text, label)
        # oversize file (a valid PNG padded with a huge text chunk)
        info = PngImagePlugin.PngInfo(); info.add_text("pad", os.urandom(160_000).hex())
        b = io.BytesIO(); Image.open(io.BytesIO(sprite_png())).save(b, "PNG", pnginfo=info)
        r = upload(c, did, b.getvalue())
        self.assertIn(r.status, (400, 413))
        self.assertIn("too big", r.text)
        # request without a file, without csrf, and signed out
        self.assertEqual(multipart(c, f"/me/dogs/{did}/pixel", {"primary": "1"}).status, 400)
        self.assertEqual(multipart(c, f"/me/dogs/{did}/pixel", {"csrf": "x"}, [("sprite", "s.png", sprite_png())]).status, 403)
        anon = Client("10.11.0.10")
        self.assertEqual(multipart(anon, f"/me/dogs/{did}/pixel", {"csrf": "x"}, [("sprite", "s.png", sprite_png())]).status, 401)
        self.assertIsNone(dog(did)["pixel_photo_id"])

    def test_owner_only_actions(self):
        c, _, _, (did,) = member("pxa")
        other, _, _, _ = member("pxb")
        r = upload(other, did, sprite_png(), primary="1")
        self.assertEqual(r.status, 404)
        self.assertIsNone(dog(did)["pixel_photo_id"])
        self.assertEqual(upload(c, did, sprite_png()).status, 200)
        pid = dog(did)["pixel_photo_id"]
        for action in ("primary", "photo", "delete"):
            self.assertEqual(other.post(f"/me/dogs/{did}/pixel/{action}", {}).status, 404, action)
        self.assertEqual(dog(did)["pixel_photo_id"], pid)
        self.assertEqual(c.post(f"/me/dogs/{did}/pixel/delete", {}, csrf=False).status, 403)
        # the gallery photo routes can't touch the sprite
        c.post(f"/me/dogs/{did}/photos/{pid}/delete", {})
        self.assertEqual(dog(did)["pixel_photo_id"], pid)
        self.assertEqual(Client().get(f"/px/{pid}-1x.png").status, 200)

    def test_storage_reencode_and_routes(self):
        c, _, _, (did,) = member("pxs")
        raw = sprite_png(48, meta=True)
        self.assertIn(b"secret", raw)
        r = upload(c, did, raw, primary="1")
        self.assertEqual(r.status, 200, r.text)
        self.assertIn('"ok": true', r.text)
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
        r = c.post(f"/me/dogs/{did}/pixel/primary", {})
        self.assertEqual(r.status, 303)
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
        c.post(f"/me/dogs/{did}/pixel/photo", {})
        self.assertFalse(dog(did)["pixel_primary"])
        self.assertNotIn(f'class="pxav" src="/px/{pid}', mpage(c, mid).text)
        c.post(f"/me/dogs/{did}/pixel/delete", {})
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

    def test_vendored_segmenter_assets(self):
        c = Client()
        r = c.req("GET", "/vendor/mediapipe/vision_wasm_internal.wasm", headers={"Accept-Encoding": "gzip"})
        self.assertEqual((r.status, r.headers["Content-Type"], r.headers.get("Content-Encoding")), (200, "application/wasm", "gzip"))
        self.assertIn("max-age=604800", r.headers["Cache-Control"])
        r = c.get("/vendor/mediapipe/vision_bundle.mjs")
        self.assertTrue(r.headers["Content-Type"].startswith("text/javascript"))
        self.assertEqual(c.get("/vendor/mediapipe/magic_touch.tflite").status, 200)
        self.assertIn("Apache License", c.get("/vendor/mediapipe/LICENSE").text)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_pixel_pals_showcase_start_and_nudge(self):
        anon = Client("10.11.0.21")
        # landing section + nav/footer links
        home = anon.get("/").text
        for s in ('id="pixel-pals"', "Turn your dog into a classic game character", "FREE", 'href="/pixel-pals/start"',
                  "/img/pp-lily.png", "/img/pp-maggie.png", 'href="/pixel-pals"'):
            self.assertIn(s, home)
        self.assertNotIn("{{PIXEL_PALS}}", home)
        # public page: gallery of public dogs with sprites, share card, indexable, in the sitemap and menu
        c, _, _, (did,) = member("ppg")
        upload(c, did, sprite_png(), primary="1")
        A.add_photo(did, jpeg_with_exif())
        r = anon.get("/pixel-pals")
        self.assertEqual(r.status, 200)
        px = dog(did)["pixel_photo_id"]
        self.assertIn(f'src="/px/{px}.png"', r.text)
        self.assertIn('content="index,follow"', r.text)
        self.assertRegex(r.text, r'og:image" content="[^"]+/px/\d+-og\.png"')
        self.assertIn("Make your pixel pal", r.text)
        self.assertIn("/pixel-pals</loc>", anon.get("/sitemap.xml").text)
        self.assertIn('href="/pixel-pals"', c.get("/dogs").text)
        A.set_hidden(did, True) if hasattr(A, "set_hidden") else A.q("UPDATE dogs SET hidden=1 WHERE id=:i", i=did)
        self.assertNotIn(f'src="/px/{px}.png"', anon.get("/pixel-pals").text, "hidden dogs stay out of the gallery")
        A.q("UPDATE dogs SET hidden=0 WHERE id=:i", i=did)
        # CTA: signed out -> sign in and back; one dog -> its maker; no dog -> add one; several -> chooser
        r = anon.get("/pixel-pals/start")
        self.assertEqual(r.status, 303); self.assertEqual(r.headers["Location"], "/signin?next=%2Fpixel-pals%2Fstart")
        self.assertEqual(c.get("/pixel-pals/start").headers["Location"], f"/me/dogs/{did}/pixel")
        c0, _, _, _ = member("ppz", dogs=0)
        self.assertEqual(c0.get("/pixel-pals/start").headers["Location"], "/me/dogs/new?px=1")
        c2, _, _, (d1, d2) = member("ppm", dogs=2)
        r = c2.get("/pixel-pals/start")
        self.assertEqual(r.status, 200)
        self.assertIn(f"/me/dogs/{d1}/pixel", r.text); self.assertIn(f"/me/dogs/{d2}/pixel", r.text)
        # nudge after the first photos, only for a dog with photos and no sprite
        self.assertNotIn("pxnudge", c2.get(f"/me/dogs/{d1}/edit?m=photos").text, "no photos yet: no nudge")
        A.add_photo(d1, jpeg_with_exif())
        t = c2.get(f"/me/dogs/{d1}/edit?m=photos").text
        self.assertIn("pxnudge", t); self.assertIn(f'href="/me/dogs/{d1}/pixel">Make my pixel pal', t)
        self.assertNotIn("pxnudge", c2.get(f"/me/dogs/{d1}/edit").text, "only right after adding photos")
        self.assertNotIn("pxnudge", c.get(f"/me/dogs/{did}/edit?m=photos").text, "already has a sprite")

    def test_pixelpal_js_pipeline(self):
        p = subprocess.run(["node", os.path.join(HERE, "test_pixelpal.js")], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("pixelpal tests passed", p.stdout)


if __name__ == "__main__":
    unittest.main()
