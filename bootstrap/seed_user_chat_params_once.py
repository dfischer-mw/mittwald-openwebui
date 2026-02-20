#!/usr/bin/env python3
import hashlib
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

def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


OVERWRITE_MODE_ENV = os.getenv("OWUI_BOOTSTRAP_OVERWRITE_MODE", "").strip().lower()
FORCE_OVERWRITE_ENV = os.getenv("OWUI_BOOTSTRAP_FORCE")
if OVERWRITE_MODE_ENV in {"always", "missing", "stale"}:
    OVERWRITE_MODE = OVERWRITE_MODE_ENV
elif FORCE_OVERWRITE_ENV is not None:
    OVERWRITE_MODE = (
        "always" if FORCE_OVERWRITE_ENV.strip().lower() == "true" else "missing"
    )
else:
    # Safe default for customer environments:
    # - repairs known stale factory defaults (0.8/0.9/40/128)
    # - preserves explicitly customized user values.
    OVERWRITE_MODE = "stale"

# Backward-compatible bool used by some tests/callers.
FORCE_OVERWRITE = OVERWRITE_MODE == "always"
REAPPLY_ON_START = _bool_env("OWUI_BOOTSTRAP_REAPPLY_ON_START", False)
BOOTSTRAP_MARKER_VERSION = os.getenv("OWUI_BOOTSTRAP_MARKER_VERSION", "v2")
SYNC_CHATS_ON_EVERY_START = _bool_env("OWUI_BOOTSTRAP_SYNC_CHATS_ON_EVERY_START", False)

POLL_INTERVAL_SEC = int(os.getenv("OWUI_BOOTSTRAP_POLL_INTERVAL_SEC", "2"))
MAX_WAIT_SECONDS = int(os.getenv("OWUI_BOOTSTRAP_MAX_WAIT_SECONDS", "86400"))
DB_WAIT_TIMEOUT_SEC = int(os.getenv("OWUI_BOOTSTRAP_DB_WAIT_TIMEOUT_SEC", "600"))

# Values that indicate unconfigured Open WebUI defaults we should auto-repair.
KNOWN_STALE_DEFAULTS: Dict[str, List[float]] = {
    "temperature": [0.8],
    "top_p": [0.9],
    "top_k": [40.0],
    "max_tokens": [128.0],
}

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
    "temperature": 0.1,
    "top_p": 0.5,
    "top_k": 10,
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


def _float_equal(a: Any, b: float, eps: float = 1e-9) -> bool:
    if not isinstance(a, (int, float)):
        return False
    return abs(float(a) - b) <= eps


def _is_stale_value(key: str, value: Any) -> bool:
    candidates = KNOWN_STALE_DEFAULTS.get(key, [])
    return any(_float_equal(value, candidate) for candidate in candidates)


def _resolve_overwrite_mode(
    force_overwrite: Optional[bool] = None, overwrite_mode: Optional[str] = None
) -> str:
    if overwrite_mode in {"always", "missing", "stale"}:
        return overwrite_mode
    if force_overwrite is not None:
        return "always" if force_overwrite else "missing"
    return OVERWRITE_MODE


def _should_set_param(
    container: Dict[str, Any],
    key: str,
    mode: str,
    managed_params: Optional[Dict[str, Any]] = None,
) -> bool:
    if mode == "always":
        return True
    if key not in container:
        return True
    if (
        mode == "stale"
        and isinstance(managed_params, dict)
        and key in managed_params
        and container.get(key) == managed_params.get(key)
    ):
        # Value still equals previous bootstrap-managed value, so it is safe to
        # update when defaults evolve.
        return True
    if mode == "stale":
        return _is_stale_value(key, container.get(key))
    return False


def _desired_fingerprint(desired: Dict[str, Any]) -> str:
    encoded = json.dumps(desired, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_marker(path: str) -> Dict[str, Any]:
    marker_path = Path(path)
    if not marker_path.exists():
        return {}
    try:
        raw = marker_path.read_text(encoding="utf-8").strip()
    except Exception:
        return {"legacy": True}
    if not raw:
        return {"legacy": True}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"legacy": True}


def _marker_needs_full_sync(marker: Dict[str, Any], desired: Dict[str, Any]) -> bool:
    if not marker:
        return True
    if marker.get("legacy") is True:
        return True
    if marker.get("version") != BOOTSTRAP_MARKER_VERSION:
        return True
    if marker.get("desired_hash") != _desired_fingerprint(desired):
        return True
    return False


def _write_marker(path: str, payload: Dict[str, Any]) -> None:
    marker_path = Path(path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


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


def find_chat_table(conn: sqlite3.Connection) -> Optional[str]:
    tables = list_tables(conn)
    candidates = []
    for t in tables:
        cols = set(table_columns(conn, t))
        if "chat" in cols and ("user_id" in cols or "id" in cols):
            score = 0
            for c in ("created_at", "updated_at", "title"):
                if c in cols:
                    score += 1
            candidates.append((score, t))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    if "chat" in tables:
        return "chat"
    return None


def find_chat_payload_column(conn: sqlite3.Connection, table: str) -> Optional[str]:
    cols = table_columns(conn, table)
    for c in ("chat", "payload", "data", "content"):
        if c in cols:
            return c
    return None


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
    overwrite_mode: Optional[str] = None,
) -> int:
    """
    Applies desired keys under current Open WebUI path settings['ui']['params']
    and mirrors to legacy paths for compatibility:
    - settings['ui']['chat']['params']
    - settings['params']
    - settings['chat']['params']
    Returns number of updated rows.
    """
    updated = 0
    desired_values = desired if desired is not None else DESIRED
    mode = _resolve_overwrite_mode(
        force_overwrite=force_overwrite, overwrite_mode=overwrite_mode
    )
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

        changed = False

        # Canonical path for current Open WebUI versions:
        # settings.ui.params (loaded by frontend through userSettings.ui).
        ui = base.get("ui")
        if not isinstance(ui, dict):
            ui = {}
            base["ui"] = ui
            changed = True

        params = ui.get("params")
        if not isinstance(params, dict):
            params = {}
            ui["params"] = params
            changed = True

        ui_chat = ui.get("chat")
        if not isinstance(ui_chat, dict):
            ui_chat = {}
            ui["chat"] = ui_chat
            changed = True

        ui_chat_params = ui_chat.get("params")
        if not isinstance(ui_chat_params, dict):
            ui_chat_params = {}
            ui_chat["params"] = ui_chat_params
            changed = True

        # Legacy compatibility paths (older payload shapes we still keep in sync).
        legacy_top_params = base.get("params")
        if not isinstance(legacy_top_params, dict):
            legacy_top_params = {}
            base["params"] = legacy_top_params
            changed = True

        legacy_top_chat = base.get("chat")
        if not isinstance(legacy_top_chat, dict):
            legacy_top_chat = {}
            base["chat"] = legacy_top_chat
            changed = True

        legacy_top_chat_params = legacy_top_chat.get("params")
        if not isinstance(legacy_top_chat_params, dict):
            legacy_top_chat_params = {}
            legacy_top_chat["params"] = legacy_top_chat_params
            changed = True

        compatibility_params = [ui_chat_params, legacy_top_params, legacy_top_chat_params]

        # Per-user bootstrap metadata lets us safely evolve defaults later without
        # clobbering customer-edited values.
        ui_bootstrap_meta = ui.get("_mittwald_bootstrap")
        if not isinstance(ui_bootstrap_meta, dict):
            ui_bootstrap_meta = {}
            ui["_mittwald_bootstrap"] = ui_bootstrap_meta
            changed = True
        managed_params = ui_bootstrap_meta.get("managed_params")
        if not isinstance(managed_params, dict):
            managed_params = {}
            ui_bootstrap_meta["managed_params"] = managed_params
            changed = True

        # Migrate forward from legacy paths to canonical ui.params.
        for source in compatibility_params:
            for key, value in source.items():
                if key not in params:
                    params[key] = value
                    changed = True
                elif (
                    mode == "stale"
                    and _is_stale_value(key, params.get(key))
                    and not _is_stale_value(key, value)
                ):
                    params[key] = value
                    changed = True

        for k, v in desired_values.items():
            if _should_set_param(params, k, mode, managed_params=managed_params):
                if params.get(k) != v:
                    params[k] = v
                    changed = True
                if managed_params.get(k) != v:
                    managed_params[k] = v
                    changed = True
            elif (
                mode != "always"
                and k in managed_params
                and params.get(k) != managed_params.get(k)
            ):
                # Value drifted away from bootstrap-managed value; treat as
                # customer-owned.
                managed_params.pop(k, None)
                changed = True

            for target in compatibility_params:
                if _should_set_param(target, k, mode) and target.get(k) != params.get(k):
                    target[k] = params.get(k)
                    changed = True

        # Keep all compatibility paths aligned with canonical ui.params.
        for target in compatibility_params:
            for key, value in params.items():
                if _should_set_param(target, key, mode) and target.get(key) != value:
                    target[key] = value
                    changed = True

        # Ensure missing desired keys are present in all paths even in missing mode.
        for k, v in desired_values.items():
            if k not in params:
                params[k] = v
                changed = True
            for target in compatibility_params:
                if k not in target:
                    target[k] = params.get(k)
                    changed = True

        desired_hash = _desired_fingerprint(
            desired_values if isinstance(desired_values, dict) else {}
        )
        metadata_changed = False
        if ui_bootstrap_meta.get("version") != BOOTSTRAP_MARKER_VERSION:
            ui_bootstrap_meta["version"] = BOOTSTRAP_MARKER_VERSION
            metadata_changed = True
        if ui_bootstrap_meta.get("desired_hash") != desired_hash:
            ui_bootstrap_meta["desired_hash"] = desired_hash
            metadata_changed = True
        if changed or metadata_changed:
            ui_bootstrap_meta["updated_at_epoch"] = int(time.time())
            changed = True

        if changed:
            conn.execute(
                f"UPDATE '{table}' SET {settings_col} = ? WHERE {id_col} = ?",
                (json.dumps(base, ensure_ascii=False), user_id),
            )
            updated += 1

    return updated


def update_chat_params_once(
    conn: sqlite3.Connection,
    table: str,
    id_col: str,
    payload_col: str,
    desired: Optional[Dict[str, object]] = None,
    force_overwrite: Optional[bool] = None,
    overwrite_mode: Optional[str] = None,
) -> int:
    updated = 0
    desired_values = desired if desired is not None else DESIRED
    mode = _resolve_overwrite_mode(
        force_overwrite=force_overwrite, overwrite_mode=overwrite_mode
    )
    cur = conn.execute(f"SELECT {id_col}, {payload_col} FROM '{table}'")
    rows = cur.fetchall()

    def apply_desired(params_obj: Optional[dict]) -> tuple[dict, bool]:
        changed_local = False
        params_local = params_obj if isinstance(params_obj, dict) else {}
        if not isinstance(params_obj, dict):
            changed_local = True

        for k, v in desired_values.items():
            if _should_set_param(params_local, k, mode) and params_local.get(k) != v:
                params_local[k] = v
                changed_local = True
        return params_local, changed_local

    for row_id, payload_raw in rows:
        payload = {}
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}

        changed = False
        params, params_changed = apply_desired(payload.get("params"))
        payload["params"] = params
        changed = changed or params_changed

        # Some Open WebUI versions keep per-message param snapshots in history.
        # Normalize those too so old chats do not keep stale defaults (e.g. 0.8).
        history = payload.get("history")
        if isinstance(history, dict):
            messages = history.get("messages")
            if isinstance(messages, dict):
                for _msg_id, msg in messages.items():
                    if not isinstance(msg, dict):
                        continue
                    if "params" not in msg and mode == "missing":
                        continue
                    new_msg_params, msg_changed = apply_desired(msg.get("params"))
                    if msg_changed:
                        msg["params"] = new_msg_params
                        changed = True

        # Keep compatibility with list-based message payload snapshots.
        message_list = payload.get("messages")
        if isinstance(message_list, list):
            for msg in message_list:
                if not isinstance(msg, dict):
                    continue
                if "params" not in msg and mode == "missing":
                    continue
                new_msg_params, msg_changed = apply_desired(msg.get("params"))
                if msg_changed:
                    msg["params"] = new_msg_params
                    changed = True

        if changed:
            conn.execute(
                f"UPDATE '{table}' SET {payload_col} = ? WHERE {id_col} = ?",
                (json.dumps(payload, ensure_ascii=False), row_id),
            )
            updated += 1

    return updated


def main():
    if not DESIRED:
        log("No OWUI_BOOTSTRAP_* env vars set; nothing to do.")
        return

    marker_state = _read_marker(MARKER)
    desired_hash = _desired_fingerprint(DESIRED)
    needs_full_sync = _marker_needs_full_sync(marker_state, DESIRED)
    run_mode = OVERWRITE_MODE

    if REAPPLY_ON_START:
        needs_full_sync = True
        log("OWUI_BOOTSTRAP_REAPPLY_ON_START=true; forcing full bootstrap sync.")
    elif needs_full_sync:
        if marker_state.get("legacy"):
            log("Legacy marker detected; running bootstrap migration sync.")
        elif not marker_state:
            log("No marker found; running initial bootstrap sync.")
        elif marker_state.get("version") != BOOTSTRAP_MARKER_VERSION:
            log(
                "Marker version mismatch "
                f"({marker_state.get('version')} -> {BOOTSTRAP_MARKER_VERSION}); running sync."
            )
        else:
            log("Desired defaults changed since last marker; running sync.")
    else:
        log(
            "Marker is current; running safety sync for users "
            f"(mode={run_mode}, sync_chats={SYNC_CHATS_ON_EVERY_START})."
        )

    log(f"Waiting for DB: {DB_PATH}")
    try:
        wait_for_db(DB_PATH, timeout_s=DB_WAIT_TIMEOUT_SEC)
    except TimeoutError:
        log(
            f"DB not ready within {DB_WAIT_TIMEOUT_SEC}s ({DB_PATH}); skipping bootstrap attempt."
        )
        return

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
            n_users = update_user_settings_once(
                conn,
                users_table,
                id_col,
                settings_col,
                desired=DESIRED,
                overwrite_mode=run_mode,
            )
            n_chats = 0
            run_chat_sync = needs_full_sync or SYNC_CHATS_ON_EVERY_START
            if run_chat_sync:
                chat_table = find_chat_table(conn)
                if chat_table:
                    chat_payload_col = find_chat_payload_column(conn, chat_table)
                    if chat_payload_col:
                        chat_id_col = find_id_column(conn, chat_table)
                        n_chats = update_chat_params_once(
                            conn,
                            chat_table,
                            chat_id_col,
                            chat_payload_col,
                            desired=DESIRED,
                            overwrite_mode=run_mode,
                        )
            conn.execute("COMMIT;")
            conn.close()

            marker_payload = {
                "version": BOOTSTRAP_MARKER_VERSION,
                "desired_hash": desired_hash,
                "overwrite_mode": run_mode,
                "sync_chats": bool(run_chat_sync),
                "updated_at_epoch": int(time.time()),
                "users_updated": n_users,
                "chats_updated": n_chats,
            }
            _write_marker(MARKER, marker_payload)

            log(
                "Injected defaults into "
                f"{n_users} user(s) and {n_chats} chat(s) "
                f"(mode={run_mode}, full_sync={needs_full_sync}). Done."
            )
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
