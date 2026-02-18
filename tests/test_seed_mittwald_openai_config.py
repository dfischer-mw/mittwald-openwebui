import importlib.util
from pathlib import Path


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
    ]

    classified = seed.classify_models(model_ids)

    assert classified["default_chat_model"] == "Ministral-3-14B-Instruct-2512"
    assert classified["default_embedding_model"] == "Qwen3-Embedding-8B"
    assert classified["default_whisper_model"] == "Whisper-Large-V3-Turbo"


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
    )

    base_urls = out["openai"]["api_base_urls"]
    keys = out["openai"]["api_keys"]
    configs = out["openai"]["api_configs"]

    assert base_urls[0] == "https://llm.aihosting.mittwald.de/v1"
    assert keys[0] == "mw-key"
    assert configs["0"]["enable"] is True
    assert "mittwald" in configs["0"]["tags"]
    assert "auto-discovered" in configs["0"]["tags"]
    assert configs["0"]["model_ids"] == [
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
    )

    assert out["openai"]["api_keys"][0] == "new-key"
    assert out["openai"]["api_configs"]["0"]["model_ids"] == ["already-present"]
