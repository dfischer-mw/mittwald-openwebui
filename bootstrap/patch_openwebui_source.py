#!/usr/bin/env python3
from pathlib import Path
import sys


TARGET = Path("/app/backend/open_webui/routers/openai.py")
PATCH_MARKER = "MITTWALD_CHAT_DEFAULTS_PATCH_V1"


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
    "temperature": 0.2,
    "top_p": 0.8,
    "top_k": 20,
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
    print("[patch-openwebui-source] patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
