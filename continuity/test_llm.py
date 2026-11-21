"""
continuity/test_llm.py
----------------------
Tests call_llm() with a trivial prompt:
- Verifies reading config.yaml
- Verifies JSON parsing and ```json fence stripping
- Verifies caching in data/cache.json
"""

import time
from pathlib import Path
from continuity.llm import call_llm, CACHE_PATH

def test_trivial_call():
    print("=== Testing call_llm(prompt, json_mode=True) ===")
    
    prompt = 'Return a valid JSON object with keys "status" equal to "ok" and "count" equal to 42. Output JSON only.'
    
    # 1. Live call (or cache read if present)
    t0 = time.time()
    result1 = call_llm(prompt, json_mode=True)
    d1 = time.time() - t0
    
    print(f"Call 1 duration: {d1:.2f}s")
    print(f"Call 1 result:   {result1} (Type: {type(result1).__name__})")
    
    assert isinstance(result1, dict), f"Expected dict, got {type(result1)}"
    assert result1.get("status") == "ok", f"Expected status 'ok', got {result1.get('status')}"
    assert result1.get("count") == 42, f"Expected count 42, got {result1.get('count')}"
    
    # 2. Verify data/cache.json was updated
    assert CACHE_PATH.exists(), f"Cache file {CACHE_PATH} must exist"
    print(f"[OK] Cache verified at {CACHE_PATH}")
    
    # 3. Second call (must hit data/cache.json instantly)
    t0 = time.time()
    result2 = call_llm(prompt, json_mode=True)
    d2 = time.time() - t0
    
    print(f"Call 2 duration: {d2:.5f}s (Cache Hit!)")
    assert result1 == result2, "Cached output must match original output"
    assert d2 < 0.05, "Cache hit must be instantaneous"
    print(f"[OK] Cache hit verified in {d2:.5f}s")
    
    print("\n[SUCCESS] call_llm test passed flawlessly!")

if __name__ == "__main__":
    test_trivial_call()
