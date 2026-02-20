#!/usr/bin/env python3
from pathlib import Path
import re
import sys


TARGET = Path("/app/backend/open_webui/routers/openai.py")
PATCH_MARKER = "MITTWALD_CHAT_DEFAULTS_PATCH_V1"
USERS_TARGET = Path("/app/backend/open_webui/models/users.py")
USERS_PATCH_MARKER = "MITTWALD_USER_SETTINGS_PATCH_V1"
FRONTEND_BUNDLE_ROOT = Path("/app/build/_app/immutable")
FRONTEND_CHAT_PARAM_DEFAULTS = {
    "temperature": "0.1",
    "top_p": "0.5",
    "top_k": "10",
    "max_tokens": "4096",
}


IMPORT_NEEDLE = "import logging\nfrom typing import Optional\n"
IMPORT_REPLACEMENT = "import logging\nimport os\nfrom pathlib import Path\nfrom typing import Optional\n"

HELPERS_BLOCK = f"""
# {PATCH_MARKER}
MITTWALD_MODEL_PROFILES = {{
    "ministral": {{
        "temperature": 0.1,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    }},
    "devstral": {{
        "temperature": 0.15,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    }},
    "qwen": {{
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    }},
    "gpt-oss": {{
        "temperature": 0.2,
        "top_p": 0.7,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    }},
}}

MITTWALD_FALLBACK_PROFILE = {{
    "temperature": 0.1,
    "top_p": 0.5,
    "top_k": 10,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}}

MITTWALD_ALLOWED_CHAT_PARAM_KEYS = {{
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
}}

MITTWALD_CANONICAL_CHAT_PARAM_KEYS = {{
    "repeat_penalty": "repetition_penalty",
    "max_new_tokens": "max_tokens",
    "num_predict": "max_tokens",
    "max_completion_tokens": "max_tokens",
    "topp": "top_p",
    "topk": "top_k",
}}

MITTWALD_ENV_DEFAULTS = {{
    "temperature": "OWUI_BOOTSTRAP_TEMPERATURE",
    "top_p": "OWUI_BOOTSTRAP_TOP_P",
    "top_k": "OWUI_BOOTSTRAP_TOP_K",
    "repetition_penalty": "OWUI_BOOTSTRAP_REPETITION_PENALTY",
    "max_tokens": "OWUI_BOOTSTRAP_MAX_TOKENS",
}}


def _mittwald_coerce(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    if not isinstance(v, str):
        return None

    normalized = v.strip().replace(",", ".")
    try:
        if any(ch in normalized for ch in (".", "e", "E")):
            return float(normalized)
        return int(normalized)
    except Exception:
        return None


def _mittwald_normalize_model_name(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _mittwald_load_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {{}}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {{}}
    except Exception:
        return {{}}


def _mittwald_extract_chat_params(raw: dict) -> dict:
    out = {{}}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        canonical_key = MITTWALD_CANONICAL_CHAT_PARAM_KEYS.get(key, key)
        if canonical_key not in MITTWALD_ALLOWED_CHAT_PARAM_KEYS:
            continue
        coerced = _mittwald_coerce(value)
        if isinstance(coerced, (int, float)):
            out[canonical_key] = coerced
    return out


def _mittwald_collect_user_params(user) -> dict:
    out = {{}}
    if user is None:
        return out

    try:
        settings = getattr(user, "settings", None)
        if settings is None:
            return out
        if hasattr(settings, "model_dump"):
            settings = settings.model_dump()
        if not isinstance(settings, dict):
            return out

        candidates = []
        ui = settings.get("ui")
        if isinstance(ui, dict):
            if isinstance(ui.get("params"), dict):
                candidates.append(ui.get("params"))
            ui_chat = ui.get("chat")
            if isinstance(ui_chat, dict) and isinstance(ui_chat.get("params"), dict):
                candidates.append(ui_chat.get("params"))

        if isinstance(settings.get("params"), dict):
            candidates.append(settings.get("params"))
        top_chat = settings.get("chat")
        if isinstance(top_chat, dict) and isinstance(top_chat.get("params"), dict):
            candidates.append(top_chat.get("params"))

        for source in candidates:
            extracted = _mittwald_extract_chat_params(source)
            for key, value in extracted.items():
                if key not in out:
                    out[key] = value
    except Exception as e:
        log.debug(f"Failed to read user settings params: {{e}}")

    return out


def _mittwald_pick_profile_key(model_name: str | None) -> str | None:
    if not model_name:
        return None
    lowered = model_name.lower()
    for key in MITTWALD_MODEL_PROFILES:
        if key in lowered:
            return key
    return None


def _mittwald_find_hf_model_config(model_name: str | None) -> dict:
    if not model_name:
        return {{}}
    hf_path = Path(
        os.getenv(
            "HF_MODEL_HYPERPARAMS_PATH",
            "/usr/local/share/openwebui/hf-model-hyperparameters.json",
        )
    )
    payload = _mittwald_load_json(hf_path)
    models = payload.get("models", {{}})
    if not isinstance(models, dict):
        return {{}}

    direct = models.get(model_name)
    if isinstance(direct, dict):
        return direct

    wanted = _mittwald_normalize_model_name(model_name)
    for key, value in models.items():
        if _mittwald_normalize_model_name(str(key)) != wanted:
            continue
        if isinstance(value, dict):
            return value

    return {{}}


def _mittwald_build_chat_defaults(model_name: str | None) -> dict:
    profile_key = _mittwald_pick_profile_key(model_name)
    desired = (
        MITTWALD_MODEL_PROFILES.get(profile_key, MITTWALD_FALLBACK_PROFILE).copy()
        if profile_key
        else MITTWALD_FALLBACK_PROFILE.copy()
    )

    hf_model_config = _mittwald_find_hf_model_config(model_name)
    generation_defaults = _mittwald_extract_chat_params(
        hf_model_config.get("generation_config", {{}})
        if isinstance(hf_model_config, dict)
        else {{}}
    )
    model_defaults = _mittwald_extract_chat_params(
        hf_model_config.get("hyperparameters", {{}})
        if isinstance(hf_model_config, dict)
        else {{}}
    )
    if generation_defaults:
        desired.update(generation_defaults)
    if model_defaults:
        desired.update(model_defaults)

    for key, env_key in MITTWALD_ENV_DEFAULTS.items():
        env_value = _mittwald_coerce(os.getenv(env_key))
        if env_value is not None:
            desired[key] = env_value

    return desired


def apply_mittwald_chat_defaults(payload: dict, user=None) -> dict:
    if not isinstance(payload, dict):
        return payload

    try:
        model_name = payload.get("model")
        defaults = _mittwald_build_chat_defaults(model_name)
        user_params = _mittwald_collect_user_params(user)

        keys = set(defaults.keys()) | set(user_params.keys())
        for key in keys:
            # Request body has highest priority.
            if payload.get(key) is not None:
                continue

            # Customer/user values are second priority.
            if user_params.get(key) is not None:
                payload[key] = user_params[key]
                continue

            # Mittwald-discovered defaults are fallback.
            value = defaults.get(key)
            if value is not None:
                payload[key] = value
    except Exception as e:
        log.debug(f"Failed to apply mittwald chat defaults: {{e}}")

    return payload
# END {PATCH_MARKER}
"""


def fail(msg: str) -> int:
    print(f"[patch-openwebui-source] ERROR: {msg}", file=sys.stderr)
    return 1


def patch_frontend_chat_defaults() -> tuple[int, int]:
    if not FRONTEND_BUNDLE_ROOT.exists():
        print("[patch-openwebui-source] frontend bundle not found; skipping frontend patch")
        return (0, 0)

    files_changed = 0
    replacements = 0

    patterns = {
        key: re.compile(
            rf"(\.{key}\)\?\?null\)===null\?)([^:]+)(:null,!0\))",
            re.IGNORECASE,
        )
        for key in FRONTEND_CHAT_PARAM_DEFAULTS
    }

    for path in FRONTEND_BUNDLE_ROOT.rglob("*.js"):
        src = path.read_text(encoding="utf-8")
        out = src

        for key, default_value in FRONTEND_CHAT_PARAM_DEFAULTS.items():
            out, n = patterns[key].subn(
                lambda m, d=default_value: f"{m.group(1)}{d}{m.group(3)}",
                out,
            )
            replacements += n

        if out != src:
            path.write_text(out, encoding="utf-8")
            files_changed += 1

    print(
        "[patch-openwebui-source] frontend chat defaults patch applied "
        f"(files={files_changed}, replacements={replacements})"
    )
    return files_changed, replacements


def main() -> int:
    if not TARGET.exists():
        return fail(f"target does not exist: {TARGET}")

    src = TARGET.read_text(encoding="utf-8")
    if PATCH_MARKER in src:
        print("[patch-openwebui-source] patch already applied")
        return 0

    if IMPORT_NEEDLE not in src:
        return fail("import insertion anchor not found")
    src = src.replace(IMPORT_NEEDLE, IMPORT_REPLACEMENT, 1)

    reason_fn_anchor = "def openai_reasoning_model_handler(payload):"
    if reason_fn_anchor not in src:
        return fail("openai_reasoning_model_handler anchor not found")
    src = src.replace(reason_fn_anchor, f"{HELPERS_BLOCK}\n{reason_fn_anchor}", 1)

    call_anchor = (
        '    # Check if model is a reasoning model that needs special handling\n'
    )
    if call_anchor not in src:
        return fail("payload injection anchor not found")

    call_injection = (
        "    payload = apply_mittwald_chat_defaults(payload, user=user)\n\n"
        "    # Check if model is a reasoning model that needs special handling\n"
    )
    src = src.replace(call_anchor, call_injection, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("[patch-openwebui-source] openai router patch applied")

    if not USERS_TARGET.exists():
        return fail(f"users target does not exist: {USERS_TARGET}")

    users_src = USERS_TARGET.read_text(encoding="utf-8")
    if USERS_PATCH_MARKER not in users_src:
        users_import_needle = "import time\nfrom typing import Optional\n"
        users_import_replacement = (
            "import json\n"
            "import os\n"
            "import time\n"
            "from pathlib import Path\n"
            "from typing import Any, Dict, Optional\n"
        )
        if users_import_needle not in users_src:
            return fail("users import insertion anchor not found")
        users_src = users_src.replace(users_import_needle, users_import_replacement, 1)

        users_helper_block = f"""
# {USERS_PATCH_MARKER}
MITTWALD_DISCOVERY_CACHE_PATH = Path(
    os.getenv(
        "MITTWALD_DISCOVERY_CACHE_PATH",
        "/app/backend/data/mittwald-models-discovery.json",
    )
)
MITTWALD_HF_MODEL_HYPERPARAMS_PATH = Path(
    os.getenv(
        "HF_MODEL_HYPERPARAMS_PATH",
        "/usr/local/share/openwebui/hf-model-hyperparameters.json",
    )
)
MITTWALD_MODEL_PROFILES = {{
    "ministral": {{
        "temperature": 0.1,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    }},
    "devstral": {{
        "temperature": 0.15,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    }},
    "qwen": {{
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    }},
    "gpt-oss": {{
        "temperature": 0.2,
        "top_p": 0.7,
        "top_k": 20,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    }},
}}
MITTWALD_FALLBACK_PROFILE = {{
    "temperature": 0.1,
    "top_p": 0.5,
    "top_k": 10,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}}
MITTWALD_ALLOWED_CHAT_PARAM_KEYS = {{
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
}}
MITTWALD_CANONICAL_CHAT_PARAM_KEYS = {{
    "repeat_penalty": "repetition_penalty",
    "max_new_tokens": "max_tokens",
    "num_predict": "max_tokens",
    "max_completion_tokens": "max_tokens",
    "topp": "top_p",
    "topk": "top_k",
}}
MITTWALD_ENV_DEFAULTS = {{
    "temperature": "OWUI_BOOTSTRAP_TEMPERATURE",
    "top_p": "OWUI_BOOTSTRAP_TOP_P",
    "top_k": "OWUI_BOOTSTRAP_TOP_K",
    "repetition_penalty": "OWUI_BOOTSTRAP_REPETITION_PENALTY",
    "max_tokens": "OWUI_BOOTSTRAP_MAX_TOKENS",
}}


def _mittwald_coerce(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    if not isinstance(v, str):
        return None
    normalized = v.strip().replace(",", ".")
    try:
        if any(ch in normalized for ch in (".", "e", "E")):
            return float(normalized)
        return int(normalized)
    except Exception:
        return None


def _mittwald_normalize_model_name(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _mittwald_load_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {{}}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {{}}
    except Exception:
        return {{}}


def _mittwald_extract_chat_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {{}}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        canonical_key = MITTWALD_CANONICAL_CHAT_PARAM_KEYS.get(key, key)
        if canonical_key not in MITTWALD_ALLOWED_CHAT_PARAM_KEYS:
            continue
        coerced = _mittwald_coerce(value)
        if isinstance(coerced, (int, float)):
            out[canonical_key] = coerced
    return out


def _mittwald_default_chat_model() -> Optional[str]:
    payload = _mittwald_load_json(MITTWALD_DISCOVERY_CACHE_PATH)
    classification = payload.get("classification", {{}})
    if isinstance(classification, dict):
        model = classification.get("default_chat_model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


def _mittwald_pick_profile_key(model_name: Optional[str]) -> Optional[str]:
    if not model_name:
        return None
    lowered = model_name.lower()
    for key in MITTWALD_MODEL_PROFILES:
        if key in lowered:
            return key
    return None


def _mittwald_find_hf_model_config(model_name: Optional[str]) -> Dict[str, Any]:
    if not model_name:
        return {{}}
    payload = _mittwald_load_json(MITTWALD_HF_MODEL_HYPERPARAMS_PATH)
    models = payload.get("models", {{}})
    if not isinstance(models, dict):
        return {{}}

    direct = models.get(model_name)
    if isinstance(direct, dict):
        return direct

    wanted = _mittwald_normalize_model_name(model_name)
    for key, value in models.items():
        if _mittwald_normalize_model_name(str(key)) != wanted:
            continue
        if isinstance(value, dict):
            return value
    return {{}}


def _mittwald_build_default_params() -> Dict[str, Any]:
    model_name = _mittwald_default_chat_model()
    profile_key = _mittwald_pick_profile_key(model_name)
    desired: Dict[str, Any] = (
        MITTWALD_MODEL_PROFILES.get(profile_key, MITTWALD_FALLBACK_PROFILE).copy()
        if profile_key
        else MITTWALD_FALLBACK_PROFILE.copy()
    )

    hf_model_config = _mittwald_find_hf_model_config(model_name)
    generation_defaults = _mittwald_extract_chat_params(
        hf_model_config.get("generation_config", {{}})
        if isinstance(hf_model_config, dict)
        else {{}}
    )
    model_defaults = _mittwald_extract_chat_params(
        hf_model_config.get("hyperparameters", {{}})
        if isinstance(hf_model_config, dict)
        else {{}}
    )
    if generation_defaults:
        desired.update(generation_defaults)
    if model_defaults:
        desired.update(model_defaults)

    for key, env_key in MITTWALD_ENV_DEFAULTS.items():
        env_value = _mittwald_coerce(os.getenv(env_key))
        if env_value is not None:
            desired[key] = env_value

    return desired


def build_mittwald_initial_user_settings() -> Dict[str, Any]:
    params = _mittwald_build_default_params()
    return {{
        "ui": {{
            "params": dict(params),
            "chat": {{"params": dict(params)}},
        }},
        "params": dict(params),
        "chat": {{"params": dict(params)}},
    }}


def deep_merge_user_settings(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge_user_settings(base[key], value)
        else:
            base[key] = value
    return base
# END {USERS_PATCH_MARKER}
"""

        users_class_anchor = "class UsersTable:\n"
        if users_class_anchor not in users_src:
            return fail("users class anchor not found")
        users_src = users_src.replace(
            users_class_anchor, f"{users_helper_block}\n\n{users_class_anchor}", 1
        )

        user_insert_anchor = '                    "oauth": oauth,\n'
        if user_insert_anchor not in users_src:
            return fail("users insert anchor not found")
        users_src = users_src.replace(
            user_insert_anchor,
            user_insert_anchor + '                    "settings": build_mittwald_initial_user_settings(),\n',
            1,
        )

        merge_anchor = (
            "                if user_settings is None:\n"
            "                    user_settings = {}\n\n"
            "                user_settings.update(updated)\n\n"
            '                db.query(User).filter_by(id=id).update({"settings": user_settings})\n'
        )
        merge_replacement = (
            "                if user_settings is None or not isinstance(user_settings, dict):\n"
            "                    user_settings = {}\n\n"
            "                updates = updated if isinstance(updated, dict) else {}\n"
            "                user_settings = deep_merge_user_settings(user_settings, updates)\n\n"
            '                db.query(User).filter_by(id=id).update({"settings": user_settings})\n'
        )
        if merge_anchor not in users_src:
            return fail("users deep-merge anchor not found")
        users_src = users_src.replace(merge_anchor, merge_replacement, 1)

        USERS_TARGET.write_text(users_src, encoding="utf-8")
        print("[patch-openwebui-source] users model patch applied")
    else:
        print("[patch-openwebui-source] users model patch already applied")

    patch_frontend_chat_defaults()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
