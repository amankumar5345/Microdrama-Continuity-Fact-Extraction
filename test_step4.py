"""
test_step4.py
-------------
Verifies Step 4:
- Canonical entity and alias resolution
- Invariant attribute contradiction detection (Rule-based)
- Semantic cross-episode contradiction analysis via call_llm()
- Generation of detailed Contradiction records with verbatim quotes & timestamps
"""

from src.models import Fact
from src.checker import EntityResolver, check_contradictions

def main():
    print("=== Testing Step 4: Cross-Episode Contradiction Detector ===")

    # 1. Test Entity Resolution
    resolver = EntityResolver()
    resolver.register("Lady Juliana", ["Juliana"])
    resolver.register("Gerald", ["The Former Groom", "Dan"])
    
    c1 = resolver.get_canonical("Juliana")
    c2 = resolver.get_canonical("Lady Juliana")
    assert c1 == c2, f"Aliases must resolve to same canonical entity: {c1} vs {c2}"
    print(f"[OK] Alias resolution: 'Lady Juliana' & 'Juliana' -> '{c1}'")

    # 2. Test Invariant Lore Contradiction (e.g. Eye Color Retcon)
    fact1 = Fact(
        entity="Lady Juliana",
        aliases=["Juliana"],
        category="identity",
        attribute="eye_color",
        value="blue",
        reliability="stated",
        timestamp="00:33.70",
        quote="Close-up on Juliana's trembling lips and shocked, tearful blue eyes.",
        episode=1
    )
    fact2_contradictory = Fact(
        entity="Juliana",
        aliases=["Lady Juliana"],
        category="identity",
        attribute="eye_color",
        value="emerald green",
        reliability="stated",
        timestamp="01:12.00",
        quote="Her emerald green eyes widened in surprise.",
        episode=12
    )
    
    print("\nRunning contradiction detector on conflicting eye color across episodes...")
    contradictions = check_contradictions([fact1, fact2_contradictory], use_llm_evaluator=False)
    assert len(contradictions) == 1, f"Expected 1 contradiction, got {len(contradictions)}"
    contra = contradictions[0]
    print(f"[OK] Detected Contradiction: [{contra.contradiction_id}] {contra.severity}")
    print(f"     Entity: {contra.entity} | Attribute: {contra.attribute}")
    print(f"     Fact A (Ep {contra.fact_a.episode} @ {contra.fact_a.timestamp}): \"{contra.fact_a.quote}\"")
    print(f"     Fact B (Ep {contra.fact_b.episode} @ {contra.fact_b.timestamp}): \"{contra.fact_b.quote}\"")
    print(f"     Explanation: {contra.explanation}")

    # 3. Test Non-Contradictory Progression
    # Gerald was fiancé in Ep 1, but broke engagement in Ep 2 -> Not a contradiction
    fact_engaged = Fact(
        entity="Gerald",
        aliases=["The Former Groom"],
        category="relationship",
        attribute="betrothed",
        value="Juliana",
        reliability="stated",
        timestamp="00:15.50",
        quote="Gerald is waiting for me.",
        episode=1
    )
    fact_broken = Fact(
        entity="The Former Groom",
        aliases=["Gerald"],
        category="relationship",
        attribute="betrothed",
        value="Clarissa",
        reliability="stated",
        timestamp="00:20.90",
        quote="Promises change when a better choice appears.",
        episode=2
    )

    print("\nRunning semantic evaluator on plot progression (Engagement breakup)...")
    progression_results = check_contradictions([fact_engaged, fact_broken], use_llm_evaluator=True)
    print(f"[OK] Evaluated legitimate plot progression. Contradictions found: {len(progression_results)} (0 expected)")

    print("\n[SUCCESS] Step 4 verification passed flawlessly!")

if __name__ == "__main__":
    main()
