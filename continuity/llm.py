"""
continuity/llm.py
-----------------
Unified LLM interface supporting Gemini and OpenAI-compatible endpoints.
"""

import os
import re
import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Any, Dict, Union, List
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Base paths relative to this file
CONTINUITY_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CONTINUITY_DIR / "config.yaml"
CACHE_PATH = CONTINUITY_DIR / "data" / "cache.json"


def _load_config() -> Dict[str, Any]:
    """Load LLM configuration from config.yaml."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def _compute_prompt_hash(prompt: str) -> str:
    """Generate SHA-256 hash of the prompt string."""
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _load_cache() -> Dict[str, Any]:
    """Load cache dictionary from data/cache.json."""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read cache at {CACHE_PATH}: {e}")
    return {}


def _save_cache(cache_data: Dict[str, Any]) -> None:
    """Save cache dictionary to data/cache.json."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save cache at {CACHE_PATH}: {e}")


def _strip_json_fences(text: str) -> str:
    """Strip markdown ```json code fences from LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _call_gemini_api(model: str, api_key: str, prompt: str, temperature: float = 0.0) -> str:
    """Execute completion call via Gemini REST API."""
    clean_model = model.replace("google/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key.strip()}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates.")
    return candidates[0]["content"]["parts"][0]["text"]


def _call_openai_compatible_api(
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
    temperature: float = 0.0,
) -> str:
    """Execute completion call via OpenAI-compatible endpoint."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm(prompt: str, json_mode: bool = True) -> Union[Dict[str, Any], List[Any], str]:
    """
    Executes an LLM completion with prompt-hash disk caching and 1 retry on failure.
    
    Args:
        prompt: Prompt string to send to LLM.
        json_mode: If True, strips markdown fences and returns parsed JSON.
        
    Returns:
        Parsed JSON object if json_mode=True, else raw text string.
    """
    prompt_hash = _compute_prompt_hash(prompt)
    cache = _load_cache()

    # 1. Check data/cache.json
    if prompt_hash in cache:
        raw_text = cache[prompt_hash]
        if json_mode:
            clean_text = _strip_json_fences(raw_text)
            return json.loads(clean_text)
        return raw_text

    # 2. Read config
    cfg = _load_config()
    provider = str(cfg.get("provider", "openai")).lower()
    model = str(cfg.get("model", "nvidia/nemotron-3-ultra-550b-a55b:free"))
    api_key_env = str(cfg.get("api_key_env", "OPENROUTER_API_KEY"))
    base_url = str(cfg.get("base_url", "https://openrouter.ai/api/v1"))
    temperature = float(cfg.get("temperature", 0.0))

    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ValueError(f"Environment variable '{api_key_env}' is not set or empty.")

    # 3. Call API with 1 retry on failure
    last_error: Exception = RuntimeError("Unknown error")
    raw_response: str = ""

    for attempt in range(2):
        try:
            if provider == "gemini":
                raw_response = _call_gemini_api(model, api_key, prompt, temperature)
            else:
                raw_response = _call_openai_compatible_api(base_url, model, api_key, prompt, temperature)
            break
        except Exception as e:
            last_error = e
            logger.warning(f"LLM request attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                time.sleep(1.0)
            else:
                raise last_error

    # 4. Save to data/cache.json
    cache[prompt_hash] = raw_response
    _save_cache(cache)

    # 5. Return parsed JSON or raw string
    if json_mode:
        clean_text = _strip_json_fences(raw_response)
        return json.loads(clean_text)
    return raw_response
