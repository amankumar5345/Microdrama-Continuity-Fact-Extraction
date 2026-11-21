"""
test_step1.py
-------------
Verifies Step 1:
- Config loading
- Single call_llm(prompt) function
- Disk caching mechanism (SHA-256 hash key, zero-cost repeated calls)
"""

import time
from src.llm import load_config, call_llm, _compute_cache_key

def main():
    print("=== Testing Step 1: LLM Engine & Disk Cache ===")
    
    # 1. Test Config Loading
    cfg = load_config()
    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model"]
    temp = cfg["llm"]["temperature"]
    print(f"[OK] Config loaded: Provider='{provider}', Model='{model}', Temperature={temp}")
    assert temp == 0.0, "Temperature must be strictly 0.0"

    # 2. Test Cache Key Calculation
    test_prompt = "Say hello in one word."
    k1 = _compute_cache_key(provider, model, temp, test_prompt)
    k2 = _compute_cache_key(provider, model, temp, test_prompt)
    assert k1 == k2, "Cache key calculation must be deterministic"
    print(f"[OK] Deterministic SHA-256 cache key: {k1[:16]}...")

    # 3. Test call_llm & Disk Cache Hit
    print(f"\nMaking first call_llm() request (live API call)...")
    t0 = time.time()
    resp1 = call_llm(test_prompt)
    t1 = time.time() - t0
    print(f"First Call Duration: {t1:.2f}s | Response: {resp1.strip()[:40]}")

    print(f"\nMaking second call_llm() request (must be disk cache hit)...")
    t0 = time.time()
    resp2 = call_llm(test_prompt)
    t2 = time.time() - t0
    print(f"Second Call Duration: {t2:.4f}s (Cache Hit!) | Response: {resp2.strip()[:40]}")

    assert resp1 == resp2, "Cached response must match original response exactly"
    assert t2 < 0.1, "Cache hit must be near instantaneous"
    print("\n[SUCCESS] Step 1 verification passed flawlessly!")

if __name__ == "__main__":
    main()
