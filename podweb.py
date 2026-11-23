"""301 redirects from the never-shipped /puppy-pods URLs to pack pages."""
import re
from urllib.parse import urlencode

import packs as P
import puppypods as PP
from packweb import pack_path


def review_rows_html(key):
    return ""


def handle_review_action(f):
    return False


class PuppyPodRoutes:
    def _packs_list(self, q):
        extra = {k: v[0] for k, v in (q or {}).items() if k not in ("kind",) and v and v[0]}
        dest = "/packs?kind=puppy"
        if extra:
            dest += "&" + urlencode(extra)
        return dest

    def pod_get(self, path, q):
        if path in ("/puppy-pods", "/puppy-pods/"):
            self.redirect(self._packs_list(q), 301)
            return True
        if path == "/puppy-pods/new":
            self.redirect("/packs/new?kind=puppy", 301)
            return True
        m = re.fullmatch(r"/puppy-pods/(\d+)(?:-[a-z0-9-]*)?/?", path)
        if m:
            p = P.get(int(m.group(1)))
            self.redirect(pack_path(p) if p else "/packs?kind=puppy", 301)
            return True
        return False

    def pod_post(self, path, q):
        if path == "/puppy-pods/new":
            self.redirect("/packs/new?kind=puppy", 301)
            return True
        m = re.fullmatch(r"/puppy-pods/(\d+)(?:-[a-z0-9-]*)?/(join|leave|report|check|cancel)", path)
        if m:
            p = P.get(int(m.group(1)))
            self.redirect(pack_path(p) if p else "/packs?kind=puppy", 301)
            return True
        if path.startswith("/puppy-pods"):
            self.redirect("/packs?kind=puppy", 301)
            return True
        return False
