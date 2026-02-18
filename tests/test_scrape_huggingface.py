import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "scrape_huggingface.py"

spec = importlib.util.spec_from_file_location("scrape_hf", MODULE_PATH)
hf = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(hf)


class FakeResponse:
    def __init__(self, *, text="", json_data=None, status_code=200):
        self.text = text
        self._json_data = json_data if json_data is not None else {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._json_data


def test_get_hf_token_prefers_hf_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf-primary")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf-secondary")
    assert hf.get_hf_token() == "hf-primary"


def test_determine_fallback_settings_uses_family_defaults():
    settings = hf.determine_fallback_settings("Ministral-3-14B-Instruct-2512")
    assert settings["temperature"] == 0.1
    assert settings["top_p"] == 0.5


def test_extract_readme_hyperparameters_extracts_multiple_values():
    content = """
    temperature: 0.15
    top_p=0.6
    top_k: 30
    repetition_penalty: 1.07
    max_new_tokens: 2048
    min_p: 0.01
    """

    settings = hf.extract_readme_hyperparameters(content)

    assert settings["temperature"] == 0.15
    assert settings["top_p"] == 0.6
    assert settings["top_k"] == 30
    assert settings["repetition_penalty"] == 1.07
    assert settings["max_tokens"] == 2048
    assert settings["min_p"] == 0.01


def test_pick_best_hf_model_id_prefers_exact_normalized_match():
    candidates = [
        {"id": "mistralai/Ministral-8B-Instruct-2410"},
        {"id": "other-org/model"},
    ]
    picked = hf.pick_best_hf_model_id("Ministral-8B-Instruct-2410", candidates)
    assert picked == "mistralai/Ministral-8B-Instruct-2410"


def test_extract_model_names_from_payload_handles_models_object():
    payload = {
        "models": [
            {"name": "Ministral-3-14B-Instruct-2512"},
            {"id": "Qwen3-Embedding-8B"},
            {"model_id": "Whisper-Large-V3-Turbo"},
        ]
    }
    names = hf.extract_model_names_from_payload(payload)
    assert names == [
        "Ministral-3-14B-Instruct-2512",
        "Qwen3-Embedding-8B",
        "Whisper-Large-V3-Turbo",
    ]


def test_main_outputs_per_model_settings(monkeypatch, tmp_path, capsys):
    models_file = tmp_path / "models.json"
    models_file.write_text(
        json.dumps(
            {
                "models": [
                    {"name": "Ministral-3-14B-Instruct-2512"},
                    {"name": "Qwen3-Embedding-8B"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("HUGGINGFACE_TARGET_MODEL", "Ministral-3-14B-Instruct-2512")
    monkeypatch.setattr(
        hf,
        "scrape_model_hyperparameters",
        lambda model_name, _token: {
            "model_name": model_name,
            "hf_model_id": f"org/{model_name}",
            "source": "huggingface_scrape",
            "hyperparameters": {
                "temperature": 0.1 if "Ministral" in model_name else 0.2,
                "top_p": 0.5,
                "top_k": 10,
                "repetition_penalty": 1.0,
                "max_tokens": 4096,
            },
            "generation_hyperparameters": {"temperature": 0.2},
            "card_hyperparameters": {},
            "readme_hyperparameters": {},
            "chat_template": "{{prompt}}",
            "generation_config": {"temperature": 0.1},
        },
    )

    monkeypatch.setattr("sys.argv", ["scrape_huggingface.py", "--models-file", str(models_file)])
    hf.main()

    output = json.loads(capsys.readouterr().out)

    assert output["selected_model"] == "Ministral-3-14B-Instruct-2512"
    assert output["temperature"] == 0.1
    assert output["source"] == "huggingface_scrape"
    assert "Ministral-3-14B-Instruct-2512" in output["models"]
    assert "Qwen3-Embedding-8B" in output["models"]


def test_scrape_model_hyperparameters_merges_generation_card_readme(monkeypatch):
    monkeypatch.setattr(
        hf, "resolve_hf_model_id", lambda model_name, token: "org/model-a"
    )
    monkeypatch.setattr(
        hf,
        "get_model_info",
        lambda model_id, token: {
            "cardData": {"default_params": {"temperature": 0.15}},
            "config": {
                "generation_config": {"top_p": 0.55, "max_new_tokens": 1024},
                "chat_template": "{{prompt}}",
            },
        },
    )
    monkeypatch.setattr(
        hf,
        "scrape_model_readme",
        lambda model_id, token: "top_p: 0.5\ntop_k: 12\n",
    )

    result = hf.scrape_model_hyperparameters("Ministral-3-14B-Instruct-2512", "token")

    assert result["hf_model_id"] == "org/model-a"
    assert result["chat_template"] == "{{prompt}}"
    assert result["generation_hyperparameters"]["max_tokens"] == 1024
    # README should override generation_config for top_p
    assert result["hyperparameters"]["top_p"] == 0.5
    # Card should override fallback for temperature
    assert result["hyperparameters"]["temperature"] == 0.15
    assert result["hyperparameters"]["top_k"] == 12
