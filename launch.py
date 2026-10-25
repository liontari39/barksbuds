#!/usr/bin/env python3
"""BarksBuds launch-day script. Run it ONLY on the launch day Mike picks.

    python3 launch.py            # dry run: shows what would happen, changes nothing
    python3 launch.py --yes      # deletes the sample pack(s) and sample meetup(s) on the live site

What --yes does:
  1. POST /admin/packs   action=delete_all_samples  (deletes every is_sample pack AND every is_sample meetup)
  2. POST /admin/meetups action=delete_samples      (belt and braces: any sample meetup left over)
  3. Checks /packs and /meetups no longer show a "Sample" badge.
  4. Prints the Render env change to make by hand (it does not touch Render itself).
The admin key is read from $ADMIN_KEY or ./.admin_key and sent only in the X-Admin-Key header; it is never printed.
Set BASE=http://localhost:8080 to rehearse against a local server.
"""
import os, sys, urllib.error, urllib.request

BASE = os.environ.get("BASE", "https://barksbuds.app").rstrip("/")
SERVICE = "srv-dbed49jncjis73dsb390"
OWNER_EMAIL = "mike.karachalios@gmail.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def admin_key():
    k = os.environ.get("ADMIN_KEY", "").strip()
    if not k:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".admin_key")
        if os.path.exists(p):
            k = open(p).read().strip()
    if not k:
        sys.exit("No admin key: set ADMIN_KEY or create .admin_key next to this script.")
    return k


def post(path, action, key):
    req = urllib.request.Request(BASE + path, data=f"action={action}".encode(), method="POST",
                                 headers={"X-Admin-Key": key, "Content-Type": "application/x-www-form-urlencoded",
                                          "User-Agent": "barksbuds-launch"})
    try:
        r = urllib.request.build_opener(NoRedirect).open(req, timeout=60)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code   # 303 (redirect back to the admin page) means it worked


def sample_badges(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "barksbuds-launch"})
    body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    return body.count('badge sample">Sample') + body.count('ns-badge">Sample')


def env_instructions():
    print(f"""
==> Last step, by hand in the Render dashboard (service {SERVICE}, "barksbuds" > Environment):
    1. ADD    RUN_SUGGEST_EMAIL = {OWNER_EMAIL}
              (keeps the "new dog run / tip suggestion" emails coming to Mike; today they ride on the allowlist)
    2. REMOVE MEETUP_EMAIL_ALLOWLIST
              (this is the only env var to delete; it currently limits meetup, pack and suggestion emails to Mike)
    3. Save changes. Render redeploys; after that, meetup and pack emails go to every member.
    Do not remove anything else.""")


def main():
    go = "--yes" in sys.argv[1:]
    print(f"BarksBuds launch script for {BASE}  ({'LIVE RUN' if go else 'dry run, nothing will change'})")
    print("Plan:\n  - delete all sample packs and sample meetups via /admin/packs and /admin/meetups\n"
          "  - verify /packs and /meetups show no Sample badges\n  - print the Render env var change")
    key = admin_key()
    try:
        print(f"Sample badges right now: /packs={sample_badges('/packs')} /meetups={sample_badges('/meetups')}")
    except Exception as ex:
        print("Could not read the public pages:", type(ex).__name__)
    if not go:
        env_instructions()
        print("\nDry run only. Re-run with --yes on launch day.")
        return
    for path, action in (("/admin/packs", "delete_all_samples"), ("/admin/meetups", "delete_samples")):
        st = post(path, action, key)
        ok = st in (200, 303)
        print(f"  {path} {action}: HTTP {st} {'ok' if ok else 'FAILED'}")
        if not ok:
            sys.exit("Stopped: an admin call failed (check the admin key and that the site is up).")
    left = (sample_badges("/packs"), sample_badges("/meetups"))
    print(f"Sample badges after: /packs={left[0]} /meetups={left[1]}" + ("  (all gone)" if left == (0, 0) else "  (some still showing!)"))
    env_instructions()


if __name__ == "__main__":
    main()
