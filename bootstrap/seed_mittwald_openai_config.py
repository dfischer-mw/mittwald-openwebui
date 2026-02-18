#!/usr/bin/env python3
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATA_DIR = Path(os.getenv("OWUI_DATA_DIR", "/app/backend/data"))
DB_PATH = Path(os.getenv("OWUI_DB_PATH", str(DATA_DIR / "webui.db")))
CONFIG_JSON_PATH = Path(
    os.getenv("OWUI_BOOTSTRAP_CONFIG_PATH", str(DATA_DIR / "config.json"))
)
DISCOVERY_CACHE_PATH = Path(
    os.getenv(
        "MITTWALD_DISCOVERY_CACHE_PATH", str(DATA_DIR / "mittwald-models-discovery.json")
    )
)

MITTWALD_BASE_URL = os.getenv(
    "MITTWALD_OPENAI_BASE_URL", "https://llm.aihosting.mittwald.de/v1"
)
MITTWALD_API_KEY = os.getenv("MITTWALD_OPENAI_API_KEY", "").strip()
MITTWALD_DISCOVERY_TIMEOUT_SEC = int(os.getenv("MITTWALD_DISCOVERY_TIMEOUT_SEC", "20"))
MITTWALD_PROVIDER_TAG = os.getenv("MITTWALD_PROVIDER_TAG", "mittwald")

MITTWALD_CONFIGURE_AUDIO_STT = (
    os.getenv("MITTWALD_CONFIGURE_AUDIO_STT", "true").strip().lower() == "true"
)
MITTWALD_SET_DEFAULT_MODEL = (
    os.getenv("MITTWALD_SET_DEFAULT_MODEL", "true").strip().lower() == "true"
)
MITTWALD_CONFIGURE_RAG_EMBEDDING = (
    os.getenv("MITTWALD_CONFIGURE_RAG_EMBEDDING", "true").strip().lower() == "true"
)
MITTWALD_VERIFY_MODEL_ENDPOINTS = (
    os.getenv("MITTWALD_VERIFY_MODEL_ENDPOINTS", "true").strip().lower() == "true"
)
MITTWALD_SET_RERANKING_MODEL = (
    os.getenv("MITTWALD_SET_RERANKING_MODEL", "false").strip().lower() == "true"
)

MITTWALD_CHAT_MODEL_HINT = os.getenv("MITTWALD_CHAT_MODEL_HINT", "").strip()
MITTWALD_EMBEDDING_MODEL_HINT = os.getenv("MITTWALD_EMBEDDING_MODEL_HINT", "").strip()
MITTWALD_WHISPER_MODEL_HINT = os.getenv("MITTWALD_WHISPER_MODEL_HINT", "").strip()
MITTWALD_RERANKING_MODEL_HINT = os.getenv("MITTWALD_RERANKING_MODEL_HINT", "").strip()
MITTWALD_CHAT_MODEL_PRIORITY = [
    p.strip().lower()
    for p in os.getenv(
        "MITTWALD_CHAT_MODEL_PRIORITY",
        "ministral,devstral,gpt-oss,qwen",
    ).split(",")
    if p.strip()
]
MITTWALD_EMBEDDING_PROBE_INPUT = os.getenv(
    "MITTWALD_EMBEDDING_PROBE_INPUT", "mittwald endpoint capability probe"
)


def log(msg: str) -> None:
    print(f"[bootstrap-mittwald-config] {msg}", flush=True)


def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "https://llm.aihosting.mittwald.de/v1"
    return url.rstrip("/")


def _request_json(url: str, api_key: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )

    with urlopen(request, timeout=MITTWALD_DISCOVERY_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def extract_model_ids(payload: Dict[str, Any]) -> List[str]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    model_ids: List[str] = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name")
        if isinstance(model_id, str):
            model_id = model_id.strip()
            if model_id and model_id not in seen:
                seen.add(model_id)
                model_ids.append(model_id)
    return model_ids


def _pick_by_hint(candidates: List[str], hint: str) -> Optional[str]:
    if not candidates:
        return None
    if hint:
        lowered = hint.lower()
        for model in candidates:
            if model.lower() == lowered:
                return model
        for model in candidates:
            if lowered in model.lower():
                return model
    return candidates[0]


def _pick_with_priority(candidates: List[str], hint: str, priority_tokens: List[str]) -> Optional[str]:
    picked = _pick_by_hint(candidates, hint)
    if picked is not None and hint:
        return picked
    if not candidates:
        return None
    for token in priority_tokens:
        lowered = token.lower()
        for model in candidates:
            if lowered in model.lower():
                return model
    return candidates[0]


def classify_models(model_ids: List[str]) -> Dict[str, Any]:
    whisper_candidates = [m for m in model_ids if "whisper" in m.lower()]
    embedding_candidates = [m for m in model_ids if "embedding" in m.lower()]
    reranking_candidates = [
        m
        for m in model_ids
        if any(token in m.lower() for token in ["rerank", "reranker", "ranker", "colbert"])
    ]

    excluded = set(whisper_candidates + embedding_candidates + reranking_candidates)
    chat_candidates = [m for m in model_ids if m not in excluded]

    return {
        "chat_candidates": chat_candidates,
        "embedding_candidates": embedding_candidates,
        "whisper_candidates": whisper_candidates,
        "reranking_candidates": reranking_candidates,
        "default_chat_model": _pick_with_priority(
            chat_candidates, MITTWALD_CHAT_MODEL_HINT, MITTWALD_CHAT_MODEL_PRIORITY
        ),
        "default_embedding_model": _pick_by_hint(embedding_candidates, MITTWALD_EMBEDDING_MODEL_HINT),
        "default_whisper_model": _pick_by_hint(whisper_candidates, MITTWALD_WHISPER_MODEL_HINT),
        "default_reranking_model": _pick_by_hint(reranking_candidates, MITTWALD_RERANKING_MODEL_HINT),
    }


def fetch_mittwald_models(base_url: str, api_key: str) -> List[str]:
    payload = _request_json(f"{base_url}/models", api_key, method="GET")
    return extract_model_ids(payload)


def probe_embeddings_endpoint(base_url: str, api_key: str, model_id: str) -> Tuple[bool, str]:
    if not MITTWALD_VERIFY_MODEL_ENDPOINTS:
        return True, "probe_disabled"

    try:
        payload = _request_json(
            f"{base_url}/embeddings",
            api_key,
            method="POST",
            body={
                "model": model_id,
                "input": MITTWALD_EMBEDDING_PROBE_INPUT,
            },
        )
        data = payload.get("data", [])
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict) and "embedding" in first:
                return True, "ok"
            return True, "ok_no_embedding_field"
        return False, "missing_data"
    except HTTPError as e:
        return False, f"http_{e.code}"
    except URLError as e:
        return False, f"network_{e.reason}"
    except Exception as e:
        return False, f"error_{type(e).__name__}:{e}"


def select_embedding_model(base_url: str, api_key: str, classification: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Dict[str, Any]]]:
    candidates = classification.get("embedding_candidates", [])
    checks: Dict[str, Dict[str, Any]] = {}

    for model_id in candidates:
        ok, reason = probe_embeddings_endpoint(base_url, api_key, model_id)
        checks[model_id] = {"supported": ok, "reason": reason}
        if ok:
            return model_id, checks

    return None, checks


def load_existing_config_from_db(db_path: Path) -> Dict[str, Any]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return {}

    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='config'"
        ).fetchone()
        if not table_exists:
            return {}

        row = conn.execute("SELECT data FROM config ORDER BY id DESC LIMIT 1").fetchone()
        if not row or row[0] is None:
            return {}

        raw = row[0]
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        log(f"Could not read existing config from DB ({db_path}): {e}")
    finally:
        conn.close()

    return {}


def load_previous_discovery(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ensure_dict_path(obj: Dict[str, Any], *path: str) -> Dict[str, Any]:
    cur = obj
    for key in path:
        value = cur.get(key)
        if not isinstance(value, dict):
            cur[key] = {}
        cur = cur[key]
    return cur


def as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    out.append(cleaned)
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def ensure_list_len(lst: List[str], length: int, fill: str = "") -> None:
    while len(lst) < length:
        lst.append(fill)


def merge_mittwald_openai_config(
    config: Dict[str, Any],
    base_url: str,
    api_key: str,
    discovered_model_ids: List[str],
    selected_models: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    base_url = normalize_base_url(base_url)

    if not isinstance(config, dict):
        config = {}

    openai_cfg = ensure_dict_path(config, "openai")
    openai_cfg["enable"] = True

    base_urls = as_str_list(openai_cfg.get("api_base_urls"))
    if base_url in base_urls:
        target_idx = base_urls.index(base_url)
    else:
        # Append new provider URLs to avoid reindexing existing OpenAI providers.
        base_urls.append(base_url)
        target_idx = len(base_urls) - 1
    openai_cfg["api_base_urls"] = base_urls

    api_keys = as_str_list(openai_cfg.get("api_keys"))
    ensure_list_len(api_keys, len(base_urls), "")
    api_keys[target_idx] = api_key
    openai_cfg["api_keys"] = api_keys

    api_configs = openai_cfg.get("api_configs")
    if not isinstance(api_configs, dict):
        api_configs = {}

    key = str(target_idx)
    target_config = api_configs.get(key)
    if not isinstance(target_config, dict):
        target_config = {}

    target_config["enable"] = True
    target_config.setdefault("connection_type", "external")

    tags = as_str_list(target_config.get("tags"))
    for new_tag in [MITTWALD_PROVIDER_TAG, "auto-discovered"]:
        if new_tag not in tags:
            tags.append(new_tag)
    target_config["tags"] = tags

    if discovered_model_ids:
        target_config["model_ids"] = discovered_model_ids

    api_configs[key] = target_config
    openai_cfg["api_configs"] = api_configs

    if MITTWALD_CONFIGURE_AUDIO_STT:
        audio_stt_cfg = ensure_dict_path(config, "audio", "stt")
        audio_stt_openai_cfg = ensure_dict_path(config, "audio", "stt", "openai")

        audio_stt_cfg["engine"] = "openai"
        audio_stt_openai_cfg["api_base_url"] = base_url
        audio_stt_openai_cfg["api_key"] = api_key

        whisper_model = selected_models.get("default_whisper_model")
        if whisper_model:
            audio_stt_cfg["model"] = whisper_model

        if not isinstance(audio_stt_cfg.get("supported_content_types"), list):
            audio_stt_cfg["supported_content_types"] = [
                "audio/mpeg",
                "audio/ogg",
                "audio/wav",
                "audio/flac",
            ]

    default_chat_model = selected_models.get("default_chat_model")
    if MITTWALD_SET_DEFAULT_MODEL and default_chat_model:
        ui_cfg = ensure_dict_path(config, "ui")
        ui_cfg["default_models"] = default_chat_model

    default_embedding_model = selected_models.get("default_embedding_model")
    if MITTWALD_CONFIGURE_RAG_EMBEDDING and default_embedding_model:
        rag_cfg = ensure_dict_path(config, "rag")
        rag_cfg["embedding_engine"] = "openai"
        rag_cfg["embedding_model"] = default_embedding_model
        rag_cfg["openai_api_base_url"] = base_url
        rag_cfg["openai_api_key"] = api_key

    # Optional advanced knob; disabled by default to avoid loading incompatible rerankers.
    if MITTWALD_SET_RERANKING_MODEL and selected_models.get("default_reranking_model"):
        rag_cfg = ensure_dict_path(config, "rag")
        rag_cfg["reranking_model"] = selected_models["default_reranking_model"]

    if "version" not in config:
        config["version"] = 0

    return config


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _diff_models(previous_models: List[str], current_models: List[str]) -> Dict[str, Any]:
    previous_set = set(previous_models)
    current_set = set(current_models)
    added = sorted(current_set - previous_set)
    removed = sorted(previous_set - current_set)
    return {
        "changed": bool(added or removed),
        "added": added,
        "removed": removed,
    }


def main() -> None:
    if not MITTWALD_API_KEY:
        log("MITTWALD_OPENAI_API_KEY not set; skipping Mittwald provider bootstrap.")
        return

    base_url = normalize_base_url(MITTWALD_BASE_URL)
    previous_discovery = load_previous_discovery(DISCOVERY_CACHE_PATH)
    previous_models = previous_discovery.get("models", []) if isinstance(previous_discovery, dict) else []

    discovered_models: List[str] = []
    classification: Dict[str, Any] = classify_models([])
    embedding_checks: Dict[str, Dict[str, Any]] = {}

    try:
        discovered_models = fetch_mittwald_models(base_url, MITTWALD_API_KEY)
        classification = classify_models(discovered_models)

        selected_embedding_model, embedding_checks = select_embedding_model(
            base_url, MITTWALD_API_KEY, classification
        )
        classification["default_embedding_model"] = selected_embedding_model

        log(
            f"Discovered {len(discovered_models)} Mittwald model(s) from {base_url}/models"
        )
        if selected_embedding_model:
            log(f"Selected embedding model with /embeddings support: {selected_embedding_model}")
        elif classification.get("embedding_candidates"):
            log("No embedding candidate passed /embeddings probe; keeping existing embedding config")
    except HTTPError as e:
        log(
            f"Model discovery failed with HTTP {e.code}: {e.reason}; keeping existing model_ids"
        )
    except URLError as e:
        log(f"Model discovery failed due to network error: {e}; keeping existing model_ids")
    except Exception as e:
        log(f"Model discovery failed: {e}; keeping existing model_ids")

    existing = load_existing_config_from_db(DB_PATH)
    merged = merge_mittwald_openai_config(
        config=existing,
        base_url=base_url,
        api_key=MITTWALD_API_KEY,
        discovered_model_ids=discovered_models,
        selected_models={
            "default_chat_model": classification.get("default_chat_model"),
            "default_embedding_model": classification.get("default_embedding_model"),
            "default_whisper_model": classification.get("default_whisper_model"),
            "default_reranking_model": classification.get("default_reranking_model"),
        },
    )

    write_json(CONFIG_JSON_PATH, merged)
    log(f"Wrote merged Open WebUI config to {CONFIG_JSON_PATH}")

    model_diff = _diff_models(previous_models if isinstance(previous_models, list) else [], discovered_models)
    if model_diff["changed"]:
        log(
            f"Model list changed: +{len(model_diff['added'])} / -{len(model_diff['removed'])}"
        )

    discovery_meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "model_count": len(discovered_models),
        "models": discovered_models,
        "model_diff": model_diff,
        "classification": classification,
        "embedding_probe": {
            "enabled": MITTWALD_VERIFY_MODEL_ENDPOINTS,
            "checks": embedding_checks,
        },
    }
    write_json(DISCOVERY_CACHE_PATH, discovery_meta)
    log(f"Wrote model discovery cache to {DISCOVERY_CACHE_PATH}")


if __name__ == "__main__":
    main()
