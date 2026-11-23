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
    """Legacy prompt-only cache key (kept so existing caches stay usable)."""
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _compute_cache_key(cfg: Dict[str, Any], prompt: str) -> str:
    """
    Generate a SHA-256 key for the full request identity.

    Including model/provider/base_url/temperature means switching models can no
    longer silently replay answers produced by a different model.
    """
    payload = "|".join(
        [
            str(cfg.get("provider", "")).lower().strip(),
            str(cfg.get("model", "")).strip(),
            str(cfg.get("base_url", "")).strip(),
            str(cfg.get("temperature", 0.0)),
            prompt.strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache() -> Dict[str, Any]:
    """Load cache dictionary from data/cache.json."""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("Cache at %s is not a JSON object; ignoring it.", CACHE_PATH)
        except Exception as e:
            logger.warning(f"Failed to read cache at {CACHE_PATH}: {e}")
            # Keep the damaged file for inspection instead of overwriting it.
            try:
                backup = CACHE_PATH.with_suffix(".corrupt.json")
                CACHE_PATH.replace(backup)
                logger.warning("Moved unreadable cache to %s", backup)
            except Exception:
                pass
    return {}


def _save_cache(cache_data: Dict[str, Any]) -> None:
    """Save cache dictionary to data/cache.json."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = CACHE_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(CACHE_PATH)
    except Exception as e:
        logger.warning(f"Failed to save cache at {CACHE_PATH}: {e}")


def _save_cache_entry(key: str, raw_response: str) -> None:
    """Reload the on-disk cache before adding one entry (safe for concurrent runs)."""
    cache = _load_cache()
    cache[key] = raw_response
    _save_cache(cache)


def _strip_json_fences(text: str) -> str:
    """Strip markdown ```json code fences from LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _call_gemini_api(
    model: str,
    api_key: str,
    prompt: str,
    temperature: float = 0.0,
    timeout: int = 60,
) -> str:
    """Execute completion call via Gemini REST API."""
    clean_model = model.replace("google/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key.strip()}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
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
    timeout: int = 60,
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
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm(prompt: str, json_mode: bool = True) -> Union[Dict[str, Any], List[Any], str]:
    """
    Execute an LLM completion with disk caching and one retry.

    Cache keys include provider, model, base URL, and temperature. Legacy
    prompt-only entries are still accepted (and migrated to the new key), so
    existing caches keep working while future model switches stay isolated.

    Args:
        prompt: Prompt string to send to the LLM.
        json_mode: If True, strip markdown fences and return parsed JSON.

    Returns:
        Parsed JSON when ``json_mode=True``, otherwise the raw text.

    Raises:
        ValueError: If the API key is missing or JSON parsing fails twice.
        Exception: The last network/API error after the retry.
    """
    cfg = _load_config()
    provider = str(cfg.get("provider", "openai")).lower()
    model = str(cfg.get("model", "nvidia/nemotron-3-ultra-550b-a55b:free"))
    api_key_env = str(cfg.get("api_key_env", "OPENROUTER_API_KEY"))
    base_url = str(cfg.get("base_url", "https://openrouter.ai/api/v1"))
    temperature = float(cfg.get("temperature", 0.0))
    timeout = int(cfg.get("timeout_seconds", 60))

    cache = _load_cache()
    cache_key = _compute_cache_key(cfg, prompt)
    legacy_key = _compute_prompt_hash(prompt)

    # 1. Check the current key, then the legacy prompt-only key.
    cached_raw = cache.get(cache_key)
    if cached_raw is None and legacy_key in cache:
        cached_raw = cache[legacy_key]
        try:
            cache[cache_key] = cached_raw
            _save_cache(cache)
        except Exception:
            pass
        logger.info("Migrated legacy prompt-only cache entry to a model-scoped key.")

    if cached_raw is not None:
        if json_mode:
            try:
                return json.loads(_strip_json_fences(cached_raw))
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Cached response %s is not valid JSON; refreshing from the API.",
                    cache_key[:10],
                )
                cache.pop(cache_key, None)
                cache.pop(legacy_key, None)
                _save_cache(cache)
        else:
            return cached_raw

    # 2. Read the API key.
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ValueError(f"Environment variable '{api_key_env}' is not set or empty.")

    # 3. Call the API with one retry. JSON validation happens before caching,
    #    so a malformed response is never stored as a permanent bad cache entry.
    last_error: Exception = RuntimeError("Unknown error")
    for attempt in range(2):
        try:
            if provider == "gemini":
                raw_response = _call_gemini_api(
                    model, api_key, prompt, temperature, timeout
                )
            else:
                raw_response = _call_openai_compatible_api(
                    base_url, model, api_key, prompt, temperature, timeout
                )

            if not str(raw_response or "").strip():
                raise ValueError("LLM returned an empty response.")

            if json_mode:
                parsed = json.loads(_strip_json_fences(raw_response))
                _save_cache_entry(cache_key, raw_response)
                return parsed

            _save_cache_entry(cache_key, raw_response)
            return raw_response
        except Exception as e:
            last_error = e
            logger.warning(f"LLM request attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                time.sleep(1.0)

    raise last_error
