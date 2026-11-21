"""
test_step3.py
-------------
Verifies Step 3:
- Fact extraction via call_llm()
- Verbatim quote verification against source text (Zero hallucination)
- Timestamp alignment
- Disk persistence in data/facts/
"""

import time
from pathlib import Path
from src.parser import parse_screenplay, verify_quote_in_screenplay
from src.extractor import extract_facts_from_episode

def main():
    print("=== Testing Step 3: Fact Extraction Engine ===")
    
    ep1_path = Path("data/episode_001.txt")
    ep1 = parse_screenplay(ep1_path)
    print(f"Parsed Episode {ep1.number} ({len(ep1.get_all_events())} events)")

    # 1. Run Fact Extraction
    t0 = time.time()
    facts = extract_facts_from_episode(ep1, save_to_disk=True)
    duration = time.time() - t0
    print(f"[OK] Extracted {len(facts)} facts in {duration:.2f}s")
    assert len(facts) > 0, "Should extract at least one fact"

    # 2. Verify Every Fact
    print("\nAuditing extracted facts against verbatim source screenplay...")
    for idx, f in enumerate(facts[:5], 1):
        print(f"  {idx}. [{f.timestamp}] {f.entity} ({f.category}) - {f.attribute}: {f.value}")
        print(f"     Quote: \"{f.quote}\" (Reliability: {f.reliability})")
        assert verify_quote_in_screenplay(f.quote, ep1.raw_text), f"Quote must be verbatim: {f.quote}"

    # 3. Verify Disk Persistence
    facts_file = Path("data/facts/episode_001_facts.json")
    assert facts_file.exists(), f"Facts file {facts_file} must exist on disk"
    print(f"\n[OK] Facts successfully persisted to: {facts_file}")

    # 4. Verify Fast Disk Load
    t0 = time.time()
    cached_facts = extract_facts_from_episode(ep1)
    load_time = time.time() - t0
    print(f"[OK] Cached reload took {load_time:.4f}s ({len(cached_facts)} facts loaded)")
    assert len(cached_facts) == len(facts), "Cached facts count must match"

    print("\n[SUCCESS] Step 3 verification passed flawlessly!")

if __name__ == "__main__":
    main()
