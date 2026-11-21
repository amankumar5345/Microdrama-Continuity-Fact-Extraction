"""
continuity/bible.py
-------------------
Merges all extracted facts into one comprehensive Series Bible per entity.
- Normalizes names using aliases and an LLM-proposed alias merge map.
- Saves the alias merge map to outputs/alias_map.json for human review/editing.
- Outputs outputs/bible.json structured as:
  entity -> attribute -> list of {value, ep, timestamp, quote, reliability}.
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any, Set
from collections import defaultdict

from continuity.llm import call_llm

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

ALIAS_MAP_FILE_1 = OUTPUTS_DIR / "alias_map.json"
ALIAS_MAP_FILE_2 = ROOT_OUTPUTS_DIR / "alias_map.json"

BIBLE_FILE_1 = OUTPUTS_DIR / "bible.json"
BIBLE_FILE_2 = ROOT_OUTPUTS_DIR / "bible.json"


def load_all_fact_files() -> List[Dict[str, Any]]:
    """Finds and loads all facts_ep*.json files from outputs/."""
    candidate_dirs = [OUTPUTS_DIR, ROOT_OUTPUTS_DIR]
    loaded_episodes = set()
    all_facts_records: List[Dict[str, Any]] = []

    for d in candidate_dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("facts_ep*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    ep_num = data.get("episode", 1)
                    if ep_num in loaded_episodes:
                        continue
                    loaded_episodes.add(ep_num)
                    all_facts_records.append(data)
            except Exception as e:
                logger.warning(f"Error reading {f}: {e}")

    return sorted(all_facts_records, key=lambda x: x.get("episode", 0))


def gather_entities_and_aliases(all_episode_data: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Gathers all unique entity names and their observed aliases."""
    entity_aliases: Dict[str, Set[str]] = defaultdict(set)
    for ep_data in all_episode_data:
        for f in ep_data.get("facts", []):
            entity = f.get("entity", "").strip()
            if not entity:
                continue
            aliases = f.get("aliases", [])
            if isinstance(aliases, list):
                for a in aliases:
                    if a and a.strip() and a.strip().lower() != entity.lower():
                        entity_aliases[entity].add(a.strip())
            elif isinstance(aliases, str) and aliases.strip():
                entity_aliases[entity].add(aliases.strip())
    return entity_aliases


def generate_alias_map_with_llm(entity_aliases: Dict[str, Set[str]]) -> Dict[str, str]:
    """Prompts call_llm() to propose canonical entity alias merges."""
    summary_lines = []
    for ent, aliases in sorted(entity_aliases.items()):
        if aliases:
            summary_lines.append(f"- {ent} (known aliases: {', '.join(sorted(aliases))})")
        else:
            summary_lines.append(f"- {ent}")

    entities_str = "\n".join(summary_lines)

    prompt = f"""You are a continuity analyst for a serialized microdrama.
Review the following list of characters, entities, and aliases extracted from the screenplay episodes:

{entities_str}

Task:
Propose a canonical name mapping that unifies variant spellings, courtesy titles, abbreviations, and aliases to their single canonical name.
For example:
"Juliana" -> "Lady Juliana"
"The Former Groom" -> "Gerald"
"Lady in Gold Gown" -> "Clarissa"
"Mr. Cole" -> "Daniel Cole"

RULES:
1. Every alias/variant must map to the most complete, standard canonical name for that character.
2. Distinct characters must NOT be merged together.
3. Output valid JSON only, mapping each alias/variant to its canonical name:
{{
  "variant_name": "Canonical Name"
}}
"""

    logger.info("Asking LLM to propose canonical alias merges...")
    try:
        alias_map = call_llm(prompt, json_mode=True)
        if isinstance(alias_map, dict):
            # Ensure values are clean strings
            clean_map = {str(k).strip(): str(v).strip() for k, v in alias_map.items() if str(k).strip() != str(v).strip()}
            return clean_map
    except Exception as e:
        logger.warning(f"LLM alias proposal failed: {e}. Falling back to rule-based aliases.")

    # Fallback: simple alias list invert
    fallback_map: Dict[str, str] = {}
    for ent, aliases in entity_aliases.items():
        for a in aliases:
            if a.lower() != ent.lower():
                fallback_map[a] = ent
    return fallback_map


def get_or_create_alias_map(entity_aliases: Dict[str, Set[str]], force_rebuild: bool = False) -> Dict[str, str]:
    """
    Loads existing alias_map.json (so human edits are preserved), or creates one via LLM.
    """
    for map_file in [ALIAS_MAP_FILE_1, ALIAS_MAP_FILE_2]:
        if map_file.exists() and not force_rebuild:
            try:
                with open(map_file, "r", encoding="utf-8") as f:
                    alias_map = json.load(f)
                    logger.info(f"Loaded existing alias map from {map_file} ({len(alias_map)} entries)")
                    return alias_map
            except Exception as e:
                logger.warning(f"Error reading existing alias map {map_file}: {e}")

    # Generate new alias map via LLM
    alias_map = generate_alias_map_with_llm(entity_aliases)

    # Save to disk for human editing
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALIAS_MAP_FILE_1, "w", encoding="utf-8") as f:
        json.dump(alias_map, f, indent=2, ensure_ascii=False)

    try:
        ROOT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(ALIAS_MAP_FILE_2, "w", encoding="utf-8") as f:
            json.dump(alias_map, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    logger.info(f"Saved alias map to {ALIAS_MAP_FILE_1} (editable by hand)")
    return alias_map


def build_series_bible(all_episode_data: List[Dict[str, Any]], alias_map: Dict[str, str]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """
    Builds the Series Bible:
    entity -> attribute -> list of {value, ep, timestamp, quote, reliability}.
    """
    bible: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    seen_entries: Set[str] = set()

    for ep_data in all_episode_data:
        ep_num = ep_data.get("episode", 1)
        facts = ep_data.get("facts", [])

        for f in facts:
            raw_entity = f.get("entity", "").strip()
            if not raw_entity:
                continue

            # Resolve canonical entity name through alias map
            canonical_entity = alias_map.get(raw_entity, raw_entity)

            attr = f.get("attribute", "").strip().lower()
            val = f.get("value", "").strip()
            quote = f.get("quote", "").strip()
            ts = f.get("timestamp", "").strip()
            rel = f.get("reliability", "stated").strip().lower()

            if not attr or not val:
                continue

            # Deduplication key
            dedup_key = f"{canonical_entity}|{attr}|{val}|{ep_num}|{ts}|{quote}"
            if dedup_key in seen_entries:
                continue
            seen_entries.add(dedup_key)

            entry = {
                "value": val,
                "ep": ep_num,
                "timestamp": ts,
                "quote": quote,
                "reliability": rel,
            }

            bible[canonical_entity][attr].append(entry)

    # Convert defaultdicts to standard sorted dicts
    clean_bible: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for ent in sorted(bible.keys()):
        clean_bible[ent] = {}
        for attr in sorted(bible[ent].keys()):
            # Sort entries chronologically by episode and timestamp
            sorted_entries = sorted(bible[ent][attr], key=lambda x: (x.get("ep", 0), x.get("timestamp", "")))
            clean_bible[ent][attr] = sorted_entries

    return clean_bible


def save_series_bible(bible: Dict[str, Any]) -> None:
    """Saves the bible to outputs/bible.json."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(BIBLE_FILE_1, "w", encoding="utf-8") as f:
        json.dump(bible, f, indent=2, ensure_ascii=False)

    try:
        ROOT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(BIBLE_FILE_2, "w", encoding="utf-8") as f:
            json.dump(bible, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    logger.info(f"Saved Series Bible to {BIBLE_FILE_1}")


def main():
    parser = argparse.ArgumentParser(description="Build continuity Series Bible from extracted facts.")
    parser.add_argument(
        "--rebuild-aliases",
        action="store_true",
        help="Re-prompt LLM to propose alias merges even if alias_map.json exists",
    )
    args = parser.parse_args()

    all_episode_data = load_all_fact_files()
    if not all_episode_data:
        logger.error("No facts_ep*.json files found in outputs/ directory. Run extract.py first!")
        sys.exit(1)

    logger.info(f"Loaded facts from {len(all_episode_data)} episode file(s).")

    # 1. Gather entities and determine aliases
    entity_aliases = gather_entities_and_aliases(all_episode_data)

    # 2. Build or load alias map
    alias_map = get_or_create_alias_map(entity_aliases, force_rebuild=args.rebuild_aliases)

    # 3. Build series bible
    bible = build_series_bible(all_episode_data, alias_map)

    # 4. Save to outputs/bible.json
    save_series_bible(bible)

    # Print summary
    total_attributes = sum(len(attrs) for attrs in bible.values())
    total_facts_in_bible = sum(len(entries) for attrs in bible.values() for entries in attrs.values())

    print("\n" + "=" * 60)
    print("📖 CONTINUITY SERIES BIBLE GENERATED")
    print("=" * 60)
    print(f"  Episodes Ingested : {len(all_episode_data)}")
    print(f"  Canonical Entities: {len(bible)}")
    print(f"  Total Attributes  : {total_attributes}")
    print(f"  Facts Recorded    : {total_facts_in_bible}")
    print(f"  Alias Map File    : {ALIAS_MAP_FILE_1}")
    print(f"  Bible JSON File   : {BIBLE_FILE_1}")
    print("\nEntities in Bible:")
    for ent, attrs in bible.items():
        print(f"  - {ent} ({len(attrs)} attributes: {', '.join(list(attrs.keys())[:5])}...)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
