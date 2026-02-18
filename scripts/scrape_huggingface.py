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
DEFAULT_TARGET_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def _debug_enabled() -> bool:
    return os.getenv("HF_SCRAPER_DEBUG", "").lower() in {"1", "true", "yes"}


def _debug(msg: str) -> None:
    if _debug_enabled():
        print(msg, file=sys.stderr)


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
        _debug(f"Error fetching {model_id}: {e}")
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
        _debug(f"Error scraping {model_id} README: {e}")
        return {}


def determine_settings(model_family: Optional[str] = None) -> Dict[str, float]:
    """Determine best settings based on model family."""
    if model_family and model_family.lower() in MODEL_SETTINGS:
        return MODEL_SETTINGS[model_family.lower()].copy()
    return DEFAULT_SETTINGS.copy()


def infer_model_family(model_id: str) -> Optional[str]:
    """Infer model family from model id for fallback defaults."""
    lid = model_id.lower()
    for family in MODEL_SETTINGS:
        if family in lid:
            return family
    return None


def main():
    """Main scraping logic."""
    token = os.getenv("HUGGINGFACE_TOKEN", "").strip()
    target_model = os.getenv("HUGGINGFACE_TARGET_MODEL", DEFAULT_TARGET_MODEL).strip()
    configured_family = os.getenv("HUGGINGFACE_MODEL_FAMILY", "").strip()
    model_family = configured_family or infer_model_family(target_model)

    settings = determine_settings(model_family)
    source = "default_settings"

    # Avoid unauthenticated calls in CI to prevent noisy 401/403 failures.
    if token:
        model_info = get_model_info(target_model, token)
        readme_settings = scrape_model_readme(target_model, token)

        if model_info:
            card_data = model_info.get("cardData", {})
            if "default_params" in card_data:
                settings.update(card_data["default_params"])
        settings.update(readme_settings)
        source = "huggingface_scrape" if (model_info or readme_settings) else "fallback"
    else:
        _debug("HUGGINGFACE_TOKEN not set; using default settings.")

    # Output as JSON
    output = {
        "temperature": settings.get("temperature", DEFAULT_SETTINGS["temperature"]),
        "top_p": settings.get("top_p", DEFAULT_SETTINGS["top_p"]),
        "top_k": settings.get("top_k", DEFAULT_SETTINGS["top_k"]),
        "repetition_penalty": settings.get(
            "repetition_penalty", DEFAULT_SETTINGS["repetition_penalty"]
        ),
        "max_tokens": settings.get("max_tokens", DEFAULT_SETTINGS["max_tokens"]),
        "source": source,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
