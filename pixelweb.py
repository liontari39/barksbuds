"""Pixel pals (retired): the in-browser pixel-art maker, its /pixel-pals showcase and the landing-page section were
removed. Sprites that dogs already have stay in the photos table (kind='pixel') and are still served so existing
profile pictures and galleries keep working.

  GET  /px/<id>.png, /px/<id>-1x.png, /px/<id>-og.png   upscaled sprite, native sprite, 1200x630 share card
  GET  /pixel-pals[/start], /me/dogs/<id>/pixel[-ai]      old URLs: redirect to /dogs
  POST /me/dogs/<id>/pixel[/...]                          old maker endpoints: 404
"""
import re

import accounts as A

OG_CACHE = {}  # photo id -> png (sprites never change in place)
OLD_PAGES = re.compile(r"/pixel-pals(/start)?/?|/me/dogs/\d+/pixel(-ai)?(/.*)?")


class PixelRoutes:
    def pixel_get(self, path, q):
        m = re.fullmatch(r"/px/(\d+)(|-1x|-og)\.png", path)
        if m:
            self._app_reset(); self.pixel_image(int(m.group(1)), m.group(2)); return True
        if OLD_PAGES.fullmatch(path):
            self._app_reset(); self.redirect("/dogs", 301); return True
        return False

    def pixel_post(self, path, q):
        if re.fullmatch(r"/me/dogs/\d+/pixel(-ai)?(/.*)?", path):
            self._app_reset(); self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"}); return True
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
