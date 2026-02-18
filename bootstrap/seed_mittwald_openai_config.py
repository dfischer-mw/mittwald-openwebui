#!/usr/bin/env python3
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
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


def log(msg: str) -> None:
    print(f"[bootstrap-mittwald-config] {msg}", flush=True)


def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "https://llm.aihosting.mittwald.de/v1"
    return url.rstrip("/")


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


def classify_models(model_ids: List[str]) -> Dict[str, Optional[str]]:
    whisper = [m for m in model_ids if "whisper" in m.lower()]
    embeddings = [m for m in model_ids if "embedding" in m.lower()]
    chat = [m for m in model_ids if m not in whisper and m not in embeddings]

    return {
        "default_chat_model": chat[0] if chat else None,
        "default_embedding_model": embeddings[0] if embeddings else None,
        "default_whisper_model": whisper[0] if whisper else None,
    }


def fetch_mittwald_models(base_url: str, api_key: str) -> List[str]:
    request = Request(
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    with urlopen(request, timeout=MITTWALD_DISCOVERY_TIMEOUT_SEC) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return extract_model_ids(payload)


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
        base_urls.insert(0, base_url)
        target_idx = 0
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

        whisper_model = next(
            (m for m in discovered_model_ids if "whisper" in m.lower()), None
        )
        if whisper_model:
            audio_stt_cfg["model"] = whisper_model

        if not isinstance(audio_stt_cfg.get("supported_content_types"), list):
            audio_stt_cfg["supported_content_types"] = [
                "audio/mpeg",
                "audio/ogg",
                "audio/wav",
                "audio/flac",
            ]

    classified = classify_models(discovered_model_ids)
    default_chat_model = classified.get("default_chat_model")
    default_embedding_model = classified.get("default_embedding_model")

    if MITTWALD_SET_DEFAULT_MODEL and default_chat_model:
        ui_cfg = ensure_dict_path(config, "ui")
        ui_cfg["default_models"] = default_chat_model

    if MITTWALD_CONFIGURE_RAG_EMBEDDING and default_embedding_model:
        rag_cfg = ensure_dict_path(config, "rag")
        rag_cfg["embedding_engine"] = "openai"
        rag_cfg["embedding_model"] = default_embedding_model
        rag_cfg["openai_api_base_url"] = base_url
        rag_cfg["openai_api_key"] = api_key

    if "version" not in config:
        config["version"] = 0

    return config


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    if not MITTWALD_API_KEY:
        log("MITTWALD_OPENAI_API_KEY not set; skipping Mittwald provider bootstrap.")
        return

    base_url = normalize_base_url(MITTWALD_BASE_URL)

    discovered_models: List[str] = []
    try:
        discovered_models = fetch_mittwald_models(base_url, MITTWALD_API_KEY)
        log(f"Discovered {len(discovered_models)} Mittwald model(s) from {base_url}/models")
    except HTTPError as e:
        log(f"Model discovery failed with HTTP {e.code}: {e.reason}; keeping existing model_ids")
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
    )

    write_json(CONFIG_JSON_PATH, merged)
    log(f"Wrote merged Open WebUI config to {CONFIG_JSON_PATH}")

    discovery_meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "model_count": len(discovered_models),
        "models": discovered_models,
        "classified": classify_models(discovered_models),
    }
    write_json(DISCOVERY_CACHE_PATH, discovery_meta)
    log(f"Wrote model discovery cache to {DISCOVERY_CACHE_PATH}")


if __name__ == "__main__":
    main()
