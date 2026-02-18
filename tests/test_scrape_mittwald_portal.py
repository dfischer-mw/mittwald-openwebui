import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "scrape_mittwald_portal.py"


spec = importlib.util.spec_from_file_location("scrape_mittwald", MODULE_PATH)
mittwald = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mittwald)


class FakeResponse:
    def __init__(self, *, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._json_data


def test_normalize_models_handles_varied_field_names():
    scraper = mittwald.MittwaldPortalScraper("https://example.com")
    models = [
        {
            "model_id": "model-a",
            "display_name": "Model A",
            "status": "active",
            "recommended_settings": {"temperature": 0.7},
        }
    ]

    out = scraper._normalize_models(models)
    assert len(out) == 1
    assert out[0]["id"] == "model-a"
    assert out[0]["name"] == "Model A"
    assert out[0]["parameters"]["temperature"] == 0.7


def test_scrape_model_table_uses_api_when_available(monkeypatch):
    scraper = mittwald.MittwaldPortalScraper("https://example.com")

    def _fake_get(url, timeout=30):
        assert url.endswith("/api/models")
        return FakeResponse(
            status_code=200,
            json_data=[{"id": "m1", "name": "Model 1", "parameters": {"top_p": 0.9}}],
        )

    monkeypatch.setattr(scraper.session, "get", _fake_get)

    models = scraper.scrape_model_table()
    assert len(models) == 1
    assert models[0]["id"] == "m1"
    assert models[0]["parameters"]["top_p"] == 0.9


def test_scrape_model_table_falls_back_to_html(monkeypatch):
    scraper = mittwald.MittwaldPortalScraper("https://example.com")
    calls = {"count": 0}

    html = """
    <html>
      <body>
        <table class=\"models-table\">
          <tr><th>id</th><th>name</th></tr>
          <tr><td>m2</td><td>Model 2</td></tr>
        </table>
      </body>
    </html>
    """

    def _fake_get(url, timeout=30):
        calls["count"] += 1
        if calls["count"] == 1:
            return FakeResponse(status_code=404, json_data={})
        return FakeResponse(status_code=200, text=html)

    monkeypatch.setattr(scraper.session, "get", _fake_get)

    models = scraper.scrape_model_table()
    assert len(models) == 1
    assert models[0]["id"] == "m2"
    assert models[0]["name"] == "Model 2"


def test_check_for_changes_detects_added_removed_and_modified(monkeypatch):
    scraper = mittwald.MittwaldPortalScraper("https://example.com")

    current = [
        {"id": "keep", "name": "Keep", "status": "active"},
        {"id": "new", "name": "New", "status": "active"},
    ]
    previous = [
        {"id": "keep", "name": "Keep", "status": "inactive"},
        {"id": "old", "name": "Old", "status": "active"},
    ]

    monkeypatch.setattr(scraper, "scrape_model_table", lambda: current)

    changes = scraper.check_for_changes(previous)

    assert changes["has_changes"] is True
    assert len(changes["added"]) == 1
    assert len(changes["removed"]) == 1
    assert len(changes["modified"]) == 1
    assert changes["added"][0]["id"] == "new"
    assert changes["removed"][0]["id"] == "old"
    assert changes["modified"][0]["id"] == "keep"
