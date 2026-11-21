"""Admin-only maintenance endpoints (X-Admin-Key header only; never a query-string key).

  GET  /admin/maint/stats      JSON: database size, connections, per-table rows/dead rows/size, hygiene counts
  GET  /admin/maint/backup     gzip NDJSON logical backup of every table (bytea as base64). Free-tier Render
                               Postgres has no backups/exports and no external access, so this is how to take one.
  POST /admin/maint/cleanup    removes expired sessions and login links that expired over a day ago.
                               Dry run unless dry_run=0. Never touches user content.

There is no HTTP restore endpoint. restore_backup() plus scripts/restore_backup.py load a
backup into a local SQLite (or a new empty Postgres) database. See the README.
"""
import base64, datetime as _dt, gzip, json, re, time

import accounts as A


def _tables():
    st = A.STORE
    if st.kind == "postgres":
        return [r[0] for r in st.q("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    return [r[0] for r in st.q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _count(sql, **kw):
    try:
        return int(A.STORE.q(sql, **kw)[0][0])
    except Exception as e:
        return f"n/a ({type(e).__name__})"


def hygiene():
    t = A.now()
    day = 86400
    return {
        "sessions_total": _count("SELECT COUNT(*) FROM sessions"),
        "sessions_expired": _count("SELECT COUNT(*) FROM sessions WHERE expires_at<:t", t=t),
        "login_tokens_total": _count("SELECT COUNT(*) FROM login_tokens"),
        "login_tokens_expired_over_1d": _count("SELECT COUNT(*) FROM login_tokens WHERE expires_at<:t", t=t - day),
        "rate_limit_rows": "none (rate limits are in memory, not in the database)",
        "orphan_dog_photos": _count("SELECT COUNT(*) FROM photos p WHERE NOT EXISTS (SELECT 1 FROM dogs d WHERE d.id=p.dog_id)"),
        "orphan_pack_photos": _count("SELECT COUNT(*) FROM pack_photos p WHERE NOT EXISTS (SELECT 1 FROM packs k WHERE k.id=p.pack_id)"),
        "orphan_portrait_request_photos": _count("SELECT COUNT(*) FROM portrait_request_photos x WHERE NOT EXISTS (SELECT 1 FROM portrait_requests r WHERE r.id=x.request_id)"),
        "portrait_requests_pending": _count("SELECT COUNT(*) FROM portrait_requests WHERE status='pending'"),
        "portrait_requests_pending_over_7d": _count("SELECT COUNT(*) FROM portrait_requests WHERE status='pending' AND created_at<:t", t=t - 7 * day),
    }


def stats():
    st = A.STORE
    out = {"store": st.kind, "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "hygiene": hygiene()}
    if st.kind == "postgres":
        out["db_bytes"] = int(st.q("SELECT pg_database_size(current_database())")[0][0])
        out["pg_version"] = st.q("SHOW server_version")[0][0]
        out["max_connections"] = int(st.q("SHOW max_connections")[0][0])
        out["connections"] = {str(s or "none"): int(n) for s, n in st.q(
            "SELECT state, COUNT(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY state")}
        out["oldest_idle_conn_s"] = _count("SELECT COALESCE(EXTRACT(EPOCH FROM max(now()-state_change)),0)::bigint FROM pg_stat_activity WHERE datname=current_database() AND state='idle'")
        out["tables"] = [dict(zip(("table", "live", "dead", "bytes", "seq_scan", "idx_scan", "last_autovacuum"),
                                  (r[0], int(r[1]), int(r[2]), int(r[3]), int(r[4] or 0), int(r[5] or 0), str(r[6] or ""))))
                         for r in st.q("""SELECT relname, n_live_tup, n_dead_tup, pg_total_relation_size(relid), seq_scan, idx_scan,
                                          last_autovacuum FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC""")]
        out["long_running_queries"] = [dict(state=r[0], seconds=int(r[1]), query=(r[2] or "")[:120]) for r in st.q(
            """SELECT state, EXTRACT(EPOCH FROM now()-query_start)::bigint, query FROM pg_stat_activity
               WHERE datname=current_database() AND state<>'idle' AND pid<>pg_backend_pid() AND now()-query_start > interval '5 seconds'""")]
    else:
        out["tables"] = [{"table": t, "live": _count(f'SELECT COUNT(*) FROM "{t}"')} for t in _tables()]
    return out


def cleanup(dry_run=True):
    t = A.now()
    before = hygiene()
    if not dry_run:
        A.STORE.q("DELETE FROM sessions WHERE expires_at<:t", t=t)
        A.STORE.q("DELETE FROM login_tokens WHERE expires_at<:t", t=t - 86400)
    return {"dry_run": dry_run, "before": before, "after": hygiene()}


def _enc(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def write_backup(fileobj, chunk=200):
    st = A.STORE
    z = gzip.GzipFile(fileobj=fileobj, mode="wb", compresslevel=6)
    def w(o):
        z.write((json.dumps(o, separators=(",", ":")) + "\n").encode())
    w({"backup": "barksbuds", "store": st.kind, "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")})
    for t in _tables():
        if st.kind == "postgres":
            cols = [r[0] for r in st.q("""SELECT column_name FROM information_schema.columns
                                          WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position""", t=t)]
        else:
            cols = [r[1] for r in st.q(f'PRAGMA table_info("{t}")')]
        w({"table": t, "columns": cols})
        n, off = 0, 0
        while True:
            rows = st.q(f'SELECT * FROM "{t}" ORDER BY 1 LIMIT {int(chunk)} OFFSET {int(off)}')
            for r in rows:
                w({"t": t, "r": [_enc(v) for v in r]})
            n += len(rows); off += chunk
            if len(rows) < chunk:
                break
        w({"table_end": t, "rows": n})
    w({"end": True})
    z.close()


def _ident(name):
    """Allow only simple SQL identifiers (backup table/column names)."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("invalid identifier in backup")
    return name


def _dec(v):
    if isinstance(v, dict):
        if "$b64" in v and len(v) == 1:
            return base64.b64decode(v["$b64"])
        return json.dumps(v)
    if isinstance(v, list):
        return json.dumps(v)
    return v


def _table_columns(store, table):
    t = _ident(table)
    if store.kind == "postgres":
        return [r[0] for r in store.q(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position""", t=t)]
    return [r[1] for r in store.q(f'PRAGMA table_info("{t}")')]


def _table_count(store, table):
    return int(store.q(f'SELECT COUNT(*) FROM "{_ident(table)}"')[0][0])


def _reset_sequences(store, tables):
    if store.kind == "postgres":
        for t in tables:
            cols = store.q(
                """SELECT a.attname FROM pg_class c
                     JOIN pg_namespace n ON n.oid=c.relnamespace
                     JOIN pg_attribute a ON a.attrelid=c.oid
                   WHERE n.nspname='public' AND c.relname=:t
                     AND a.attnum>0 AND NOT a.attisdropped
                     AND pg_get_serial_sequence(quote_ident(:t), a.attname) IS NOT NULL""", t=t)
            for (col,) in cols:
                c = _ident(col)
                seq = store.q("SELECT pg_get_serial_sequence(quote_ident(:t), :c)", t=t, c=c)
                if not seq or not seq[0][0]:
                    continue
                mx = int(store.q(f'SELECT COALESCE(MAX("{c}"), 0) FROM "{_ident(t)}"')[0][0])
                if mx < 1:
                    store.q("SELECT setval(:s, 1, false)", s=seq[0][0])
                else:
                    store.q("SELECT setval(:s, :n)", s=seq[0][0], n=mx)
        return
    try:
        store.q("DELETE FROM sqlite_sequence")
    except Exception:
        return
    for t in tables:
        info = store.q(f'PRAGMA table_info("{_ident(t)}")')
        pk = [r[1] for r in info if r[5]]
        if len(pk) != 1:
            continue
        col = _ident(pk[0])
        typ = (next(r[2] for r in info if r[1] == col) or "").upper()
        if "INT" not in typ:
            continue
        mx = int(store.q(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{_ident(t)}"')[0][0])
        store.q("INSERT INTO sqlite_sequence(name, seq) VALUES(:n, :s)", n=t, s=mx)


def restore_backup(fileobj, store=None, replace=False):
    """Load a gzip NDJSON backup (from write_backup) into store (default accounts.STORE).

    The destination schema must already exist (call server.init_app() first). By default
    this refuses if any target table already has rows, so a live database cannot be
    overwritten by accident. Pass replace=True only for a throwaway local store.
    Returns {"ok": True, "at": ..., "tables": {name: rows, ...}} and never prints row contents.
    """
    st = store or A.STORE
    recs = [json.loads(x) for x in gzip.GzipFile(fileobj=fileobj, mode="rb").read().splitlines() if x]
    if not recs or not recs[-1].get("end"):
        raise ValueError("backup is truncated (missing end record)")
    header = recs[0]
    if not isinstance(header, dict) or header.get("backup") != "barksbuds":
        raise ValueError("not a BarksBuds backup")

    tables_in, existing = [], []
    for rec in recs:
        if "table" in rec and "columns" in rec:
            t = _ident(rec["table"])
            tables_in.append(t)
            if not _table_columns(st, t):
                raise ValueError(f"backup table {t} is not in the destination schema")
            if _table_count(st, t):
                existing.append(t)
    if existing and not replace:
        raise RuntimeError(
            "destination already has rows in: " + ", ".join(existing)
            + " (pass replace=True only for a throwaway local store)")
    if replace:
        for t in reversed(tables_in):
            st.q(f'DELETE FROM "{_ident(t)}"')

    written, expected = {}, {}
    current, src_cols = None, None
    for rec in recs:
        if "table" in rec and "columns" in rec:
            current = _ident(rec["table"])
            src_cols = list(rec["columns"])
            written.setdefault(current, 0)
            continue
        if "t" in rec and "r" in rec:
            if current is None:
                raise ValueError("row record before table header")
            destset = set(_table_columns(st, current))
            cols, vals = [], {}
            for name, rawv in zip(src_cols, rec["r"]):
                name = _ident(name)
                if name not in destset:
                    continue
                cols.append(name)
                vals[name] = _dec(rawv)
            if not cols:
                continue
            placeholders = ", ".join(f":p{i}" for i in range(len(cols)))
            colnames = ", ".join(f'"{c}"' for c in cols)
            kw = {f"p{i}": vals[c] for i, c in enumerate(cols)}
            st.q(f'INSERT INTO "{current}" ({colnames}) VALUES ({placeholders})', **kw)
            written[current] = written.get(current, 0) + 1
            continue
        if "table_end" in rec:
            expected[_ident(rec["table_end"])] = int(rec["rows"])
    mismatches = {t: (expected[t], written.get(t, 0)) for t in expected if expected[t] != written.get(t, 0)}
    if mismatches:
        raise RuntimeError(
            "restore count mismatch (expected, wrote): "
            + ", ".join(f"{t}={pair}" for t, pair in mismatches.items()))
    _reset_sequences(st, list(written))
    return {
        "ok": True,
        "at": header.get("at"),
        "source_store": header.get("store"),
        "tables": {t: written.get(t, 0) for t in tables_in},
    }


class MaintRoutes:
    def _maint_ok(self):
        return self._admin_key_ok(self.headers.get("X-Admin-Key", ""))

    def _maint_json(self, obj):
        self._send(200, json.dumps(obj, default=str).encode(), "application/json", {"Cache-Control": "no-store"})

    def maint_get(self, path, q):
        if not path.startswith("/admin/maint/"):
            return False
        if not self._maint_ok():
            self.send_error(404); return True
        if path == "/admin/maint/stats":
            self._maint_json(stats()); return True
        if path == "/admin/maint/backup":
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", 'attachment; filename="barksbuds-backup-%s.ndjson.gz"' % time.strftime("%Y%m%d-%H%M%S"))
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            write_backup(self.wfile)
            return True
        self.send_error(404); return True

    def maint_post(self, path, q):
        if path != "/admin/maint/cleanup":
            return False
        if not self._maint_ok():
            self.send_error(404); return True
        self._maint_json(cleanup(dry_run=q.get("dry_run", ["1"])[0] != "0"))
        return True
