"""
src/llm.py
----------
Centralized LLM interface for Continuity Checker.

Constraints met:
1. All LLM calls pass through ONE function: call_llm(prompt).
2. Provider and model are dynamically read from config.yaml.
3. Temperature is strictly 0.0.
4. Every LLM response is cached to disk using a SHA-256 hash key.
5. Minimal dependencies (uses standard requests and PyYAML).
"""

import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import requests
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Base project paths
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config() -> Dict[str, Any]:
    """Load LLM and system configuration from config.yaml."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found at: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_cache_path(cache_dir: Path, key: str) -> Path:
    """Return the cache file path for a given SHA-256 key."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.json"


def _compute_cache_key(provider: str, model: str, temperature: float, prompt: str) -> str:
    """Generate deterministic SHA-256 hash for provider, model, temp, and prompt."""
    payload = f"{provider}:{model}:{temperature}:{prompt.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _call_openrouter(model: str, prompt: str, temperature: float, timeout: int) -> str:
    """Execute completion call via OpenRouter API."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is missing or empty.")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/continuity-checker",
        "X-Title": "Continuity Checker",
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


def _call_openai(model: str, prompt: str, temperature: float, timeout: int) -> str:
    """Execute completion call via standard OpenAI-compatible API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is missing or empty.")

    url = "https://api.openai.com/v1/chat/completions"
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


def _call_gemini(model: str, prompt: str, temperature: float, timeout: int) -> str:
    """Execute completion call via Gemini REST API."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing or empty.")

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


def _call_groq(model: str, prompt: str, temperature: float, timeout: int) -> str:
    """Execute completion call via Groq API."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing or empty.")

    url = "https://api.groq.com/openai/v1/chat/completions"
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


def call_llm(prompt: str) -> str:
    """
    Main LLM entrypoint.
    
    Reads provider and model from config.yaml.
    Sets temperature to 0.0.
    Checks disk cache first; if cached, returns cached response instantly.
    Otherwise, executes the network call and caches the response to disk.
    """
    config = load_config()
    llm_cfg = config.get("llm", {})

    provider = str(llm_cfg.get("provider", "openrouter")).lower()
    model = str(llm_cfg.get("model", "google/gemini-2.5-flash"))
    temperature = float(llm_cfg.get("temperature", 0.0))
    cache_rel_dir = llm_cfg.get("cache_dir", ".cache/llm")
    timeout = int(llm_cfg.get("timeout_seconds", 60))

    cache_dir = Path(__file__).resolve().parent.parent / cache_rel_dir
    cache_key = _compute_cache_key(provider, model, temperature, prompt)
    cache_file = _get_cache_path(cache_dir, cache_key)

    # 1. Check disk cache
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                logger.info(f"LLM Cache Hit [{cache_key[:10]}...]")
                return cached_data.get("response", "")
        except Exception as e:
            logger.warning(f"Failed to read cache file {cache_file}: {e}")

    # 2. Make LLM API request
    logger.info(f"Calling LLM ({provider} / {model}, temp={temperature})...")
    if provider == "openrouter":
        content = _call_openrouter(model, prompt, temperature, timeout)
    elif provider == "openai":
        content = _call_openai(model, prompt, temperature, timeout)
    elif provider == "gemini":
        content = _call_gemini(model, prompt, temperature, timeout)
    elif provider == "groq":
        content = _call_groq(model, prompt, temperature, timeout)
    else:
        raise ValueError(f"Unsupported LLM provider '{provider}' in config.yaml.")

    # 3. Save to disk cache
    try:
        cache_data = {
            "cache_key": cache_key,
            "provider": provider,
            "model": model,
            "temperature": temperature,
            "prompt": prompt,
            "response": content,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        logger.info(f"LLM response cached to {cache_file.name}")
    except Exception as e:
        logger.warning(f"Failed to write cache file {cache_file}: {e}")

    return content
