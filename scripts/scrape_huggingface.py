#!/usr/bin/env python3
"""
Scrapes recommended settings from Hugging Face for Open WebUI models.
Expects HUGGINGFACE_TOKEN env var for authentication if needed.
"""

import json
import os
import re
import sys
from typing import Dict, Any, Optional

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}", file=sys.stderr)
    print("Install with: pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

# Default recommended settings for popular model families
DEFAULT_SETTINGS = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repetition_penalty": 1.1,
    "max_tokens": 2048,
}

# Known model settings from Hugging Face documentation
MODEL_SETTINGS = {
    "llama": {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "repetition_penalty": 1.1,
        "max_tokens": 4096,
    },
    "mistral": {
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 40,
        "repetition_penalty": 1.05,
        "max_tokens": 8192,
    },
    "qwen": {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 50,
        "repetition_penalty": 1.0,
        "max_tokens": 32768,
    },
    "gemma": {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "repetition_penalty": 1.0,
        "max_tokens": 8192,
    },
}

HF_API_BASE = "https://huggingface.co/api"


def get_model_info(model_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch model info from Hugging Face API."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            f"{HF_API_BASE}/models/{model_id}", headers=headers, timeout=30
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching {model_id}: {e}", file=sys.stderr)
        return {}


def scrape_model_readme(model_id: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Scrape model README for recommended settings."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            f"https://huggingface.co/{model_id}/raw/main/README.md",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        readme = response.text

        # Look for temperature, top_p, top_k, repetition_penalty in README
        settings = {}

        # Common patterns for settings in README
        patterns = {
            "temperature": r"temperature[:\s=]+([0-9.]+)",
            "top_p": r"top_p[:\s=]+([0-9.]+)",
            "top_k": r"top_k[:\s=]+(\d+)",
            "repetition_penalty": r"repetition_penalty[:\s=]+([0-9.]+)",
            "max_tokens": r"max[_\s]?tokens?[:\s=]+(\d+)",
        }

        for key, pattern in patterns.items():
            matches = re.findall(pattern, readme, re.IGNORECASE)
            if matches:
                try:
                    value = float(matches[0])
                    settings[key] = value
                except ValueError:
                    continue

        return settings

    except Exception as e:
        print(f"Error scraping {model_id} README: {e}", file=sys.stderr)
        return {}


def determine_settings(model_family: Optional[str] = None) -> Dict[str, float]:
    """Determine best settings based on model family."""
    if model_family and model_family.lower() in MODEL_SETTINGS:
        return MODEL_SETTINGS[model_family.lower()].copy()
    return DEFAULT_SETTINGS.copy()


def main():
    """Main scraping logic."""
    token = os.getenv("HUGGINGFACE_TOKEN")

    # Default to general LLM settings
    settings = DEFAULT_SETTINGS.copy()

    # Try to scrape from Open WebUI's Hugging Face space
    try:
        model_info = get_model_info("open-webui/open-webui", token or "")

        # Check if there's info about default models
        if model_info:
            card_data = model_info.get("cardData", {})
            if "default_params" in card_data:
                settings.update(card_data["default_params"])
    except Exception as e:
        print(f"Could not fetch Open WebUI model info: {e}", file=sys.stderr)

    # Scrape README for additional settings
    readme_settings = scrape_model_readme("open-webui/open-webui", token or "")
    settings.update(readme_settings)

    # Output as JSON
    output = {
        "temperature": settings.get("temperature", DEFAULT_SETTINGS["temperature"]),
        "top_p": settings.get("top_p", DEFAULT_SETTINGS["top_p"]),
        "top_k": settings.get("top_k", DEFAULT_SETTINGS["top_k"]),
        "repetition_penalty": settings.get(
            "repetition_penalty", DEFAULT_SETTINGS["repetition_penalty"]
        ),
        "max_tokens": settings.get("max_tokens", DEFAULT_SETTINGS["max_tokens"]),
        "source": "huggingface_scrape",
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
