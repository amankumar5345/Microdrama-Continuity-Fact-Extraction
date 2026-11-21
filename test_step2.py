"""
test_step2.py
-------------
Verifies Step 2:
- Structured data models (Episode, Scene, ScriptEvent, Fact, Contradiction)
- Screenplay parsing of real microdrama screenplays
- Verbatim quote lookup and verification against screenplay text
"""

from pathlib import Path
from src.parser import parse_screenplay, verify_quote_in_screenplay, find_quote_event
from src.models import FactCategory, Reliability, Fact

def main():
    print("=== Testing Step 2: Screenplay Parser & Data Models ===")
    
    ep1_path = Path("data/episode_01.txt")
    assert ep1_path.exists(), f"File {ep1_path} not found"

    print(f"Parsing: {ep1_path}...")
    ep1 = parse_screenplay(ep1_path)
    
    print(f"[OK] Episode parsed: #{ep1.number}")
    print(f"     Logline: {ep1.logline[:60]}...")
    print(f"     Scenes: {len(ep1.scenes)}")
    assert ep1.number == 1, f"Expected episode 1, got {ep1.number}"
    assert len(ep1.scenes) >= 1, "Must have at least 1 scene"

    events = ep1.get_all_events()
    print(f"     Total Events: {len(events)}")
    assert len(events) > 10, f"Expected > 10 events, got {len(events)}"

    dialogues = [e for e in events if e.event_type == "dialogue"]
    print(f"     Dialogue Lines: {len(dialogues)}")
    assert len(dialogues) > 5, "Expected dialogue lines"

    # Verify Verbatim Quote Checking
    test_quote = "Because he is marrying me."
    assert verify_quote_in_screenplay(test_quote, ep1.raw_text), "Verbatim quote check failed"
    ev = find_quote_event(test_quote, ep1)
    assert ev is not None, "Failed to locate quote event"
    print(f"[OK] Quote '{test_quote}' located at timestamp: {ev.start_time} (Speaker: {ev.speaker})")

    fake_quote = "Juliana is an alien from Mars."
    assert not verify_quote_in_screenplay(fake_quote, ep1.raw_text), "Hallucinated quote must be rejected"
    print(f"[OK] Hallucinated quote correctly rejected by verification check")

    # Verify Fact instantiation & dictionary conversion
    fact = Fact(
        entity="Juliana",
        aliases=["Lady Juliana"],
        category=FactCategory.OBJECT.value,
        attribute="attire",
        value="white silk gown",
        reliability=Reliability.STATED.value,
        timestamp=ev.start_time,
        quote=test_quote,
        episode=ep1.number,
        scene=1,
    )
    d = fact.to_dict()
    assert d["entity"] == "Juliana"
    assert d["category"] == "object"
    print(f"[OK] Fact model serialization verified: {d['entity']} -> {d['attribute']}='{d['value']}'")

    print("\n[SUCCESS] Step 2 verification passed flawlessly!")

if __name__ == "__main__":
    main()
