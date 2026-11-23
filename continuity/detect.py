"""
continuity/detect.py
--------------------
Detects cross-episode candidate continuity contradictions in two passes:
Pass 1: Value conflicts - same entity + attribute, different values in different episodes (reliability == "stated").
Pass 2: State errors - entity with status like arrested, dead, or injured in episode X who appears or speaks in a later episode with no status change in between.

Outputs candidate pairs with both quotes to outputs/candidates.json.
Prints the count per type.
"""

import sys
import os
import re
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

from continuity.textutil import enable_utf8_console, normalize_attribute, normalize_value

enable_utf8_console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
ROOT_OUTPUTS_DIR = BASE_DIR.parent / "outputs"

BIBLE_FILE_1 = OUTPUTS_DIR / "bible.json"
BIBLE_FILE_2 = ROOT_OUTPUTS_DIR / "bible.json"

CANDIDATES_FILE_1 = OUTPUTS_DIR / "candidates.json"
CANDIDATES_FILE_2 = ROOT_OUTPUTS_DIR / "candidates.json"

# State keywords for Pass 2
DEAD_PATTERNS = re.compile(r"\b(dead|deceased|killed|murdered|perished|slain|corpse|passed away|fatal)\b", re.I)
ARREST_PATTERNS = re.compile(r"\b(arrested|in jail|in prison|imprisoned|jailed|captured|in custody|detained|behind bars|lockup)\b", re.I)
INJURED_PATTERNS = re.compile(r"\b(critically injured|unconscious|comatose|in a coma|paralyzed|poisoned|bedridden|hospitalized)\b", re.I)

REVERSAL_PATTERNS = re.compile(r"\b(released|freed|escaped|bailed|acquitted|healed|recovered|woke up|conscious|resurrected|survived|discharged)\b", re.I)


def load_bible() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Loads Series Bible from outputs/bible.json."""
    for b_path in [BIBLE_FILE_1, BIBLE_FILE_2]:
        if b_path.exists():
            try:
                with open(b_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read bible at {b_path}: {e}")
    return {}


def _merged_attributes(
    attributes: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Group attributes that normalize to the same key (e.g. eye_color variants)."""
    merged: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for attribute, entries in attributes.items():
        merged[normalize_attribute(attribute)].extend(entries)
    return merged


def pass_1_value_conflicts(bible: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    """
    Pass 1: Value conflicts.
    Same entity + normalized attribute, different stated values in different
    episodes.
    """
    candidates = []
    seen_pairs: Set[str] = set()

    for entity, attributes in bible.items():
        for attribute, entries in _merged_attributes(attributes).items():
            if not attribute:
                continue

            stated_entries = [
                e
                for e in entries
                if str(e.get("reliability", "")).lower() == "stated"
            ]
            if len(stated_entries) < 2:
                continue

            # Group entries by episode to compare representative values.
            ep_entries: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
            for e in stated_entries:
                ep_entries[e.get("ep", 0)].append(e)

            episodes = sorted(ep_entries.keys())
            if len(episodes) < 2:
                continue

            for i in range(len(episodes)):
                for j in range(i + 1, len(episodes)):
                    ep_a = episodes[i]
                    ep_b = episodes[j]

                    for entry_a in ep_entries[ep_a]:
                        for entry_b in ep_entries[ep_b]:
                            norm_a = normalize_value(entry_a.get("value", ""))
                            norm_b = normalize_value(entry_b.get("value", ""))

                            if not norm_a or not norm_b or norm_a == norm_b:
                                continue

                            pair_key = (
                                f"{entity}|{attribute}|{ep_a}|{norm_a}|{ep_b}|{norm_b}"
                            )
                            if pair_key in seen_pairs:
                                continue
                            seen_pairs.add(pair_key)

                            candidates.append({
                                "type": "value_conflict",
                                "entity": entity,
                                "attribute": attribute,
                                "fact_a": entry_a,
                                "fact_b": entry_b,
                                "description": (
                                    f"Value conflict for {entity} -> {attribute}: "
                                    f"Ep {ep_a} ('{entry_a.get('value')}') vs "
                                    f"Ep {ep_b} ('{entry_b.get('value')}')"
                                ),
                            })

    return candidates


def _fact_text(fact: Dict[str, Any]) -> str:
    return f"{fact.get('value', '')} {fact.get('quote', '')}"


def _state_category(fact: Dict[str, Any]) -> Optional[str]:
    text = _fact_text(fact)
    if DEAD_PATTERNS.search(text):
        return "dead"
    if ARREST_PATTERNS.search(text):
        return "arrested"
    if INJURED_PATTERNS.search(text):
        return "injured"
    return None


def pass_2_state_errors(bible: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    """
    Pass 2: State errors.

    An entity marked dead/arrested/injured in episode X who has a stated fact in
    a later episode that is not itself a disabling state, with no reversal
    (released, healed, survived, ...) anywhere in between.
    """
    candidates = []
    seen_state_errors: Set[str] = set()

    for entity, attributes in bible.items():
        all_facts: List[Dict[str, Any]] = []
        for attr, entries in _merged_attributes(attributes).items():
            for entry in entries:
                fact = dict(entry)
                fact["attribute"] = attr
                fact.setdefault("reliability", "stated")
                all_facts.append(fact)

        if not all_facts:
            continue

        all_facts.sort(key=lambda x: (x.get("ep", 0), x.get("timestamp", "")))

        for idx, fact_a in enumerate(all_facts):
            # Only stated facts can establish a disabling state.
            if str(fact_a.get("reliability", "")).lower() != "stated":
                continue

            ep_a = fact_a.get("ep", 0)
            state_category = _state_category(fact_a)
            if not state_category:
                continue
            # "arrested and later released" in one fact is not a disabling state.
            if REVERSAL_PATTERNS.search(_fact_text(fact_a)):
                continue

            for fact_b in all_facts[idx + 1:]:
                if str(fact_b.get("reliability", "")).lower() != "stated":
                    continue

                ep_b = fact_b.get("ep", 0)
                if ep_b <= ep_a:
                    continue

                text_b = _fact_text(fact_b)

                # A later disabling statement is not evidence of recovery.
                if _state_category(fact_b):
                    continue

                # A reversal at any point up to fact_b clears the error.
                reversal_found = any(
                    REVERSAL_PATTERNS.search(_fact_text(other))
                    for other in all_facts
                    if ep_a < other.get("ep", 0) <= ep_b
                )
                if reversal_found:
                    break

                error_key = f"{entity}|{state_category}|{ep_a}|{ep_b}"
                if error_key in seen_state_errors:
                    break
                seen_state_errors.add(error_key)

                candidates.append({
                    "type": "state_error",
                    "entity": entity,
                    "attribute": fact_a.get("attribute", "status"),
                    "state_category": state_category,
                    "fact_a": fact_a,
                    "fact_b": fact_b,
                    "description": (
                        f"State error for {entity}: marked as {state_category} in "
                        f"Ep {ep_a} (\"{fact_a.get('quote')}\"), but the character has "
                        f"a stated fact in Ep {ep_b} (\"{fact_b.get('quote')}\") "
                        f"without an intervening status reversal."
                    ),
                })
                # One flag per disabling state occurrence is enough for review.
                break

    return candidates


def save_candidates(candidates: List[Dict[str, Any]]) -> None:
    """Saves candidate pairs to outputs/candidates.json."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_FILE_1, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)

    try:
        ROOT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(CANDIDATES_FILE_2, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    logger.info(f"Saved {len(candidates)} candidate pairs to {CANDIDATES_FILE_1}")


def main():
    logger.info("Running Continuity Contradiction Detector (Two Passes)...")
    bible = load_bible()
    if not bible:
        logger.error("No Series Bible found in outputs/bible.json. Run bible.py first!")
        sys.exit(1)

    # Pass 1: Value conflicts
    value_conflicts = pass_1_value_conflicts(bible)

    # Pass 2: State errors
    state_errors = pass_2_state_errors(bible)

    all_candidates = value_conflicts + state_errors

    # Save to outputs/candidates.json
    save_candidates(all_candidates)

    # Print summary and count per type as requested
    print("\n" + "=" * 60)
    print("🔍 CONTRADICTION DETECTION SUMMARY")
    print("=" * 60)
    print(f"  Pass 1 (Value Conflicts) : {len(value_conflicts)}")
    print(f"  Pass 2 (State Errors)    : {len(state_errors)}")
    print(f"  Total Candidates Flagged : {len(all_candidates)}")
    print(f"  Saved to                 : {CANDIDATES_FILE_1}")

    if all_candidates:
        print("\nCandidate Pairs Sample:")
        for idx, c in enumerate(all_candidates[:5], 1):
            print(f"\n  [{idx}] Type: {c['type']} | Entity: {c['entity']} ({c['attribute']})")
            print(f"      Fact A (Ep {c['fact_a'].get('ep')} @ {c['fact_a'].get('timestamp')}):")
            print(f"        Value: {c['fact_a'].get('value')}")
            print(f"        Quote: \"{c['fact_a'].get('quote')}\"")
            print(f"      Fact B (Ep {c['fact_b'].get('ep')} @ {c['fact_b'].get('timestamp')}):")
            print(f"        Value: {c['fact_b'].get('value')}")
            print(f"        Quote: \"{c['fact_b'].get('quote')}\"")
        if len(all_candidates) > 5:
            print(f"\n  ... and {len(all_candidates) - 5} more candidate pairs in {CANDIDATES_FILE_1.name}.")
    else:
        print("\n  ✅ No candidate contradictions found across ingested episodes.")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
