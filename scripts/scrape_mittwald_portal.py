#!/usr/bin/env python3
"""
Scrapes Mittwald AI Developer Portal for model changes.
Expects MITTWALD_API_TOKEN env var for authentication.
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}", file=sys.stderr)
    print("Install with: pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)


class MittwaldPortalScraper:
    """Scraper for Mittwald AI Developer Portal."""

    def __init__(self, base_url: str, api_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.getenv("MITTWALD_API_TOKEN")
        self.session = requests.Session()

        if self.api_token:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                }
            )

    def scrape_model_table(self) -> List[Dict[str, Any]]:
        """
        Scrape model information from the developer portal.
        This is a placeholder - actual implementation depends on the portal structure.
        """
        models = []

        try:
            # Try API endpoint first (preferred)
            response = self.session.get(f"{self.base_url}/api/models", timeout=30)

            if response.status_code == 200:
                models = response.json()
                return self._normalize_models(models)

        except Exception as e:
            print(f"API fetch failed: {e}, trying HTML scrape...", file=sys.stderr)

        try:
            # Fallback to HTML scraping
            response = self.session.get(f"{self.base_url}/models", timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Look for model tables (adjust selectors based on actual HTML)
            table = soup.find("table", {"class": "models-table"}) or soup.find("table")

            if table:
                headers = [th.get_text(strip=True) for th in table.find_all("th")]

                for row in table.find_all("tr")[1:]:  # Skip header
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]

                    if len(cols) >= 2:
                        model_info = dict(zip(headers, cols))
                        model_info["scraped_at"] = datetime.now(
                            timezone.utc
                        ).isoformat()
                        models.append(model_info)

        except Exception as e:
            print(f"HTML scrape failed: {e}", file=sys.stderr)

        return models

    def scrape_model_details(self, model_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific model."""
        try:
            response = self.session.get(
                f"{self.base_url}/api/models/{model_id}", timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching model {model_id}: {e}", file=sys.stderr)
            return {}

    def _normalize_models(self, models: List[Dict]) -> List[Dict[str, Any]]:
        """Normalize model data to consistent format."""
        normalized = []

        for model in models:
            # Ensure required fields exist
            norm = {
                "id": model.get("id")
                or model.get("model_id")
                or model.get("name", "unknown"),
                "name": model.get("name") or model.get("display_name", "Unknown"),
                "version": model.get("version", "latest"),
                "status": model.get("status", "active"),
                "parameters": model.get("parameters", {}),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }

            # Extract parameters if available
            if "params" in model:
                norm["parameters"].update(model["params"])
            if "recommended_settings" in model:
                norm["parameters"].update(model["recommended_settings"])

            normalized.append(norm)

        return normalized

    def check_for_changes(self, previous_models: List[Dict]) -> Dict[str, Any]:
        """Compare current models with previous state to detect changes."""
        current = self.scrape_model_table()

        changes = {"added": [], "removed": [], "modified": [], "has_changes": False}

        current_ids = {m["id"] for m in current}
        previous_ids = {m["id"] for m in previous_models}

        # Detect additions
        changes["added"] = [m for m in current if m["id"] not in previous_ids]

        # Detect removals
        changes["removed"] = [m for m in previous_models if m["id"] not in current_ids]

        # Detect modifications
        for prev in previous_models:
            for curr in current:
                if prev["id"] == curr["id"] and prev != curr:
                    changes["modified"].append(
                        {"id": curr["id"], "previous": prev, "current": curr}
                    )

        changes["has_changes"] = any(
            [changes["added"], changes["removed"], changes["modified"]]
        )

        changes["scraped_at"] = datetime.now(timezone.utc).isoformat()

        return changes


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Scrape Mittwald AI Portal")
    parser.add_argument("portal_url", help="Mittwald Developer Portal URL")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    scraper = MittwaldPortalScraper(args.portal_url)

    # Load previous state for comparison
    prev_file = ".cache/models.json"
    previous = []

    if os.path.exists(prev_file):
        try:
            with open(prev_file, "r") as f:
                previous = json.load(f)
        except Exception:
            pass

    # Scrape and check for changes
    changes = scraper.check_for_changes(previous)
    models = scraper.scrape_model_table()

    output = {
        "models": models,
        "changes": changes,
        "metadata": {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "portal_url": args.portal_url,
            "model_count": len(models),
        },
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Output written to {args.output}")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
