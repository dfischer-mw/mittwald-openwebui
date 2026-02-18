#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from typing import Optional, List, Dict

DB_PATH = os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db")
MARKER = os.getenv(
    "OWUI_BOOTSTRAP_MARKER", "/app/backend/data/.bootstrapped_chat_params"
)

# Env-controlled "desired defaults"
DEFAULTS = {
    "temperature": os.getenv("OWUI_BOOTSTRAP_TEMPERATURE"),
    "top_p": os.getenv("OWUI_BOOTSTRAP_TOP_P"),
    "top_k": os.getenv("OWUI_BOOTSTRAP_TOP_K"),
    "repetition_penalty": os.getenv("OWUI_BOOTSTRAP_REPETITION_PENALTY"),
    "max_tokens": os.getenv("OWUI_BOOTSTRAP_MAX_TOKENS"),
}


def _coerce(v: Optional[str]):
    if v is None or v == "":
        return None
    # int if it looks like int, else float if it looks like float, else string
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


DESIRED: Dict[str, object] = {
    k: _coerce(v) for k, v in DEFAULTS.items() if _coerce(v) is not None
}


def log(msg: str):
    print(f"[bootstrap-chat-params] {msg}", flush=True)


def wait_for_db(path: str, timeout_s: int = 600):
    start = time.time()
    while time.time() - start < timeout_s:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return
        time.sleep(1)
    raise TimeoutError(f"DB not found after {timeout_s}s: {path}")


def list_tables(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]


def find_users_table(conn: sqlite3.Connection) -> Optional[str]:
    tables = list_tables(conn)
    # best-effort heuristics: table containing email+role is typically the user table
    candidates = []
    for t in tables:
        cols = set(table_columns(conn, t))
        if "email" in cols and ("role" in cols or "is_admin" in cols):
            score = 0
            for c in ("name", "username", "created_at", "updated_at", "settings"):
                if c in cols:
                    score += 1
            candidates.append((score, t))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    # fallback by name
    for t in tables:
        if t.lower() in ("user", "users", "account", "accounts"):
            return t
    return None


def find_settings_column(conn: sqlite3.Connection, table: str) -> Optional[str]:
    cols = table_columns(conn, table)
    for c in ("settings", "preferences", "config", "data", "meta", "info"):
        if c in cols:
            return c
    return None


def find_id_column(conn: sqlite3.Connection, table: str) -> str:
    cols = table_columns(conn, table)
    for c in ("id", "user_id", "uuid"):
        if c in cols:
            return c
    return cols[0]  # last resort


def user_count(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM '{table}'")
    return int(cur.fetchone()[0])


def ensure_nested(d: dict, *path: str) -> dict:
    cur = d
    for p in path:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    return cur


def update_user_settings_once(
    conn: sqlite3.Connection, table: str, id_col: str, settings_col: str
) -> int:
    """
    Applies DESIRED keys only if missing under settings['chat']['params'].
    Returns number of updated rows.
    """
    updated = 0
    cur = conn.execute(f"SELECT {id_col}, {settings_col} FROM '{table}'")
    rows = cur.fetchall()

    for user_id, settings_raw in rows:
        base = {}
        if settings_raw:
            try:
                base = json.loads(settings_raw)
                if not isinstance(base, dict):
                    base = {}
            except Exception:
                base = {}

        params = ensure_nested(base, "chat", "params")

        changed = False
        for k, v in DESIRED.items():
            if k not in params:
                params[k] = v
                changed = True

        if changed:
            conn.execute(
                f"UPDATE '{table}' SET {settings_col} = ? WHERE {id_col} = ?",
                (json.dumps(base, ensure_ascii=False), user_id),
            )
            updated += 1

    return updated


def main():
    if not DESIRED:
        log("No OWUI_BOOTSTRAP_* env vars set; nothing to do.")
        return

    if os.path.exists(MARKER):
        log("Marker exists; bootstrap already done.")
        return

    log(f"Waiting for DB: {DB_PATH}")
    wait_for_db(DB_PATH)

    # keep retrying in case the app is migrating/locking sqlite
    for attempt in range(1, 301):  # ~10 minutes (2s sleep)
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("PRAGMA busy_timeout=30000;")

            users_table = find_users_table(conn)
            if not users_table:
                log("Could not find users table yet; retrying...")
                if conn:
                    conn.close()
                time.sleep(2)
                continue

            # Wait until the customer actually signs up
            if user_count(conn, users_table) < 1:
                if conn:
                    conn.close()
                time.sleep(2)
                continue

            settings_col = find_settings_column(conn, users_table)
            if not settings_col:
                log(
                    f"Found users table '{users_table}' but no obvious settings column; aborting (no changes)."
                )
                if conn:
                    conn.close()
                return

            id_col = find_id_column(conn, users_table)

            conn.execute("BEGIN;")
            n = update_user_settings_once(conn, users_table, id_col, settings_col)
            conn.execute("COMMIT;")
            conn.close()

            # write marker into the persistent volume so it only ever runs once
            with open(MARKER, "w", encoding="utf-8") as f:
                f.write(f"done {int(time.time())}\n")

            log(f"Injected defaults into {n} user(s). Done.")
            return

        except sqlite3.OperationalError as e:
            # most common: database is locked during migrations/startup
            log(f"SQLite operational error (attempt {attempt}): {e}; retrying...")
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            time.sleep(2)

    log("Gave up waiting for a writable DB/users; no changes applied.")


if __name__ == "__main__":
    main()
