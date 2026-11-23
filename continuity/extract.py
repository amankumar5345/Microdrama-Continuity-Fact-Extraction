"""
continuity/extract.py
---------------------
Extracts checkable continuity facts per episode via call_llm().
- Uses prompts/extract.txt
- Validates JSON schema
- DROPS any fact whose quote is not found verbatim in that episode's text (case/whitespace-insensitive)
- Logs how many were dropped
- Saves outputs/facts_epN.json
- CLI flag: --eps 1 2 3
"""

import sys
import os
import re
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from continuity.llm import call_llm
from continuity.textutil import (
    clean_aliases,
    enable_utf8_console,
    is_noise_entity,
    normalize_attribute,
    normalize_text_for_matching,
)

enable_utf8_console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Base paths
BASE_DIR = Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "extract.txt"
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs"
ROOT_OUTPUTS_DIR = BASE_DIR.parent / "outputs"

VALID_CATEGORIES = {"identity", "relationship", "status", "object", "place", "timeline"}
VALID_RELIABILITIES = {"stated", "lie", "flashback", "hypothetical", "joke"}


def is_quote_in_screenplay(quote: str, raw_screenplay: str) -> bool:
    """Case- and whitespace-insensitive verbatim quote check."""
    clean_q = normalize_text_for_matching(quote)
    clean_src = normalize_text_for_matching(raw_screenplay)
    if not clean_q:
        return False
    return clean_q in clean_src


def load_extract_prompt(episode_num: int, screenplay_text: str) -> str:
    """Loads and formats the prompt from prompts/extract.txt safely without str.format() brace conflicts."""
    if not PROMPT_FILE.exists():
        fallback_prompt = BASE_DIR.parent / "prompts" / "extract.txt"
        if fallback_prompt.exists():
            prompt_path = fallback_prompt
        else:
            raise FileNotFoundError(f"Prompt template not found at {PROMPT_FILE}")
    else:
        prompt_path = PROMPT_FILE

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Safely replace placeholders without crashing on JSON braces
    has_text_placeholder = ("{screenplay_text}" in template) or ("{text}" in template)

    prompt = template
    prompt = prompt.replace("{episode}", str(episode_num))
    prompt = prompt.replace("{episode_number}", str(episode_num))
    prompt = prompt.replace("{ep}", str(episode_num))

    if has_text_placeholder:
        prompt = prompt.replace("{screenplay_text}", screenplay_text)
        prompt = prompt.replace("{text}", screenplay_text)
    else:
        # If user pasted prompt without {screenplay_text}, append the screenplay text
        prompt = f"{prompt.strip()}\n\nSCREENPLAY:\n{screenplay_text}"

    return prompt


def validate_and_filter_facts(raw_facts: List[Dict[str, Any]], raw_screenplay: str, ep_num: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Validates fact schema and drops any fact whose quote is not found verbatim in raw_screenplay.
    Returns (verified_facts, dropped_count).
    """
    verified = []
    dropped_count = 0

    for item in raw_facts:
        if not isinstance(item, dict):
            dropped_count += 1
            continue

        entity = str(item.get("entity", "")).strip()
        category = str(item.get("category", "")).strip().lower()
        attribute = normalize_attribute(item.get("attribute", ""))
        value = str(item.get("value", "")).strip()
        reliability = str(item.get("reliability", "stated")).strip().lower()
        timestamp = str(item.get("timestamp", "")).strip()
        quote = str(item.get("quote", "")).strip()

        # Schema validation. Section labels such as "Episode 3" or "Timeline"
        # are extraction noise, not story entities.
        if not entity or not attribute or not value or not quote:
            dropped_count += 1
            logger.warning(f"[Ep {ep_num}] Dropping malformed fact missing core fields: {item}")
            continue

        if is_noise_entity(entity):
            dropped_count += 1
            logger.info(f"[Ep {ep_num}] Dropping non-character entity: {entity!r}")
            continue

        aliases = clean_aliases(entity, item.get("aliases", []))

        if category not in VALID_CATEGORIES:
            category = "status"

        if reliability not in VALID_RELIABILITIES:
            reliability = "stated"

        # Verbatim quote check in source screenplay
        if not is_quote_in_screenplay(quote, raw_screenplay):
            dropped_count += 1
            logger.warning(f"[Ep {ep_num}] Dropped non-verbatim quote: \"{quote}\"")
            continue

        verified.append({
            "entity": entity,
            "aliases": aliases,
            "category": category,
            "attribute": attribute,
            "value": value,
            "reliability": reliability,
            "timestamp": timestamp,
            "quote": quote,
        })

    return verified, dropped_count


def extract_episode(ep_num: int, screenplay_path: Path) -> Dict[str, Any]:
    """
    Extracts facts for a single episode, validates, filters, and saves output.
    """
    logger.info(f"Processing Episode {ep_num} from {screenplay_path.name}...")
    with open(screenplay_path, "r", encoding="utf-8", errors="replace") as f:
        raw_screenplay = f.read()

    prompt = load_extract_prompt(ep_num, raw_screenplay)

    # Call LLM with JSON mode. A failure for one episode must not abort the
    # whole pipeline or overwrite a previously good facts file.
    try:
        response_data = call_llm(prompt, json_mode=True)
    except Exception as exc:
        logger.error(f"[Ep {ep_num}] LLM extraction failed: {exc}")
        return {
            "episode": ep_num,
            "facts_count": 0,
            "dropped_count": 0,
            "facts": [],
            "error": str(exc),
        }

    if not isinstance(response_data, dict):
        logger.error(f"[Ep {ep_num}] LLM did not return a JSON object. Got {type(response_data)}")
        raw_facts = []
    else:
        raw_facts = response_data.get("facts", [])
        if not isinstance(raw_facts, list):
            raw_facts = []

    # Validate and drop non-verbatim quotes
    verified_facts, dropped_count = validate_and_filter_facts(raw_facts, raw_screenplay, ep_num)

    logger.info(f"[Ep {ep_num}] Facts Extracted: {len(raw_facts)} | Verified: {len(verified_facts)} | Dropped: {dropped_count}")

    output_data = {
        "episode": ep_num,
        "facts_count": len(verified_facts),
        "dropped_count": dropped_count,
        "facts": verified_facts,
    }

    # Save outputs/facts_epN.json
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUTS_DIR / f"facts_ep{ep_num}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Mirror to root outputs/
    try:
        ROOT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        root_out = ROOT_OUTPUTS_DIR / f"facts_ep{ep_num}.json"
        with open(root_out, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    logger.info(f"[Ep {ep_num}] Saved facts to {out_file}")
    return output_data


def find_screenplay_file(ep_num: int) -> Optional[Path]:
    """Finds screenplay text file for given episode number."""
    candidate_dirs = [DATA_DIR, BASE_DIR.parent / "data"]
    for d in candidate_dirs:
        if not d.exists():
            continue
        patterns = [
            f"episode_{ep_num:03d}.txt",
            f"episode_{ep_num:02d}.txt",
            f"episode_{ep_num}.txt",
            f"episode-*{ep_num:03d}*.txt",
            f"*ep*{ep_num}*.txt",
        ]
        for pat in patterns:
            matches = list(d.glob(pat))
            if matches:
                return matches[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Extract continuity facts from microdrama screenplays.")
    parser.add_argument(
        "--eps",
        nargs="+",
        type=int,
        help="Specific episode numbers to process, e.g. --eps 1 2 3",
    )
    args = parser.parse_args()

    # Determine which episodes to run
    if args.eps:
        target_episodes = sorted(list(set(args.eps)))
    else:
        # Default: scan all files in data/
        target_episodes = []
        files = list(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []
        for f in files:
            m = re.search(r"(\d+)", f.name)
            if m:
                target_episodes.append(int(m.group(1)))
        target_episodes = sorted(list(set(target_episodes))) or [1]

    logger.info(f"Running fact extraction on episodes: {target_episodes}")

    total_verified = 0
    total_dropped = 0

    for ep_num in target_episodes:
        screenplay_path = find_screenplay_file(ep_num)
        if not screenplay_path:
            logger.warning(f"Could not find screenplay file for Episode {ep_num}. Skipping.")
            continue

        result = extract_episode(ep_num, screenplay_path)
        total_verified += result["facts_count"]
        total_dropped += result["dropped_count"]

    print("\n" + "=" * 60)
    print("🎬 EXTRACTION COMPLETED")
    print("=" * 60)
    print(f"  Episodes processed : {len(target_episodes)}")
    print(f"  Verified facts     : {total_verified}")
    print(f"  Dropped non-quotes : {total_dropped}")
    print(f"  Output directory   : {OUTPUTS_DIR}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
