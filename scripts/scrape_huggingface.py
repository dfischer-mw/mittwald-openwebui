#!/usr/bin/env python3
"""
Scrapes Hugging Face model cards/READMEs for generation hyperparameters.

Supports dynamic multi-model mode so CI can scrape all discovered model names:
- Provide `--models-file` with a JSON payload (expects `{"models": [...]}`)
- Or provide `HUGGINGFACE_MODEL_NAMES` as comma-separated names

Authentication token can be provided via:
- `HF_TOKEN` (preferred)
- `HUGGINGFACE_TOKEN` (fallback)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError as e:
    print(f"Missing dependency: {e}", file=sys.stderr)
    print("Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


HF_API_BASE = "https://huggingface.co/api"
DEFAULT_TARGET_MODEL = "meta-llama/Llama-3.1-8B-Instruct"

# Conservative fallback defaults when no model-specific settings were found.
DEFAULT_SETTINGS = {
    "temperature": 0.1,
    "top_p": 0.5,
    "top_k": 10,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}

FAMILY_FALLBACKS = {
    "ministral": {
        "temperature": 0.1,
        "top_p": 0.5,
        "top_k": 10,
        "repetition_penalty": 1.0,
        "max_tokens": 4096,
    },
    "mistral": {
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
    "llama": {
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "repetition_penalty": 1.05,
        "max_tokens": 8192,
    },
}

# Aliases for extracting README parameters dynamically.
HYPERPARAMETER_ALIASES: Dict[str, List[str]] = {
    "temperature": ["temperature"],
    "top_p": ["top_p", "topp"],
    "top_k": ["top_k", "topk"],
    "repetition_penalty": ["repetition_penalty", "repeat_penalty"],
    "max_tokens": ["max_tokens", "max_new_tokens", "num_predict", "max_completion_tokens"],
    "min_p": ["min_p"],
    "frequency_penalty": ["frequency_penalty"],
    "presence_penalty": ["presence_penalty"],
    "mirostat": ["mirostat"],
    "mirostat_eta": ["mirostat_eta"],
    "mirostat_tau": ["mirostat_tau"],
    "repeat_last_n": ["repeat_last_n"],
    "tfs_z": ["tfs_z"],
    "seed": ["seed"],
    "num_ctx": ["num_ctx"],
    "num_batch": ["num_batch"],
    "num_thread": ["num_thread"],
    "num_gpu": ["num_gpu"],
}


def _debug_enabled() -> bool:
    return os.getenv("HF_SCRAPER_DEBUG", "").lower() in {"1", "true", "yes"}


def _debug(msg: str) -> None:
    if _debug_enabled():
        print(msg, file=sys.stderr)


def get_hf_token() -> str:
    return (os.getenv("HF_TOKEN", "") or os.getenv("HUGGINGFACE_TOKEN", "")).strip()


def normalize_model_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def infer_model_family(model_name: str) -> Optional[str]:
    lowered = (model_name or "").lower()
    alias_order = [
        ("ministral", ["ministral"]),
        ("mistral", ["mistral"]),
        ("devstral", ["devstral"]),
        ("qwen", ["qwen"]),
        ("gpt-oss", ["gpt-oss", "gpt_oss", "gptoss"]),
        ("llama", ["llama"]),
    ]
    for family, aliases in alias_order:
        if any(alias in lowered for alias in aliases):
            return family
    return None


def determine_fallback_settings(model_name: str) -> Dict[str, Any]:
    family = infer_model_family(model_name)
    if family:
        return FAMILY_FALLBACKS[family].copy()
    return DEFAULT_SETTINGS.copy()


CANONICAL_KEY_MAP = {
    "max_new_tokens": "max_tokens",
    "num_predict": "max_tokens",
    "max_completion_tokens": "max_tokens",
    "topp": "top_p",
    "topk": "top_k",
    "repeat_penalty": "repetition_penalty",
}


def canonicalize_hyperparameter_key(key: str) -> str:
    normalized = (key or "").strip().lower()
    return CANONICAL_KEY_MAP.get(normalized, normalized)


def _request_json(url: str, token: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _request_text(url: str, token: str) -> str:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def search_hf_candidates(model_name: str, token: str) -> List[Dict[str, Any]]:
    try:
        response = requests.get(
            f"{HF_API_BASE}/models",
            params={"search": model_name, "limit": 20},
            headers={
                "Accept": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []
    except Exception as e:
        _debug(f"Model search failed for '{model_name}': {e}")
        return []


def pick_best_hf_model_id(model_name: str, candidates: List[Dict[str, Any]]) -> Optional[str]:
    requested_norm = normalize_model_name(model_name)

    best_score = -1
    best_id = None

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = candidate.get("id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            continue

        cid = candidate_id.strip()
        cid_norm = normalize_model_name(cid)
        score = 0

        if cid_norm == requested_norm:
            score = 100
        elif requested_norm and requested_norm in cid_norm:
            score = 80
        elif cid_norm and cid_norm in requested_norm:
            score = 60
        elif requested_norm and normalize_model_name(candidate.get("modelId", "")) == requested_norm:
            score = 90

        if score > best_score:
            best_score = score
            best_id = cid

    return best_id


def resolve_hf_model_id(model_name: str, token: str) -> Optional[str]:
    model_name = (model_name or "").strip()
    if not model_name:
        return None

    # If already explicit HF repo id form, try that first.
    if "/" in model_name:
        return model_name

    candidates = search_hf_candidates(model_name, token)
    return pick_best_hf_model_id(model_name, candidates)


def coerce_numeric(value: Any) -> Optional[Any]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        except ValueError:
            return None
    return None


def extract_card_hyperparameters(card_data: Dict[str, Any]) -> Dict[str, Any]:
    hyperparams: Dict[str, Any] = {}

    if not isinstance(card_data, dict):
        return hyperparams

    default_params = card_data.get("default_params")
    if isinstance(default_params, dict):
        for key, value in default_params.items():
            coerced = coerce_numeric(value)
            if coerced is not None:
                hyperparams[canonicalize_hyperparameter_key(str(key))] = coerced

    # Some cards use generation_config style payloads.
    generation_config = card_data.get("generation_config")
    if isinstance(generation_config, dict):
        for key, value in generation_config.items():
            coerced = coerce_numeric(value)
            canonical_key = canonicalize_hyperparameter_key(str(key))
            if coerced is not None and canonical_key not in hyperparams:
                hyperparams[canonical_key] = coerced

    return hyperparams


def extract_generation_hyperparameters(generation_config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(generation_config, dict):
        return {}

    hyperparams: Dict[str, Any] = {}
    for key, value in generation_config.items():
        coerced = coerce_numeric(value)
        if coerced is None:
            continue
        hyperparams[canonicalize_hyperparameter_key(str(key))] = coerced
    return hyperparams


def alias_to_pattern(alias: str) -> str:
    escaped = re.escape(alias)
    return escaped.replace("\\_", r"[\\s_\\-]*").replace("\\-", r"[\\s_\\-]*")


def extract_readme_hyperparameters(readme_text: str) -> Dict[str, Any]:
    if not readme_text:
        return {}

    found: Dict[str, Any] = {}

    for canonical_key, aliases in HYPERPARAMETER_ALIASES.items():
        for alias in aliases:
            ap = alias_to_pattern(alias)
            patterns = [
                rf"(?im)^\s*[\-\*>`\s\"]*{ap}\s*[:=]\s*(-?\d+(?:\.\d+)?)\b",
                rf"(?i)\"{ap}\"\s*:\s*(-?\d+(?:\.\d+)?)\b",
                rf"(?i){ap}\s*=\s*(-?\d+(?:\.\d+)?)\b",
            ]

            matched_value = None
            for pattern in patterns:
                match = re.search(pattern, readme_text)
                if match:
                    matched_value = coerce_numeric(match.group(1))
                    if matched_value is not None:
                        break

            if matched_value is not None:
                found[canonical_key] = matched_value
                break

    return found


def get_model_info(model_id: str, token: str) -> Dict[str, Any]:
    try:
        return _request_json(f"{HF_API_BASE}/models/{model_id}", token)
    except Exception as e:
        _debug(f"Error fetching model info for {model_id}: {e}")
        return {}


def scrape_model_readme(model_id: str, token: str) -> str:
    try:
        return _request_text(f"https://huggingface.co/{model_id}/raw/main/README.md", token)
    except Exception as e:
        _debug(f"Error fetching README for {model_id}: {e}")
        return ""


def scrape_model_hyperparameters(model_name: str, token: str) -> Dict[str, Any]:
    fallback = determine_fallback_settings(model_name)

    hf_model_id = resolve_hf_model_id(model_name, token)
    if not hf_model_id:
        return {
            "model_name": model_name,
            "hf_model_id": None,
            "source": "fallback_no_hf_match",
            "hyperparameters": fallback,
            "card_hyperparameters": {},
            "readme_hyperparameters": {},
            "chat_template": None,
            "generation_config": {},
        }

    model_info = get_model_info(hf_model_id, token)
    card_params = extract_card_hyperparameters(model_info.get("cardData", {}))

    readme_text = scrape_model_readme(hf_model_id, token)
    readme_params = extract_readme_hyperparameters(readme_text)

    model_generation_config = model_info.get("config", {})
    if isinstance(model_generation_config, dict):
        model_generation_config = model_generation_config.get("generation_config", {})
    if not isinstance(model_generation_config, dict):
        model_generation_config = {}
    generation_params = extract_generation_hyperparameters(model_generation_config)

    merged = fallback.copy()
    # Lowest to highest precedence.
    merged.update(generation_params)
    merged.update(card_params)
    merged.update(readme_params)

    source = "fallback"
    if generation_params or card_params or readme_params:
        source = "huggingface_scrape"

    model_chat_template = None
    if isinstance(model_info.get("config"), dict):
        model_chat_template = model_info["config"].get("chat_template")
    if not isinstance(model_chat_template, str):
        model_chat_template = None

    return {
        "model_name": model_name,
        "hf_model_id": hf_model_id,
        "source": source,
        "hyperparameters": merged,
        "generation_hyperparameters": generation_params,
        "card_hyperparameters": card_params,
        "readme_hyperparameters": readme_params,
        "chat_template": model_chat_template,
        "generation_config": model_generation_config,
    }


def extract_model_names_from_payload(payload: Any) -> List[str]:
    names: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        names.append(candidate)

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                add(item.get("name"))
                add(item.get("id"))
                add(item.get("model_id"))
        return names

    if isinstance(payload, dict):
        models = payload.get("models")
        if isinstance(models, list):
            return extract_model_names_from_payload(models)

    return names


def read_models_file(path: str) -> List[str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        _debug(f"Failed to read models file '{path}': {e}")
        return []
    return extract_model_names_from_payload(payload)


def parse_model_names_from_env() -> List[str]:
    raw = os.getenv("HUGGINGFACE_MODEL_NAMES", "")
    if not raw.strip():
        return []
    names = []
    seen = set()
    for part in raw.split(","):
        item = part.strip()
        if item and item not in seen:
            seen.add(item)
            names.append(item)
    return names


def pick_selected_model_name(scraped_model_names: List[str]) -> str:
    configured_target = os.getenv("HUGGINGFACE_TARGET_MODEL", "").strip()

    if configured_target:
        for name in scraped_model_names:
            if normalize_model_name(name) == normalize_model_name(configured_target):
                return name
        return configured_target

    if scraped_model_names:
        return scraped_model_names[0]

    return DEFAULT_TARGET_MODEL


def build_output(scraped: Dict[str, Dict[str, Any]], selected_model_name: str, token_configured: bool) -> Dict[str, Any]:
    selected = scraped.get(selected_model_name)
    if not selected and scraped:
        selected = next(iter(scraped.values()))

    selected_hparams = selected.get("hyperparameters", {}) if selected else {}

    output = {
        "temperature": selected_hparams.get("temperature", DEFAULT_SETTINGS["temperature"]),
        "top_p": selected_hparams.get("top_p", DEFAULT_SETTINGS["top_p"]),
        "top_k": selected_hparams.get("top_k", DEFAULT_SETTINGS["top_k"]),
        "repetition_penalty": selected_hparams.get("repetition_penalty", DEFAULT_SETTINGS["repetition_penalty"]),
        "max_tokens": selected_hparams.get("max_tokens", DEFAULT_SETTINGS["max_tokens"]),
        "source": selected.get("source", "fallback") if selected else "fallback",
        "selected_model": selected_model_name,
        "selected_hf_model_id": selected.get("hf_model_id") if selected else None,
        "models": scraped,
        "scrape_metadata": {
            "model_count": len(scraped),
            "token_configured": token_configured,
        },
    }

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Hugging Face hyperparameters")
    parser.add_argument(
        "--models-file",
        help="JSON file containing model names (or {models:[...]} payload)",
    )
    args = parser.parse_args()

    token = get_hf_token()

    model_names = []
    if args.models_file:
        model_names.extend(read_models_file(args.models_file))
    model_names.extend(parse_model_names_from_env())

    # Keep order while deduplicating.
    deduped: List[str] = []
    seen = set()
    for name in model_names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)

    if not deduped:
        deduped = [os.getenv("HUGGINGFACE_TARGET_MODEL", DEFAULT_TARGET_MODEL).strip() or DEFAULT_TARGET_MODEL]

    scraped: Dict[str, Dict[str, Any]] = {}
    for model_name in deduped:
        scraped[model_name] = scrape_model_hyperparameters(model_name, token)

    selected_model_name = pick_selected_model_name(deduped)
    output = build_output(scraped, selected_model_name, token_configured=bool(token))

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
