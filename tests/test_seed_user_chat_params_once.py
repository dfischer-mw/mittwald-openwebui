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

    updated = seed.update_user_settings_once(
        conn,
        "users",
        "id",
        "settings",
        desired=seed.DESIRED,
        force_overwrite=False,
    )
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


def test_update_user_settings_once_overwrites_existing_when_enabled(tmp_path):
    db_path = tmp_path / "webui.db"
    conn = _create_users_db(db_path)

    existing = {"chat": {"params": {"temperature": 0.7, "top_p": 0.9}}}

    conn.execute(
        "INSERT INTO users (id, email, role, settings, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (1, "a@example.com", "admin", json.dumps(existing)),
    )
    conn.commit()

    desired = {
        "temperature": 0.1,
        "top_p": 0.5,
        "top_k": 10,
    }

    updated = seed.update_user_settings_once(
        conn,
        "users",
        "id",
        "settings",
        desired=desired,
        force_overwrite=True,
    )
    conn.commit()

    assert updated == 1

    row = conn.execute("SELECT settings FROM users WHERE id = 1").fetchone()[0]
    parsed = json.loads(row)
    assert parsed["chat"]["params"]["temperature"] == 0.1
    assert parsed["chat"]["params"]["top_p"] == 0.5
    assert parsed["chat"]["params"]["top_k"] == 10

    conn.close()


def test_build_desired_defaults_uses_ministral_profile_from_discovery(tmp_path, monkeypatch):
    cache = tmp_path / "mittwald-models-discovery.json"
    cache.write_text(
        json.dumps(
            {
                "classification": {
                    "default_chat_model": "Ministral-3-14B-Instruct-2512",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(seed, "DISCOVERY_CACHE_PATH", cache)
    monkeypatch.setattr(
        seed,
        "ENV_DEFAULTS",
        {
            "temperature": None,
            "top_p": None,
            "top_k": None,
            "repetition_penalty": None,
            "max_tokens": None,
        },
    )

    desired = seed.build_desired_defaults()

    assert desired["temperature"] == 0.1
    assert desired["top_p"] == 0.5
    assert desired["top_k"] == 10


def test_find_hf_model_config_for_model_uses_normalized_model_key():
    payload = {
        "models": {
            "Ministral-3-14B-Instruct-2512": {
                "hyperparameters": {"temperature": 0.1},
                "generation_config": {"top_p": 0.5},
            }
        }
    }

    selected = seed.find_hf_model_config_for_model(
        payload, "ministral_3_14b_instruct_2512"
    )

    assert selected["hyperparameters"]["temperature"] == 0.1
    assert selected["generation_config"]["top_p"] == 0.5


def test_build_desired_defaults_applies_hf_generation_then_hyperparams(
    tmp_path, monkeypatch
):
    cache = tmp_path / "mittwald-models-discovery.json"
    cache.write_text(
        json.dumps(
            {
                "classification": {
                    "default_chat_model": "Ministral-3-14B-Instruct-2512",
                }
            }
        ),
        encoding="utf-8",
    )

    hf_payload = tmp_path / "hf-model-hyperparameters.json"
    hf_payload.write_text(
        json.dumps(
            {
                "models": {
                    "Ministral-3-14B-Instruct-2512": {
                        "generation_config": {
                            "temperature": 0.25,
                            "topk": 30,
                            "max_new_tokens": 2048,
                        },
                        "hyperparameters": {
                            "temperature": 0.1,
                            "top_p": 0.5,
                            "top_k": 10,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(seed, "DISCOVERY_CACHE_PATH", cache)
    monkeypatch.setattr(seed, "HF_MODEL_HYPERPARAMS_PATH", hf_payload)
    monkeypatch.setattr(
        seed,
        "ENV_DEFAULTS",
        {
            "temperature": None,
            "top_p": None,
            "top_k": None,
            "repetition_penalty": None,
            "max_tokens": None,
        },
    )

    desired = seed.build_desired_defaults()

    # Generation config should apply first...
    assert desired["max_tokens"] == 2048
    # ...then HF hyperparameters should win on conflicts.
    assert desired["temperature"] == 0.1
    assert desired["top_p"] == 0.5
    assert desired["top_k"] == 10
