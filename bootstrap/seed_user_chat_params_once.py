#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional, List, Dict

DB_PATH = os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db")
MARKER = os.getenv(
    "OWUI_BOOTSTRAP_MARKER", "/app/backend/data/.bootstrapped_chat_params"
)
DISCOVERY_CACHE_PATH = Path(
    os.getenv(
        "MITTWALD_DISCOVERY_CACHE_PATH",
        "/app/backend/data/mittwald-models-discovery.json",
    )
)
HF_MODEL_HYPERPARAMS_PATH = Path(
    os.getenv(
        "HF_MODEL_HYPERPARAMS_PATH",
        "/usr/local/share/openwebui/hf-model-hyperparameters.json",
    )
)

# One-time bootstrap should overwrite factory defaults on first run so custom values
# really take effect. It still only runs once due to the marker file.
FORCE_OVERWRITE = os.getenv("OWUI_BOOTSTRAP_FORCE", "true").strip().lower() == "true"
POLL_INTERVAL_SEC = int(os.getenv("OWUI_BOOTSTRAP_POLL_INTERVAL_SEC", "2"))
MAX_WAIT_SECONDS = int(os.getenv("OWUI_BOOTSTRAP_MAX_WAIT_SECONDS", "86400"))

# Optional model-aware defaults. Env vars still win when set explicitly.
MODEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "ministral": {
        "temperature": 0.1,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    },
    "devstral": {
        "temperature": 0.15,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    },
    "qwen": {
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    },
    "gpt-oss": {
        "temperature": 0.2,
        "top_p": 0.7,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    },
}

FALLBACK_PROFILE: Dict[str, Any] = {
    "temperature": 0.2,
    "top_p": 0.8,
    "top_k": 20,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}

ENV_DEFAULTS = {
    "temperature": os.getenv("OWUI_BOOTSTRAP_TEMPERATURE"),
    "top_p": os.getenv("OWUI_BOOTSTRAP_TOP_P"),
    "top_k": os.getenv("OWUI_BOOTSTRAP_TOP_K"),
    "repetition_penalty": os.getenv("OWUI_BOOTSTRAP_REPETITION_PENALTY"),
    "max_tokens": os.getenv("OWUI_BOOTSTRAP_MAX_TOKENS"),
}

ALLOWED_CHAT_PARAM_KEYS = {
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
    "repeat_penalty",
    "presence_penalty",
    "frequency_penalty",
    "max_tokens",
    "seed",
    "mirostat",
    "mirostat_eta",
    "mirostat_tau",
    "repeat_last_n",
    "tfs_z",
    "num_ctx",
    "num_batch",
    "num_thread",
    "num_gpu",
}

CANONICAL_CHAT_PARAM_KEYS = {
    "repeat_penalty": "repetition_penalty",
    "max_new_tokens": "max_tokens",
    "num_predict": "max_tokens",
    "max_completion_tokens": "max_tokens",
    "topp": "top_p",
    "topk": "top_k",
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


def log(msg: str):
    print(f"[bootstrap-chat-params] {msg}", flush=True)


def normalize_model_name(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def load_default_chat_model(discovery_cache_path: Path) -> Optional[str]:
    try:
        if not discovery_cache_path.exists():
            return None
        payload = json.loads(discovery_cache_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        classification = payload.get("classification", {})
        if isinstance(classification, dict):
            model = classification.get("default_chat_model")
            if isinstance(model, str) and model.strip():
                return model.strip()
    except Exception:
        return None
    return None


def pick_profile_key(model_name: Optional[str]) -> Optional[str]:
    if not model_name:
        return None
    lowered = model_name.lower()
    for key in MODEL_PROFILES:
        if key in lowered:
            return key
    return None


def load_hf_model_hyperparams(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def find_hf_model_config_for_model(
    hf_payload: Dict[str, Any], model_name: Optional[str]
) -> Dict[str, Any]:
    if not model_name or not isinstance(hf_payload, dict):
        return {}

    models = hf_payload.get("models", {})
    if not isinstance(models, dict):
        return {}

    # Direct key match first.
    item = models.get(model_name)
    if isinstance(item, dict):
        return item

    # Fallback to normalized lookup.
    wanted = normalize_model_name(model_name)
    for key, value in models.items():
        if normalize_model_name(str(key)) != wanted:
            continue
        if isinstance(value, dict):
            return value

    return {}


def extract_chat_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        canonical_key = CANONICAL_CHAT_PARAM_KEYS.get(key, key)
        if canonical_key not in ALLOWED_CHAT_PARAM_KEYS:
            continue
        if isinstance(value, (int, float)):
            out[canonical_key] = value
    return out


def build_desired_defaults() -> Dict[str, object]:
    # Start with model-specific profile (if available), otherwise fallback.
    discovered_model = load_default_chat_model(DISCOVERY_CACHE_PATH)
    profile_key = pick_profile_key(discovered_model)
    desired: Dict[str, Any] = (
        MODEL_PROFILES.get(profile_key, FALLBACK_PROFILE).copy()
        if profile_key
        else FALLBACK_PROFILE.copy()
    )

    hf_payload = load_hf_model_hyperparams(HF_MODEL_HYPERPARAMS_PATH)
    hf_model_config = find_hf_model_config_for_model(hf_payload, discovered_model)
    hf_generation_params = extract_chat_params(
        hf_model_config.get("generation_config", {})
        if isinstance(hf_model_config, dict)
        else {}
    )
    hf_hyperparams = extract_chat_params(
        hf_model_config.get("hyperparameters", {})
        if isinstance(hf_model_config, dict)
        else {}
    )
    if hf_generation_params:
        desired.update(hf_generation_params)
        log(
            f"Applied Hugging Face generation_config defaults for model '{discovered_model}' "
            f"from {HF_MODEL_HYPERPARAMS_PATH}"
        )
    if hf_hyperparams:
        desired.update(hf_hyperparams)
        log(
            f"Applied Hugging Face hyperparameters for model '{discovered_model}' "
            f"from {HF_MODEL_HYPERPARAMS_PATH}"
        )

    # Explicit env vars override model profile defaults.
    for key, value in ENV_DEFAULTS.items():
        coerced = _coerce(value)
        if coerced is not None:
            desired[key] = coerced

    if discovered_model:
        log(
            f"Using chat defaults profile '{profile_key or 'fallback'}' for model '{discovered_model}'"
        )
    else:
        log("No discovered default chat model found; using fallback chat defaults profile")
    return desired


DESIRED: Dict[str, object] = build_desired_defaults()


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
    conn: sqlite3.Connection,
    table: str,
    id_col: str,
    settings_col: str,
    desired: Optional[Dict[str, object]] = None,
    force_overwrite: Optional[bool] = None,
) -> int:
    """
    Applies DESIRED keys only if missing under settings['chat']['params'].
    Returns number of updated rows.
    """
    updated = 0
    desired_values = desired if desired is not None else DESIRED
    overwrite = FORCE_OVERWRITE if force_overwrite is None else force_overwrite
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

        # Open WebUI reads global defaults from settings.params.
        # Keep compatibility with older payloads by importing any legacy chat.params values.
        changed = False
        params = base.get("params")
        if not isinstance(params, dict):
            params = {}
            base["params"] = params
            changed = True

        legacy_chat = base.get("chat")
        if isinstance(legacy_chat, dict):
            legacy_params = legacy_chat.get("params")
            if isinstance(legacy_params, dict):
                for key, value in legacy_params.items():
                    if key not in params:
                        params[key] = value
                        changed = True

        for k, v in desired_values.items():
            if overwrite:
                if params.get(k) != v:
                    params[k] = v
                    changed = True
            elif k not in params:
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

    # keep retrying in case the app is migrating/locking sqlite or user signs up later.
    # MAX_WAIT_SECONDS <= 0 means "wait indefinitely".
    start_ts = time.time()
    attempt = 0
    while True:
        attempt += 1
        elapsed = int(time.time() - start_ts)
        if MAX_WAIT_SECONDS > 0 and elapsed > MAX_WAIT_SECONDS:
            log(
                f"Gave up waiting for writable DB/users after {elapsed}s; no changes applied."
            )
            return

        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("PRAGMA busy_timeout=30000;")

            users_table = find_users_table(conn)
            if not users_table:
                log("Could not find users table yet; retrying...")
                if conn:
                    conn.close()
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Wait until the customer actually signs up
            if user_count(conn, users_table) < 1:
                if conn:
                    conn.close()
                time.sleep(POLL_INTERVAL_SEC)
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
            n = update_user_settings_once(
                conn,
                users_table,
                id_col,
                settings_col,
                desired=DESIRED,
                force_overwrite=FORCE_OVERWRITE,
            )
            conn.execute("COMMIT;")
            conn.close()

            # write marker into the persistent volume so it only ever runs once
            with open(MARKER, "w", encoding="utf-8") as f:
                f.write(f"done {int(time.time())}\n")

            mode = "overwrite" if FORCE_OVERWRITE else "missing-only"
            log(f"Injected defaults into {n} user(s) ({mode} mode). Done.")
            return

        except sqlite3.OperationalError as e:
            # most common: database is locked during migrations/startup
            log(f"SQLite operational error (attempt {attempt}): {e}; retrying...")
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
