#!/usr/bin/env python3
"""Restore a BarksBuds gzip NDJSON backup into a local database (see maintweb.restore_backup).

Usage:
  python3 scripts/restore_backup.py [--data-dir DIR] [--replace] BACKUP.ndjson.gz

The destination schema is created first (server.init_app). By default the script
writes to a SQLite file at $DATA_DIR/waitlist.db (or --data-dir) and refuses to
run if any table already has rows. Pass --replace only for a throwaway store.

DATABASE_URL in the environment is ignored unless you pass --database-url, so a
production URL cannot be used by accident. Prints per-table counts only; never
prints row contents. Keep restored member data off git (chmod 600).

Example (production backup into a throwaway local SQLite store):

    python3 scripts/restore_backup.py --data-dir /tmp/bb-restore-YYYYMMDD \\
        backups/barksbuds-backup-YYYY-MM-DD.ndjson.gz
"""
import argparse, json, os, stat, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("backup", help="path to a barksbuds-backup-*.ndjson.gz file")
    p.add_argument("--data-dir", default=None,
                   help="SQLite DATA_DIR (default: $DATA_DIR). Unsets DATABASE_URL.")
    p.add_argument("--database-url", default=None,
                   help="Postgres URL for an empty (or --replace) database; do not use the live one.")
    p.add_argument("--replace", action="store_true",
                   help="delete existing rows in tables present in the backup (throwaway stores only)")
    args = p.parse_args()

    backup = os.path.abspath(args.backup)
    if not os.path.isfile(backup):
        sys.exit(f"backup not found: {backup}")

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    else:
        os.environ.pop("DATABASE_URL", None)
        data_dir = args.data_dir or os.environ.get("DATA_DIR")
        if not data_dir:
            sys.exit("pass --data-dir (or set DATA_DIR) for a local SQLite restore, or --database-url for Postgres")
        os.makedirs(data_dir, exist_ok=True)
        os.chmod(data_dir, stat.S_IRWXU)
        os.environ["DATA_DIR"] = data_dir
    os.environ.setdefault("EMAIL_PROVIDER", "file")
    os.environ.setdefault("ADMIN_KEY", "restore-local")

    sys.path.insert(0, REPO)
    os.chdir(REPO)
    import server
    server.init_app()
    import accounts as A
    import maintweb

    with open(backup, "rb") as fh:
        result = maintweb.restore_backup(fh, store=A.STORE, replace=args.replace)

    if A.STORE.kind == "sqlite":
        db = os.path.join(os.environ["DATA_DIR"], "waitlist.db")
        try:
            os.chmod(db, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        result["sqlite"] = db
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
