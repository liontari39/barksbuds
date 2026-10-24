"""Pixel pals: owners turn a dog photo into a game-style pixel-art sprite.

All the image work happens in the browser (public/pixelmaker.js + public/pixelpal.js, with the MediaPipe
interactive segmenter vendored under public/vendor/mediapipe). The server only receives the finished sprite PNG,
validates and re-encodes it (accounts.process_pixel_png) and stores it in the photos table (kind='pixel').

  GET  /me/dogs/<id>/pixel                         the maker (owner only)
  POST /me/dogs/<id>/pixel                         upload a sprite (multipart: csrf, sprite, primary=0|1) -> JSON
  POST /me/dogs/<id>/pixel/(primary|photo|delete)  use the sprite / the photo as profile pic, or remove the sprite
  GET  /px/<id>.png, /px/<id>-1x.png, /px/<id>-og.png   upscaled sprite, native sprite, 1200x630 share card
"""
import html, json, re

import accounts as A
import webapp as W

e = html.escape
W.FLASH.update({"px_saved": "Pixel pal saved.", "px_primary": "The pixel pal is now the profile picture.",
                "px_photo": "The photo is the profile picture again.", "px_deleted": "Pixel pal removed."})
MAX_PIXEL_REQUEST = 400 * 1024
OG_CACHE = {}  # photo id -> png (sprites never change in place: a remake gets a new id)


class PixelRoutes:
    def pixel_get(self, path, q):
        m = re.fullmatch(r"/px/(\d+)(|-1x|-og)\.png", path)
        if m:
            self._app_reset(); self.pixel_image(int(m.group(1)), m.group(2)); return True
        m = re.fullmatch(r"/me/dogs/(\d+)/pixel/?", path)
        if m:
            self._app_reset()
            d = self.own_dog(int(m.group(1)))
            if d is not None:
                self.pixel_maker(d)
            return True
        return False

    def pixel_post(self, path, q):
        m = re.fullmatch(r"/me/dogs/(\d+)/pixel", path)
        if m:
            self._app_reset(); self.post_pixel(int(m.group(1))); return True
        m = re.fullmatch(r"/me/dogs/(\d+)/pixel/(primary|photo|delete)", path)
        if m:
            self._app_reset(); self.post_pixel_action(int(m.group(1)), m.group(2)); return True
        return False

    # ------------------------------------------------------------ images
    def pixel_image(self, pid, variant):
        etag = '"px%d%s"' % (pid, variant)
        hdr = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": etag}
        if etag in (self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            for k, v in hdr.items():
                self.send_header(k, v)
            self.end_headers()
            return
        got = A.pixel_blob(pid, "native" if variant in ("-1x", "-og") else "big")
        if got is None:
            return self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"})
        blob, name = got
        if variant == "-og":
            if pid not in OG_CACHE:
                if len(OG_CACHE) > 50:
                    OG_CACHE.clear()
                OG_CACHE[pid] = A.pixel_og_png(blob, name)
            blob = OG_CACHE[pid]
        return self._emit(200, blob, "image/png", hdr)

    # ------------------------------------------------------------ owner actions
    def _pixel_json(self, code, obj):
        return self._emit(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def post_pixel(self, dog_id):
        u = self.user()
        if not u:
            return self._pixel_json(401, {"ok": False, "error": "Please sign in again, then save."})
        d = A.dog_by_id(dog_id)
        if not d or d["user_id"] != u["id"]:
            return self._pixel_json(404, {"ok": False, "error": "We couldn't find that dog on your account."})
        f = self.read_form(MAX_PIXEL_REQUEST)
        if f is None:
            return self._pixel_json(413, {"ok": False, "error": "That sprite file is too big."})
        if not self.csrf_ok(f):
            return self._pixel_json(403, {"ok": False, "error": "Your session timed out. Refresh the page and try again."})
        files = [x for x in f.files if x[0] == "sprite"]
        if not files:
            return self._pixel_json(400, {"ok": False, "error": "No sprite was uploaded."})
        if not A.LIMITER.allow(f"pixel:{u['id']}", 30, 3600):
            return self._pixel_json(429, {"ok": False, "error": "That's a lot of pixel pals! Try again in a little while."})
        try:
            pid = A.set_pixel(d["id"], files[0][2], primary=f.get("primary") == "1")
        except A.BadImage as ex:
            return self._pixel_json(400, {"ok": False, "error": str(ex)})
        print(f"pixel: dog {d['id']} saved sprite {pid}", flush=True)
        return self._pixel_json(200, {"ok": True, "id": pid, "url": f"/px/{pid}.png", "page": f"/dogs/{d['slug']}"})

    def post_pixel_action(self, dog_id, action):
        d = self.own_dog(dog_id)
        if d is None:
            return
        if self._form_or_fail() is None:
            return
        if action == "delete":
            A.clear_pixel(d["id"]); flash = "px_deleted"
        else:
            A.set_pixel_primary(d["id"], action == "primary"); flash = "px_" + action
        return self.redirect(f"/me/dogs/{d['id']}/edit?m={flash}#pixel-panel")

    # ------------------------------------------------------------ the maker page
    def pixel_maker(self, d):
        nm = e(d["name"])
        photos = A.gallery(d["id"])
        picks = "".join(
            f'<li><button type="button" class="pxpick" data-src="/p/{p["id"]}.jpg" aria-label="Use photo {i + 1}">'
            f'<img src="/p/{p["id"]}.webp" alt="" loading="lazy"></button></li>' for i, p in enumerate(photos))
        picks_html = (f'<ul class="pxpicks">{picks}</ul>' if picks else
                      f'<p class="muted">{nm} has no photos on BarksBuds yet, so pick one from your device.</p>')
        current = (f'<p class="small muted" style="margin:14px 0 0">{nm} already has a pixel pal: '
                   f'<img class="pxinline" src="/px/{d["pixel_photo_id"]}-1x.png" alt="current pixel pal" width="40" height="40">'
                   f' Saving a new one replaces it.</p>') if d.get("pixel_photo_id") else ""
        cfg = {"dog": d["id"], "name": d["name"], "slug": d["slug"], "csrf": self.csrf_token(),
               "primary": bool(d.get("pixel_primary"))}
        sw = "".join(f'<label class="sw sw-{k}"><input type="radio" name="backdrop" value="{k}"{" checked" if k == "none" else ""}>'
                     f'<span title="{t}"><span class="vh">{t}</span></span></label>'
                     for k, t in (("none", "See-through"), ("cream", "Cream"), ("sunny", "Sunny"), ("sky", "Sky"), ("mint", "Mint"), ("rose", "Rose")))
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">pixel pal</span><h1>Make {nm}'s pixel pal</h1>
<p class="lead">Turn a photo into a crisp little piece of game-style pixel art. Everything happens right here on your device: only the finished sprite is saved.</p></div></section>
<section class="section" style="padding-top:28px"><div class="wrap pxm" id="pxm" data-cfg="{e(json.dumps(cfg))}">
<noscript><p class="notice">The pixel pal maker needs JavaScript turned on.</p></noscript>
<div class="panel" id="pxpick"><h2><span class="stepn">1</span> Pick a photo</h2>
<p class="hint">A clear, side-on or face-on shot where {nm} fills most of the frame works best.</p>
{picks_html}
<div class="pxfile"><label class="btn btn-ghost btn-sm" for="pxfile"><svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg> Use another photo</label>
<input id="pxfile" type="file" accept="image/*" class="vh-file"><span class="small muted">It stays on your device.</span></div>
{current}<p class="err" id="pxpickerr" role="alert"></p></div>

<div class="pxed" id="pxed" hidden>
<div class="panel pxsel"><h2><span class="stepn">2</span> Select {nm}</h2>
<div class="pxtools" role="radiogroup" aria-label="Selection tool">
<label><input type="radio" name="tool" value="tap" checked><span><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg>Tap to select</span></label>
<label><input type="radio" name="tool" value="keep"><span>Keep brush</span></label>
<label><input type="radio" name="tool" value="erase"><span>Erase brush</span></label>
<label><input type="radio" name="tool" value="crop"><span>Crop</span></label>
<label><input type="radio" name="tool" value="eyes"><span>Eyes</span></label>
<label><input type="radio" name="tool" value="nose"><span>Nose</span></label></div>
<div class="pxbrush"><label for="pxbsize">Brush size</label><input id="pxbsize" type="range" min="4" max="60" value="18"></div>
<div class="pxcanvas"><canvas id="pxsrc" tabindex="0" role="img" aria-label="Photo of {nm}. The selected area is highlighted." aria-describedby="pxkeys"></canvas></div>
<p class="small muted" id="pxkeys">Tap on {nm} to select; tap more spots to add missed parts. Use the brushes to touch up edges.
For cartoon eyes, pick Eyes and tap the center of each eye, then pick Nose and tap the nose.
Keyboard: arrow keys move the cursor, Enter applies the tool.</p>
<div class="pxrowbtn"><button type="button" class="btn btn-ghost btn-sm" id="pxundo" disabled>Undo</button>
<button type="button" class="btn btn-ghost btn-sm" id="pxclear">Clear selection</button>
<button type="button" class="btn btn-ghost btn-sm" id="pxall">Keep everything in crop</button>
<button type="button" class="btn btn-ghost btn-sm" id="pxfacereset">Reset eyes &amp; nose</button></div>
<p class="small" id="pxfacest" aria-live="polite"></p>
<p class="small" id="pxstatus" role="status" aria-live="polite"></p></div>

<div class="panel pxstyle"><h2><span class="stepn">3</span> Style it</h2>
<div class="pxprev"><div class="pxba" role="group" aria-label="Compare">
<button type="button" data-v="after" aria-pressed="true">After</button><button type="button" data-v="before" aria-pressed="false">Before</button></div>
<canvas id="pxout" width="384" height="384" role="img" aria-label="Pixel art preview of {nm}"></canvas>
<canvas id="pxbefore" width="384" height="384" role="img" aria-label="The selected part of the photo" hidden></canvas></div>
<div class="pxpresets" role="group" aria-label="Style presets">
<button type="button" data-preset="game" aria-pressed="true">Game Sprite</button><button type="button" data-preset="classic" aria-pressed="false">Classic</button><button type="button" data-preset="retro" aria-pressed="false">Retro 8-bit</button><button type="button" data-preset="soft" aria-pressed="false">Soft</button></div>
<div class="pxctl">
<div><label for="pxsize">Size</label><select id="pxsize"><option value="24">Small (24 px)</option><option value="32" selected>Medium (32 px)</option><option value="40">Large (40 px)</option></select></div>
<div><label for="pxdetail">Detail</label><input id="pxdetail" type="range" min="0" max="4" step="1" value="2"></div>
<div><label for="pxcolors">Colors <output id="pxcolorsv">10</output></label><input id="pxcolors" type="range" min="4" max="24" step="1" value="10"></div>
<div><label for="pxoutline">Outline</label><select id="pxoutline"><option value="ink">Ink (game)</option><option value="dark">Dark</option><option value="soft">Soft</option><option value="none">None</option></select></div>
<div class="pxchecks"><label><input type="checkbox" id="pxshadow" checked> Shadow</label><label><input type="checkbox" id="pxdither"> Retro dither</label></div>
<div class="pxchecks"><label><input type="checkbox" id="pxface" checked> Cartoon eyes &amp; nose</label><label><input type="checkbox" id="pxblush" checked> Blush</label></div>
<div><label for="pxmouth">Mouth</label><select id="pxmouth"><option value="none">None</option><option value="smile">Smile</option><option value="tongue" selected>Tongue out</option></select></div>
<div><label for="pxeyes">Eyes</label><select id="pxeyes"><option value="dots" selected>Dots</option><option value="happy">Happy (^ ^)</option></select></div>
<div><label for="pxchibi">Big head</label><input id="pxchibi" type="range" min="0" max="1.5" step="0.25" value="1" aria-describedby="pxchibih"><span class="small muted" id="pxchibih">Needs the eyes marked</span></div>
<fieldset class="pxsw"><legend>Background</legend>{sw}</fieldset></div>
<div class="pxsave"><div class="pxrowbtn"><button type="button" class="btn" id="pxsavebtn" data-primary="1">Use as avatar</button>
<button type="button" class="btn btn-ghost" id="pxsave2" data-primary="0">Save, keep photo as avatar</button>
<button type="button" class="btn btn-ghost" id="pxdl">Download PNG</button>
<button type="button" class="btn btn-ghost" id="pxreset">Start over</button></div>
<p class="small" id="pxsaved" role="status" aria-live="polite"></p></div></div>
</div></div></section>"""
        js = '<script src="/pixelpal.js?v=3"></script><script type="module" src="/pixelmaker.js?v=3"></script>'
        return self.page(f"Make {d['name']}'s pixel pal", body, scripts=js, active="dogs")
