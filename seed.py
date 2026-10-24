"""Seed the first BarksBuds dog profiles (Lily and Maggie on Mike's account). Safe to run more than once.

Usage:  DATABASE_URL=... python3 seed.py [--assets /path/to/barksbuds-assets]
        (without DATABASE_URL it seeds the local SQLite database in DATA_DIR)
   or:  python3 seed.py --url https://barksbuds.app [--assets ...]
        uploads the photos to the site's admin-only /admin/seed endpoint (key from $ADMIN_KEY or ./.admin_key),
        for when the database isn't reachable directly.

Idempotent: the account is matched by email, dogs by a fixed seed key, and photos are only added to a dog that has none,
so existing edits made through the site are never overwritten.
"""
import argparse
import json
import os
import urllib.request
import uuid
from datetime import date

import accounts as A

OWNER = dict(email="mike.karachalios@gmail.com", display_name="Mike", area="Nassau", town="Manhasset", bio="")

DOGS = [
    dict(seed_key="mike-lily", name="Lily", breed="Standard Poodle mix", age=6, size="large",
         bio="Say hi to Lily! She's a standard poodle mix with a curly black-and-grey coat. "
             "Look for the red heart tag on her collar.",
         photos=["lily-1.jpg", "lily-2.jpg", "lily-3.jpg"], sprite="lily-sprite.jpg"),
    dict(seed_key="mike-maggie", name="Maggie", breed="French Bulldog", age=3, size="small",
         bio="Meet Maggie, a merle French Bulldog. Come say hello!",
         photos=["maggie-1.jpg", "maggie-2.jpg"], sprite="maggie-sprite.jpg"),
]


def asset_names():
    out = []
    for spec in DOGS:
        out += [f"dogs/{fn}" for fn in spec["photos"]] + [f"sprites/{spec['sprite']}"]
    return out


def run(load, log=print):
    """Seed using load(relative_path) -> bytes or None. Returns the user id."""
    uid, created = A.get_or_create_user(OWNER["email"])
    u = A.one("SELECT display_name, area, town, bio FROM users WHERE id=:i", i=uid)
    A.update_profile(uid, u[0] or OWNER["display_name"], u[1] or OWNER["area"], u[2] or OWNER["town"], u[3] or OWNER["bio"])
    log(f"owner: user {uid} ({'created' if created else 'existing'})")
    for spec in DOGS:
        row = A.one("SELECT id FROM dogs WHERE seed_key=:k", k=spec["seed_key"])
        if row:
            dog_id = row[0]
            log(f"{spec['name']}: exists (dog {dog_id}), leaving profile as is")
        else:
            f = dict(name=spec["name"], breed=spec["breed"], birthday="", birth_year=date.today().year - spec["age"],
                     sex="", size=spec["size"], temperament=[], play_style=[], vaccinated=False, fav_runs=[], bio=spec["bio"])
            dog_id = A.save_dog(uid, f, seed_key=spec["seed_key"])
            log(f"{spec['name']}: created dog {dog_id}")
        if A.photo_count(dog_id) == 0:
            for fn in spec["photos"]:
                raw = load(f"dogs/{fn}")
                if raw:
                    log(f"  + photo {fn} -> {A.add_photo(dog_id, raw)}")
                else:
                    log(f"  ! missing {fn}")
        if not A.dog_by_id(dog_id).get("avatar_photo_id") and spec.get("sprite"):
            raw = load(f"sprites/{spec['sprite']}")
            if raw:
                pid = A.add_photo(dog_id, raw, kind="avatar")
                A.set_avatar(dog_id, pid)
                log(f"  + avatar {spec['sprite']} -> {pid}")
        log(f"  page: /dogs/{A.dog_by_id(dog_id)['slug']}")
    return uid


def upload(url, assets):
    key = os.environ.get("ADMIN_KEY") or open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".admin_key")).read().strip()
    bnd = "----bbseed" + uuid.uuid4().hex
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="key"\r\n\r\n{key}\r\n'.encode()]
    for rel in asset_names():
        with open(os.path.join(assets, rel), "rb") as fh:
            data = fh.read()
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="{rel}"\r\n'
                     f'Content-Type: image/jpeg\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    req = urllib.request.Request(url.rstrip("/") + "/admin/seed", data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}", "User-Agent": "barksbuds-seed"})
    with urllib.request.urlopen(req, timeout=180) as r:
        print(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "barksbuds-assets"))
    ap.add_argument("--url", help="seed a running site through its admin-only /admin/seed endpoint")
    args = ap.parse_args()
    if args.url:
        return upload(args.url, args.assets)
    import server
    server.init_app()

    def load(rel):
        p = os.path.join(args.assets, rel)
        return open(p, "rb").read() if os.path.exists(p) else None
    run(load)


if __name__ == "__main__":
    main()
