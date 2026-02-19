import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bootstrap" / "seed_mittwald_openai_config.py"

spec = importlib.util.spec_from_file_location("seed_mittwald", MODULE_PATH)
seed = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(seed)


def test_extract_model_ids_deduplicates_and_preserves_order():
    payload = {
        "data": [
            {"id": "Ministral-3-14B-Instruct-2512"},
            {"name": "Whisper-Large-V3-Turbo"},
            {"id": "Ministral-3-14B-Instruct-2512"},
            {"id": "Qwen3-Embedding-8B"},
        ]
    }

    model_ids = seed.extract_model_ids(payload)

    assert model_ids == [
        "Ministral-3-14B-Instruct-2512",
        "Whisper-Large-V3-Turbo",
        "Qwen3-Embedding-8B",
    ]


def test_classify_models_picks_chat_embedding_and_whisper_defaults():
    model_ids = [
        "Qwen3-Embedding-8B",
        "Ministral-3-14B-Instruct-2512",
        "Whisper-Large-V3-Turbo",
        "BGE-Reranker-v2",
    ]

    classified = seed.classify_models(model_ids)

    assert classified["default_chat_model"] == "Ministral-3-14B-Instruct-2512"
    assert classified["default_embedding_model"] == "Qwen3-Embedding-8B"
    assert classified["default_whisper_model"] == "Whisper-Large-V3-Turbo"
    assert classified["default_reranking_model"] == "BGE-Reranker-v2"


def test_classify_models_prefers_ministral_with_default_priority():
    model_ids = [
        "gpt-oss-120b",
        "Ministral-3-14B-Instruct-2512",
        "Qwen3-Embedding-8B",
    ]

    classified = seed.classify_models(model_ids)

    assert classified["default_chat_model"] == "Ministral-3-14B-Instruct-2512"


def test_select_embedding_model_probes_until_supported(monkeypatch):
    classification = {
        "embedding_candidates": ["Emb-A", "Emb-B"],
    }

    def fake_probe(base_url, api_key, model_id):
        if model_id == "Emb-A":
            return False, "http_400"
        return True, "ok"

    monkeypatch.setattr(seed, "probe_embeddings_endpoint", fake_probe)

    selected, checks = seed.select_embedding_model(
        "https://llm.aihosting.mittwald.de/v1",
        "mw-key",
        classification,
    )

    assert selected == "Emb-B"
    assert checks["Emb-A"]["supported"] is False
    assert checks["Emb-B"]["supported"] is True


def test_merge_mittwald_openai_config_injects_models_and_audio_defaults(monkeypatch):
    monkeypatch.setattr(seed, "MITTWALD_PROVIDER_TAG", "mittwald")
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_AUDIO_STT", True)
    monkeypatch.setattr(seed, "MITTWALD_SET_DEFAULT_MODEL", True)
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_RAG_EMBEDDING", True)

    config = {
        "openai": {
            "enable": True,
            "api_base_urls": ["https://api.openai.com/v1"],
            "api_keys": ["sk-openai"],
            "api_configs": {"0": {"enable": True, "model_ids": ["gpt-4.1"]}},
        }
    }

    out = seed.merge_mittwald_openai_config(
        config=config,
        base_url="https://llm.aihosting.mittwald.de/v1",
        api_key="mw-key",
        discovered_model_ids=[
            "Ministral-3-14B-Instruct-2512",
            "Qwen3-Embedding-8B",
            "Whisper-Large-V3-Turbo",
        ],
        selected_models={
            "default_chat_model": "Ministral-3-14B-Instruct-2512",
            "default_embedding_model": "Qwen3-Embedding-8B",
            "default_whisper_model": "Whisper-Large-V3-Turbo",
            "default_reranking_model": None,
        },
    )

    base_urls = out["openai"]["api_base_urls"]
    keys = out["openai"]["api_keys"]
    configs = out["openai"]["api_configs"]
    mittwald_idx = base_urls.index("https://llm.aihosting.mittwald.de/v1")

    assert keys[mittwald_idx] == "mw-key"
    assert configs[str(mittwald_idx)]["enable"] is True
    assert "mittwald" in configs[str(mittwald_idx)]["tags"]
    assert "auto-discovered" in configs[str(mittwald_idx)]["tags"]
    assert configs[str(mittwald_idx)]["model_ids"] == [
        "Ministral-3-14B-Instruct-2512",
        "Qwen3-Embedding-8B",
        "Whisper-Large-V3-Turbo",
    ]

    assert out["audio"]["stt"]["engine"] == "openai"
    assert out["audio"]["stt"]["model"] == "Whisper-Large-V3-Turbo"
    assert out["audio"]["stt"]["openai"]["api_base_url"] == "https://llm.aihosting.mittwald.de/v1"
    assert out["audio"]["stt"]["openai"]["api_key"] == "mw-key"
    assert out["ui"]["default_models"] == "Ministral-3-14B-Instruct-2512"
    assert out["rag"]["embedding_engine"] == "openai"
    assert out["rag"]["embedding_model"] == "Qwen3-Embedding-8B"
    assert out["rag"]["openai_api_base_url"] == "https://llm.aihosting.mittwald.de/v1"
    assert out["rag"]["openai_api_key"] == "mw-key"


def test_merge_without_discovery_keeps_existing_model_ids(monkeypatch):
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_AUDIO_STT", False)
    monkeypatch.setattr(seed, "MITTWALD_SET_DEFAULT_MODEL", False)
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_RAG_EMBEDDING", False)

    config = {
        "openai": {
            "api_base_urls": ["https://llm.aihosting.mittwald.de/v1"],
            "api_keys": ["old-key"],
            "api_configs": {"0": {"model_ids": ["already-present"]}},
        }
    }

    out = seed.merge_mittwald_openai_config(
        config=config,
        base_url="https://llm.aihosting.mittwald.de/v1",
        api_key="new-key",
        discovered_model_ids=[],
        selected_models={
            "default_chat_model": None,
            "default_embedding_model": None,
            "default_whisper_model": None,
            "default_reranking_model": None,
        },
    )

    assert out["openai"]["api_keys"][0] == "new-key"
    assert out["openai"]["api_configs"]["0"]["model_ids"] == ["already-present"]


def test_merge_does_not_reindex_existing_openai_provider(monkeypatch):
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_AUDIO_STT", False)
    monkeypatch.setattr(seed, "MITTWALD_SET_DEFAULT_MODEL", False)
    monkeypatch.setattr(seed, "MITTWALD_CONFIGURE_RAG_EMBEDDING", False)

    config = {
        "openai": {
            "api_base_urls": ["https://api.openai.com/v1"],
            "api_keys": ["openai-key"],
            "api_configs": {"0": {"model_ids": ["gpt-4.1"], "tags": ["openai"]}},
        }
    }

    out = seed.merge_mittwald_openai_config(
        config=config,
        base_url="https://llm.aihosting.mittwald.de/v1",
        api_key="mw-key",
        discovered_model_ids=["Ministral-3-14B-Instruct-2512"],
        selected_models={
            "default_chat_model": "Ministral-3-14B-Instruct-2512",
            "default_embedding_model": None,
            "default_whisper_model": None,
            "default_reranking_model": None,
        },
    )

    assert out["openai"]["api_base_urls"] == [
        "https://api.openai.com/v1",
        "https://llm.aihosting.mittwald.de/v1",
    ]
    assert out["openai"]["api_keys"] == ["openai-key", "mw-key"]
    assert out["openai"]["api_configs"]["0"]["tags"] == ["openai"]
    assert out["openai"]["api_configs"]["1"]["model_ids"] == [
        "Ministral-3-14B-Instruct-2512"
    ]


def test_main_returns_error_when_api_key_required_and_missing(monkeypatch):
    monkeypatch.setattr(seed, "MITTWALD_API_KEY", "")
    monkeypatch.setattr(seed, "MITTWALD_REQUIRE_API_KEY", True)

    rc = seed.main()
    assert rc == 2


def test_main_falls_back_to_previous_cache_on_discovery_http_error(monkeypatch, tmp_path):
    cache_path = tmp_path / "mittwald-models-discovery.json"
    cache_path.write_text(
        json.dumps(
            {
                "models": ["Ministral-3-14B-Instruct-2512"],
                "classification": {
                    "default_chat_model": "Ministral-3-14B-Instruct-2512",
                    "default_embedding_model": None,
                    "default_whisper_model": None,
                    "default_reranking_model": None,
                },
            }
        )
    )

    writes = []

    def fake_write_json(path, data):
        writes.append((str(path), data))

    def fake_fetch(*_args, **_kwargs):
        raise HTTPError(
            url="https://llm.aihosting.mittwald.de/v1/models",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(seed, "MITTWALD_API_KEY", "mw-key")
    monkeypatch.setattr(seed, "MITTWALD_REQUIRE_API_KEY", False)
    monkeypatch.setattr(seed, "MITTWALD_STRICT_BOOTSTRAP", False)
    monkeypatch.setattr(seed, "DISCOVERY_CACHE_PATH", cache_path)
    monkeypatch.setattr(seed, "CONFIG_JSON_PATH", tmp_path / "config.json")
    monkeypatch.setattr(seed, "fetch_mittwald_models", fake_fetch)
    monkeypatch.setattr(seed, "load_existing_config_from_db", lambda _path: {})
    monkeypatch.setattr(seed, "merge_mittwald_openai_config", lambda **_kwargs: {})
    monkeypatch.setattr(seed, "write_json", fake_write_json)

    rc = seed.main()
    assert rc == 0
    assert writes[-1][1]["models"] == ["Ministral-3-14B-Instruct-2512"]


def test_main_returns_error_when_strict_bootstrap_and_discovery_fails(monkeypatch):
    def fake_fetch(*_args, **_kwargs):
        raise HTTPError(
            url="https://llm.aihosting.mittwald.de/v1/models",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(seed, "MITTWALD_API_KEY", "mw-key")
    monkeypatch.setattr(seed, "MITTWALD_REQUIRE_API_KEY", False)
    monkeypatch.setattr(seed, "MITTWALD_STRICT_BOOTSTRAP", True)
    monkeypatch.setattr(seed, "fetch_mittwald_models", fake_fetch)

    rc = seed.main()
    assert rc == 3
