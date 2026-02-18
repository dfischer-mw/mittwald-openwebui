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


def test_determine_settings_uses_known_family_defaults():
    settings = hf.determine_settings("mistral")
    assert settings["temperature"] == 0.7
    assert settings["top_p"] == 0.95
    assert settings["max_tokens"] == 8192


def test_get_model_info_returns_empty_on_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(hf.requests, "get", _raise)
    assert hf.get_model_info("open-webui/open-webui") == {}


def test_scrape_model_readme_extracts_generation_params(monkeypatch):
    content = """
    temperature: 0.65
    top_p=0.91
    top_k: 48
    repetition_penalty: 1.08
    max_tokens: 4096
    """

    def _fake_get(*args, **kwargs):
        return FakeResponse(text=content)

    monkeypatch.setattr(hf.requests, "get", _fake_get)

    settings = hf.scrape_model_readme("open-webui/open-webui")

    assert settings["temperature"] == 0.65
    assert settings["top_p"] == 0.91
    assert settings["top_k"] == 48.0
    assert settings["repetition_penalty"] == 1.08
    assert settings["max_tokens"] == 4096.0


def test_main_prints_json_with_scraped_overrides(monkeypatch, capsys):
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "test-token")
    monkeypatch.setattr(hf, "get_model_info", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        hf,
        "scrape_model_readme",
        lambda *_args, **_kwargs: {"temperature": 0.42, "top_p": 0.88},
    )

    hf.main()
    output = json.loads(capsys.readouterr().out)

    assert output["temperature"] == 0.42
    assert output["top_p"] == 0.88
    assert output["source"] == "huggingface_scrape"


def test_main_without_token_uses_default_source(monkeypatch, capsys):
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.setenv("HUGGINGFACE_MODEL_FAMILY", "llama")

    hf.main()
    output = json.loads(capsys.readouterr().out)

    assert output["temperature"] == 0.7
    assert output["top_p"] == 0.9
    assert output["source"] == "default_settings"
