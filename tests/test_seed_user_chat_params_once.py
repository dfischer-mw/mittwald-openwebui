import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bootstrap" / "seed_user_chat_params_once.py"


spec = importlib.util.spec_from_file_location("seed_bootstrap", MODULE_PATH)
seed = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(seed)


def _create_users_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            role TEXT,
            settings TEXT,
            created_at TEXT
        )
        """
    )
    return conn


def test_find_users_table_detects_expected_schema(tmp_path):
    db_path = tmp_path / "webui.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, role TEXT, settings TEXT, created_at TEXT)"
    )

    assert seed.find_users_table(conn) == "users"

    conn.close()


def test_find_settings_column_returns_none_when_missing(tmp_path):
    db_path = tmp_path / "webui.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, role TEXT)")

    assert seed.find_settings_column(conn, "users") is None

    conn.close()


def test_update_user_settings_once_only_adds_missing_keys(tmp_path):
    db_path = tmp_path / "webui.db"
    conn = _create_users_db(db_path)

    existing = {"chat": {"params": {"temperature": 0.15}}}
    empty_settings = {}

    conn.execute(
        "INSERT INTO users (id, email, role, settings, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (1, "a@example.com", "admin", json.dumps(existing)),
    )
    conn.execute(
        "INSERT INTO users (id, email, role, settings, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (2, "b@example.com", "user", json.dumps(empty_settings)),
    )
    conn.commit()

    seed.DESIRED = {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
    }

    updated = seed.update_user_settings_once(conn, "users", "id", "settings")
    conn.commit()

    assert updated == 2

    row1 = conn.execute("SELECT settings FROM users WHERE id = 1").fetchone()[0]
    parsed1 = json.loads(row1)
    assert parsed1["chat"]["params"]["temperature"] == 0.15
    assert parsed1["chat"]["params"]["top_p"] == 0.9
    assert parsed1["chat"]["params"]["top_k"] == 40

    row2 = conn.execute("SELECT settings FROM users WHERE id = 2").fetchone()[0]
    parsed2 = json.loads(row2)
    assert parsed2["chat"]["params"]["temperature"] == 0.7
    assert parsed2["chat"]["params"]["top_p"] == 0.9
    assert parsed2["chat"]["params"]["top_k"] == 40

    conn.close()
