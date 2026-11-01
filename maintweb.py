"""Admin-only maintenance endpoints (X-Admin-Key header only; never a query-string key).

  GET  /admin/maint/stats      JSON: database size, connections, per-table rows/dead rows/size, hygiene counts
  GET  /admin/maint/backup     gzip NDJSON logical backup of every table (bytea as base64). Free-tier Render
                               Postgres has no backups/exports and no external access, so this is how to take one.
  POST /admin/maint/cleanup    removes expired sessions and login links that expired over a day ago.
                               Dry run unless dry_run=0. Never touches user content.
"""
import base64, datetime as _dt, gzip, json, time

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
