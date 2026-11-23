"""
src/extractor.py
----------------
Extracts continuity facts per episode using call_llm(prompt).
Enforces:
1. Verbatim quote verification against source screenplay.
2. Ground-truth timestamp alignment.
3. Strict JSON parsing and schema validation.
4. Disk persistence for extracted facts.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.models import Fact, Episode, FactCategory, Reliability
from src.parser import verify_quote_in_screenplay, find_quote_event
from src.llm import call_llm, load_config

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """You are a continuity analyst for a serialized microdrama.
Read the screenplay of Episode {episode_number} below and extract every checkable fact about characters, relationships, status, objects, places and timeline.

RULES:
1. Every fact needs a verbatim quote from the screenplay and its timestamp. No quote, no fact.
2. Extract only what is stated or clearly shown. Do not infer.
3. Use the name exactly as written in the scene, and list any alias used (e.g. "Gerald", "The Former Groom").
4. If a line is a lie, joke, hypothetical or flashback, set "reliability" to that type. Otherwise use "stated".
5. Ignore opinions, emotions and plot summary.
6. Output valid JSON only. No commentary.

OUTPUT FORMAT:
{{
  "episode": {episode_number},
  "facts": [
    {{
      "entity": "Character Name",
      "aliases": ["Alias 1", "Alias 2"],
      "category": "identity | relationship | status | object | place | timeline",
      "attribute": "attribute_name (e.g. sister, spouse, job, attire, location, eye_color)",
      "value": "factual_value",
      "reliability": "stated | lie | flashback | hypothetical",
      "timestamp": "mm:ss",
      "quote": "verbatim quote from the script"
    }}
  ]
}}

SCREENPLAY:
{screenplay_text}
"""


def _clean_json_response(raw_resp: str) -> str:
    """Extract valid JSON from raw response, stripping markdown fences if present."""
    text = raw_resp.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _load_cached_facts(facts_file: Path, episode: Episode) -> List[Fact]:
    """
    Load cached facts and re-verify every quote against the current screenplay.

    Caches can outlive the file they were extracted from (or be produced by an
    older parser), so a cached quote is never trusted blindly.
    """
    with open(facts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_facts = data.get("facts", [])
    facts: List[Fact] = []
    invalid = 0

    for item in raw_facts:
        if not isinstance(item, dict):
            invalid += 1
            continue
        try:
            fact = Fact(
                entity=str(item.get("entity", "")).strip(),
                aliases=item.get("aliases", []) if isinstance(item.get("aliases", []), list) else [],
                category=str(item.get("category", "status")).strip(),
                attribute=str(item.get("attribute", "")).strip().lower(),
                value=str(item.get("value", "")).strip(),
                reliability=str(item.get("reliability", "stated")).strip(),
                timestamp=str(item.get("timestamp", "")).strip(),
                quote=str(item.get("quote", "")).strip(),
                episode=int(item.get("episode", episode.number)),
                scene=item.get("scene"),
            )
        except Exception:
            invalid += 1
            continue

        if not fact.entity or not fact.quote or not verify_quote_in_screenplay(fact.quote, episode.raw_text):
            invalid += 1
            logger.warning(f"Dropping cached fact with unverifiable quote: {fact.quote!r}")
            continue
        facts.append(fact)

    if invalid:
        logger.warning(
            "Revalidation removed %d of %d cached fact(s) from %s.",
            invalid,
            len(raw_facts),
            facts_file.name,
        )
        try:
            data["facts"] = [fact.to_dict() for fact in facts]
            data["facts_count"] = len(facts)
            data["dropped_count"] = int(data.get("dropped_count", 0)) + invalid
            with open(facts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to rewrite revalidated facts file {facts_file}: {e}")

    return facts


def extract_facts_from_episode(
    episode: Episode,
    save_to_disk: bool = True,
    force_refresh: bool = False,
) -> List[Fact]:
    """
    Extracts, validates, and grounds continuity facts from an episode screenplay.

    Args:
        episode: Parsed episode.
        save_to_disk: Persist verified facts to data/facts/.
        force_refresh: Ignore an existing cache and call the LLM again.
    """
    config = load_config()
    strict_quote_check = config.get("checker", {}).get("strict_quote_verification", True)

    facts_dir = Path(__file__).resolve().parent.parent / "data" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    facts_file = facts_dir / f"episode_{episode.number:03d}_facts.json"

    # Check if facts are already extracted and cached on disk.
    if facts_file.exists() and not force_refresh:
        try:
            facts = _load_cached_facts(facts_file, episode)
            logger.info(f"Loaded {len(facts)} revalidated cached facts from {facts_file.name}")
            return facts
        except Exception as e:
            logger.warning(f"Failed to read existing facts file {facts_file}: {e}")

    # Build prompt
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        episode_number=episode.number,
        screenplay_text=episode.raw_text,
    )

    logger.info(f"Extracting facts for Episode {episode.number} via call_llm()...")
    raw_output = call_llm(prompt)
    clean_json_str = _clean_json_response(raw_output)

    try:
        parsed_data = json.loads(clean_json_str)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for Episode {episode.number}: {e}")
        return []

    raw_facts = parsed_data.get("facts", [])
    verified_facts: List[Fact] = []

    valid_categories = {c.value for c in FactCategory}
    valid_reliabilities = {r.value for r in Reliability}

    for item in raw_facts:
        entity = str(item.get("entity", "")).strip()
        aliases = item.get("aliases", [])
        category = str(item.get("category", "")).strip().lower()
        attribute = str(item.get("attribute", "")).strip().lower()
        value = str(item.get("value", "")).strip()
        reliability = str(item.get("reliability", "stated")).strip().lower()
        timestamp = str(item.get("timestamp", "")).strip()
        quote = str(item.get("quote", "")).strip()

        if not entity or not attribute or not value or not quote:
            continue

        if category not in valid_categories:
            category = FactCategory.STATUS.value

        if reliability not in valid_reliabilities:
            reliability = Reliability.STATED.value

        # Enforce Rule 1 & 2: Verbatim quote verification
        is_verified = verify_quote_in_screenplay(quote, episode.raw_text)

        if not is_verified and strict_quote_check:
            logger.warning(f"Dropping unverified/hallucinated quote: '{quote}'")
            continue

        # Ground timestamp to exact screenplay event if found
        ev = find_quote_event(quote, episode)
        final_timestamp = ev.start_time if ev and ev.start_time else timestamp

        fact = Fact(
            entity=entity,
            aliases=aliases if isinstance(aliases, list) else [str(aliases)],
            category=category,
            attribute=attribute,
            value=value,
            reliability=reliability,
            timestamp=final_timestamp,
            quote=quote,
            episode=episode.number,
        )
        verified_facts.append(fact)

    logger.info(f"Episode {episode.number}: {len(verified_facts)} verified facts extracted.")

    # Save to disk
    if save_to_disk:
        try:
            with open(facts_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "episode": episode.number,
                        "facts_count": len(verified_facts),
                        "facts": [f.to_dict() for f in verified_facts],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception as e:
            logger.warning(f"Failed to write facts file {facts_file}: {e}")

    return verified_facts
