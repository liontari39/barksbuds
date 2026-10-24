"""Seed the first BarksBuds dog profiles (Lily and Maggie on Mike's account). Safe to run more than once.

Usage:  DATABASE_URL=... python3 seed.py [--assets /path/to/barksbuds-assets]
        (without DATABASE_URL it seeds the local SQLite database in DATA_DIR)

Idempotent: the account is matched by email, dogs by a fixed seed key, and photos are only added to a dog that has none,
so existing edits made through the site are never overwritten.
"""
import argparse
import os
from datetime import date

import accounts as A
import server

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "barksbuds-assets"))
    args = ap.parse_args()
    server.init_app()

    uid, created = A.get_or_create_user(OWNER["email"])
    u = A.one("SELECT display_name, area, town, bio FROM users WHERE id=:i", i=uid)
    A.update_profile(uid, u[0] or OWNER["display_name"], u[1] or OWNER["area"], u[2] or OWNER["town"], u[3] or OWNER["bio"])
    print(f"owner: user {uid} ({'created' if created else 'existing'})")

    for spec in DOGS:
        row = A.one("SELECT id FROM dogs WHERE seed_key=:k", k=spec["seed_key"])
        if row:
            dog_id = row[0]
            print(f"{spec['name']}: exists (dog {dog_id}), leaving profile as is")
        else:
            f = dict(name=spec["name"], breed=spec["breed"], birthday="", birth_year=date.today().year - spec["age"],
                     sex="", size=spec["size"], temperament=[], play_style=[], vaccinated=False, fav_runs=[], bio=spec["bio"])
            dog_id = A.save_dog(uid, f, seed_key=spec["seed_key"])
            print(f"{spec['name']}: created dog {dog_id}")
        if A.photo_count(dog_id) == 0:
            for fn in spec["photos"]:
                with open(os.path.join(args.assets, "dogs", fn), "rb") as fh:
                    pid = A.add_photo(dog_id, fh.read())
                print(f"  + photo {fn} -> {pid}")
        if not A.dog_by_id(dog_id).get("avatar_photo_id") and spec.get("sprite"):
            p = os.path.join(args.assets, "sprites", spec["sprite"])
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    pid = A.add_photo(dog_id, fh.read(), kind="avatar")
                A.set_avatar(dog_id, pid)
                print(f"  + avatar {spec['sprite']} -> {pid}")
        print(f"  page: /dogs/{A.dog_by_id(dog_id)['slug']}")


if __name__ == "__main__":
    main()
