"""Capacitor wrap, native push devices, well-known App Links, privacy, CORS.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import json, os, re, sys, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402
import nativeapp  # noqa: E402
import push  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


ROOT = Path(__file__).resolve().parents[1]


class CapacitorProject(unittest.TestCase):
    def test_config_app_id_and_live_server_url(self):
        cfg = (ROOT / "app" / "capacitor.config.js").read_text()
        self.assertIn('appId: "app.barksbuds"', cfg)
        self.assertIn('appName: "BarksBuds"', cfg)
        self.assertIn("https://barksbuds.app", cfg)
        self.assertIn("BARKSBUDS_SERVER_URL", cfg)
        self.assertIn("BarksBudsApp/1.0", cfg)
        self.assertIn("@capacitor/camera", (ROOT / "app" / "package.json").read_text()
                      + (ROOT / "app" / "package-lock.json").read_text()
                      if (ROOT / "app" / "package-lock.json").exists()
                      else (ROOT / "app" / "package.json").read_text())
        # package.json may not list deps until npm install; config/docs still must exist
        self.assertTrue((ROOT / "app" / "www" / "index.html").is_file())
        self.assertTrue((ROOT / "app" / "resources" / "icon.png").is_file()
                        or (ROOT / "public" / "img" / "icon-512.png").is_file())
        self.assertTrue((ROOT / "codemagic.yaml").is_file())
        cm = (ROOT / "codemagic.yaml").read_text()
        self.assertIn("app.barksbuds", cm)
        self.assertIn("assembleDebug", cm)
        self.assertTrue((ROOT / "docs" / "app-store" / "mike-checklist.md").is_file())

    def test_website_js_feature_detects_and_is_cache_tagged(self):
        native = (ROOT / "public" / "native.js").read_text()
        self.assertIn("window.Capacitor", native)
        self.assertIn("bbLocate", native)
        self.assertIn("getPhoto", native)
        self.assertIn("/me/push/device", native)
        self.assertIn("sort dog runs near you", native)
        self.assertIn("save it", native)
        self.assertIn("bbLocate", (ROOT / "public" / "runs.js").read_text())
        self.assertIn("bbLocate", (ROOT / "public" / "suggest.js").read_text())
        home = Client().get("/").text
        self.assertIn("/native.js?v=1", home)
        self.assertEqual(Client().get("/native.js?v=1").status, 200)
        self.assertIn("/runs.js?v=8", Client().get("/runs").text)



    def test_native_projects_have_permissions_and_deep_links(self):
        manifest = (ROOT / "app" / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text()
        self.assertIn("android.permission.ACCESS_FINE_LOCATION", manifest)
        self.assertIn("android.permission.CAMERA", manifest)
        self.assertIn("android.permission.POST_NOTIFICATIONS", manifest)
        self.assertIn('android:host="barksbuds.app"', manifest)
        self.assertIn('android:scheme="barksbuds"', manifest)
        info = (ROOT / "app" / "ios" / "App" / "App" / "Info.plist").read_text()
        self.assertIn("NSCameraUsageDescription", info)
        self.assertIn("NSLocationWhenInUseUsageDescription", info)
        self.assertIn("barksbuds", info)
        ent = (ROOT / "app" / "ios" / "App" / "App" / "App.entitlements").read_text()
        self.assertIn("applinks:barksbuds.app", ent)
        self.assertIn("aps-environment", ent)

class PrivacyAndWellKnown(unittest.TestCase):
    def test_privacy_page_covers_the_app(self):
        r = Client().get("/privacy")
        self.assertEqual(r.status, 200)
        self.assertIn("November 23, 2026", r.text)
        self.assertIn("The BarksBuds app", r.text)
        self.assertIn("Location", r.text)
        self.assertIn("don't save it", r.text.lower().replace("we don&#x27;t", "don't").replace("we don't", "don't"))
        self.assertIn("Camera", r.text)
        self.assertIn("Notifications", r.text)
        self.assertIn("device token", r.text)

    def test_well_known_files_are_404_until_configured(self):
        old = {k: os.environ.get(k) for k in ("IOS_TEAM_ID", "IOS_BUNDLE_ID", "ANDROID_CERT_SHA256", "ANDROID_PACKAGE")}
        try:
            for k in list(old):
                os.environ.pop(k, None)
            self.assertEqual(Client().get("/.well-known/apple-app-site-association").status, 404)
            self.assertEqual(Client().get("/.well-known/assetlinks.json").status, 404)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_well_known_files_render_when_env_is_set(self):
        old = {k: os.environ.get(k) for k in ("IOS_TEAM_ID", "IOS_BUNDLE_ID", "ANDROID_CERT_SHA256", "ANDROID_PACKAGE")}
        try:
            os.environ["IOS_TEAM_ID"] = "AB12CD34EF"
            os.environ["IOS_BUNDLE_ID"] = "app.barksbuds"
            os.environ["ANDROID_PACKAGE"] = "app.barksbuds"
            os.environ["ANDROID_CERT_SHA256"] = "A" * 64
            aasa = Client().get("/.well-known/apple-app-site-association")
            self.assertEqual(aasa.status, 200)
            self.assertIn("application/json", aasa.headers.get("Content-Type", ""))
            body = json.loads(aasa.text)
            self.assertEqual(body["applinks"]["details"][0]["appID"], "AB12CD34EF.app.barksbuds")
            self.assertIn("/auth", body["applinks"]["details"][0]["paths"])
            links = Client().get("/.well-known/assetlinks.json")
            self.assertEqual(links.status, 200)
            arr = json.loads(links.text)
            self.assertEqual(arr[0]["target"]["package_name"], "app.barksbuds")
            self.assertEqual(arr[0]["target"]["sha256_cert_fingerprints"][0], ":".join(["AA"] * 32))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class CorsAndCookies(unittest.TestCase):
    def test_options_and_cors_for_capacitor_origin(self):
        r = Client().req("OPTIONS", "/me/push/device", headers={"Origin": "capacitor://localhost"})
        self.assertEqual(r.status, 204)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "capacitor://localhost")
        self.assertEqual(r.headers.get("Access-Control-Allow-Credentials"), "true")
        self.assertIn("POST", r.headers.get("Access-Control-Allow-Methods", ""))
        denied = Client().req("OPTIONS", "/me/push/device", headers={"Origin": "https://evil.example"})
        self.assertEqual(denied.status, 404)

    def test_csrf_allows_capacitor_origin_and_rejects_foreign(self):
        c = Client()
        sign_in(c, f"native-cors-{RUN}@example.com")
        token = re.search(r"window.BB_CSRF=\"([0-9a-f]+)\"", c.get("/me").text).group(1)
        body = json.dumps({"csrf": token, "platform": "android", "token": "fcm-token-abcdefghijklmnopqrstuvwxyz",
                           "kinds": ["meetups"]})
        ok = c.req("POST", "/me/push/device", body, {
            "Content-Type": "application/json",
            "Origin": "capacitor://localhost",
        })
        self.assertEqual(ok.status, 200, ok.text)
        self.assertEqual(ok.headers.get("Access-Control-Allow-Origin"), "capacitor://localhost")
        bad = c.req("POST", "/me/push/device", body, {
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
        })
        self.assertEqual(bad.status, 403)

    def test_samesite_none_only_when_configured(self):
        c = Client()
        r = c.get("/signin")
        jar = " ".join(r.set_cookies)
        self.assertIn("SameSite=Lax", jar)
        old = os.environ.get("APP_COOKIE_SAMESITE")
        try:
            os.environ["APP_COOKIE_SAMESITE"] = "none"
            r2 = Client().get("/signin")
            jar2 = " ".join(r2.set_cookies)
            self.assertIn("SameSite=None", jar2)
            self.assertIn("Secure", jar2)
        finally:
            if old is None:
                os.environ.pop("APP_COOKIE_SAMESITE", None)
            else:
                os.environ["APP_COOKIE_SAMESITE"] = old


class NativePushDevices(unittest.TestCase):
    def test_device_register_requires_login_and_valid_token(self):
        anon = Client().req("POST", "/me/push/device", "{}", {"Content-Type": "application/json"})
        self.assertEqual(anon.status, 401)
        c = Client()
        sign_in(c, f"native-push-{RUN}@example.com")
        me = c.get("/me").text
        token = re.search(r"window.BB_CSRF=\"([0-9a-f]+)\"", me).group(1)
        # Push prefs stay hidden on the website when VAPID is off, even for a
        # signed-in member, unless the request looks like the app.
        self.assertNotIn("Turn on notifications", me)
        appish = c.req("GET", "/me", headers={"User-Agent": "Mozilla/5.0 BarksBudsApp/1.0"})
        self.assertIn("Turn on notifications", appish.text)
        bad = c.req("POST", "/me/push/device",
                    json.dumps({"csrf": token, "platform": "android", "token": "short"}),
                    {"Content-Type": "application/json"})
        self.assertEqual(bad.status, 400)
        ok = c.req("POST", "/me/push/device",
                   json.dumps({"csrf": token, "platform": "ios",
                               "token": "apns-token-abcdefghijklmnopqrstuvwxyz0123",
                               "kinds": ["meetups", "checkins"]}),
                   {"Content-Type": "application/json"})
        self.assertEqual(ok.status, 200, ok.text)
        uid = T.A.one("SELECT id FROM users WHERE email=:e", e=f"native-push-{RUN}@example.com")[0]
        flags = push.user_flags(uid)
        self.assertTrue(flags["meetups"] and flags["checkins"])
        # Sending is a no-op until APNs/FCM env is set; it must not raise.
        self.assertFalse(push.native_configured())
        self.assertEqual(push.notify(uid, "meetups", "Meetup tomorrow", "Lily's walk", "/meetups"), 0)
        off = c.req("POST", "/me/push/device",
                    json.dumps({"csrf": token, "action": "off"}),
                    {"Content-Type": "application/json"})
        self.assertEqual(off.status, 200)
        flags = push.user_flags(uid)
        self.assertFalse(flags["meetups"] or flags["checkins"])

    def test_native_send_paths_exist_but_stay_off_without_keys(self):
        self.assertFalse(push.apns_configured())
        self.assertFalse(push.fcm_configured())
        # A clearly fake env must still not leak into responses.
        old = {k: os.environ.get(k) for k in ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_KEY_P8")}
        try:
            os.environ["APNS_KEY_ID"] = "TESTKEY1"
            os.environ["APNS_TEAM_ID"] = "TEAMTEST1"
            os.environ["APNS_KEY_P8"] = "not-a-real-key"
            self.assertTrue(push.apns_configured())
            self.assertNotIn("not-a-real-key", Client().get("/privacy").text)
            self.assertNotIn("TESTKEY1", Client().get("/.well-known/apple-app-site-association").text
                             if Client().get("/.well-known/apple-app-site-association").status == 200 else "")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            self.assertFalse(push.apns_configured())
