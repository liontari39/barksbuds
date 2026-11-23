"""App-mode shell (tab bar, app bar, sheets). Regular browser visits stay unchanged.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, new_dog, RUN  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


class AppShellAssets(unittest.TestCase):
    def test_pages_link_shell_assets_and_boot_script(self):
        home = Client().get("/").text
        self.assertIn("/app-shell.css?v=2", home)
        self.assertIn("/app-shell.js?v=2", home)
        self.assertIn("bb-app", home)  # boot script mentions the class
        self.assertNotIn('class="bb-app"', home.split("<body")[0])  # not hardcoded on <html>
        self.assertIn("display-mode:standalone", home)
        self.assertEqual(Client().get("/app-shell.css?v=2").status, 200)
        self.assertEqual(Client().get("/app-shell.js?v=2").status, 200)
        runs = Client().get("/runs").text
        self.assertIn("/app-shell.css?v=2", runs)
        self.assertIn("/app-shell.js?v=2", runs)
        me_signin = Client().get("/signin").text
        self.assertIn("/app-shell.css?v=2", me_signin)

    def test_css_is_gated_and_js_noops_outside_app(self):
        css = (PUBLIC / "app-shell.css").read_text()
        # every structural rule should be scoped; ignore at-rules / keyframes / comments
        unguarded = []
        for line in css.splitlines():
            s = line.strip()
            if not s or s.startswith(("/*", "*", "}", "@", "to{", "from{", "to {", "from {")):
                continue
            if s[0] in ("{",) or s.endswith("{") or "{" in s:
                if s.startswith("@") or s.startswith("html.bb-app") or s.startswith("to") or s.startswith("from"):
                    continue
                if "html.bb-app" not in s:
                    unguarded.append(s)
        self.assertEqual(unguarded, [], "un-gated CSS would change the website")
        js = (PUBLIC / "app-shell.js").read_text()
        self.assertIn("if (!isApp()) return", js)
        self.assertIn("bb-tabbar", js)
        self.assertIn("Check in", js)
        self.assertIn("Haptics", js)
        self.assertIn("prefers-reduced-motion", js)
        self.assertIn("backButton", js)
        self.assertIn("pull", js.lower())
        self.assertIn("clone.hidden = false", js)
        self.assertIn("bb-title-dup", js)

    def test_website_markup_still_has_hamburger_and_top_nav(self):
        home = Client().get("/").text
        self.assertIn("details class=\"mmenu\"", home)
        self.assertIn("class=\"nav-links\"", home)
        # tabs are injected by JS only in app mode, not in the HTML source
        self.assertNotIn("class=\"bb-tabbar\"", home)
        self.assertNotIn("class=\"bb-appbar\"", home)

    def test_signed_in_boot_includes_dogs_not_email(self):
        c = Client()
        email = f"shell-{RUN}@example.com"
        sign_in(c, email)
        c.post("/me/profile", {"display_name": "Sam", "area": "Nassau", "town": "Manhasset", "bio": "Lily's person."})
        new_dog(c, name="Lily", breed="Cairn Terrier")
        me = c.get("/me").text
        self.assertIn("BB_DOGS", me)
        self.assertIn("Lily", me)
        boot = re.search(r"window.BB_DOGS=\[.*?\];", me)
        self.assertIsNotNone(boot)
        self.assertNotIn(email, boot.group(0))
        runs = c.get("/runs").text
        self.assertIn("BB_CSRF", runs)
        self.assertIn("BB_DOGS", runs)
        boot2 = re.search(r"window.BB_DOGS=\[.*?\];", runs)
        self.assertIsNotNone(boot2)
        self.assertNotIn(email, boot2.group(0))

    def test_tabs_point_at_real_pages(self):
        js = (PUBLIC / "app-shell.js").read_text()
        for path, allowed in (("/runs", (200,)), ("/meetups/calendar", (200,)),
                               ("/picks", (200,)), ("/me", (200, 303))):
            self.assertIn('"' + path + '"', js)
            self.assertIn(Client().get(path).status, allowed)

    def test_haptics_plugin_is_listed(self):
        pkg = (ROOT / "app" / "package.json").read_text()
        self.assertIn("@capacitor/haptics", pkg)
        cfg = (ROOT / "app" / "capacitor.config.js").read_text()
        self.assertIn("contentInset: \"never\"", cfg)
        self.assertIn('style: "DARK"', cfg)
