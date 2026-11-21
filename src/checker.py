"""
src/checker.py
--------------
Detects cross-episode continuity contradictions, state anomalies, and lore discrepancies.

Key features:
1. Alias normalization to group facts under canonical entity names.
2. Rule-based detection for mutually exclusive attributes (physical lore, family relationships, mortality).
3. LLM-assisted semantic contradiction validation via call_llm() with disk caching.
4. Generates structured Contradiction objects linking both facts with verbatim quotes and timestamps.
"""

import json
import logging
import re
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from src.models import Fact, Contradiction
from src.llm import call_llm

logger = logging.getLogger(__name__)

# Attributes that should be globally invariant across all episodes unless explicitly retconned
INVARIANT_ATTRIBUTES = {
    "eye_color",
    "hair_color",
    "birthplace",
    "biological_father",
    "biological_mother",
    "mother",
    "father",
    "sister",
    "brother",
    "species",
    "native_language",
}

CONTRADICTION_EVAL_PROMPT = """You are a meticulous continuity analyst for a serialized microdrama.
Determine if the two facts extracted from different episodes represent a genuine narrative or lore CONTRADICTION.

Fact A (Episode {ep_a}, timestamp {ts_a}):
- Entity: {entity_a}
- Attribute: {attr_a}
- Value: {val_a}
- Reliability: {rel_a}
- Verbatim Quote: "{quote_a}"

Fact B (Episode {ep_b}, timestamp {ts_b}):
- Entity: {entity_b}
- Attribute: {attr_b}
- Value: {val_b}
- Reliability: {rel_b}
- Verbatim Quote: "{quote_b}"

GUIDELINES:
1. A genuine contradiction occurs when two stated facts cannot both be true in the story world (e.g., eye color changes, character is alive after being confirmed dead, inconsistent parentage, conflicting backstory).
2. If one fact is a recognized change in time/status (e.g. was engaged -> engagement broken -> married someone else), that is plot progression, NOT a contradiction.
3. If one fact is a lie or joke, it may explain the discrepancy.
4. Output valid JSON only.

OUTPUT FORMAT:
{{
  "is_contradiction": true | false,
  "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
  "explanation": "Clear, concise reason why this is a continuity error or why it is not."
}}
"""


class EntityResolver:
    """Resolves aliases and character names to canonical entities."""

    def __init__(self):
        self.alias_to_canonical: Dict[str, str] = {}

    def register(self, entity: str, aliases: List[str]) -> str:
        all_names = [entity] + (aliases or [])
        clean_names = [re.sub(r"^(lady|lord|mr\.|mrs\.|dr\.)\s+", "", n.strip(), flags=re.I).lower() for n in all_names if n.strip()]
        
        # Check if any existing canonical matches
        canonical = None
        for name in clean_names:
            if name in self.alias_to_canonical:
                canonical = self.alias_to_canonical[name]
                break
        
        if not canonical:
            canonical = entity.strip()

        for name in clean_names:
            self.alias_to_canonical[name] = canonical
            self.alias_to_canonical[name.lower()] = canonical

        return canonical

    def get_canonical(self, name: str) -> str:
        clean = re.sub(r"^(lady|lord|mr\.|mrs\.|dr\.)\s+", "", name.strip(), flags=re.I).lower()
        return self.alias_to_canonical.get(clean, name.strip())


def _clean_json_str(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def check_contradictions(facts: List[Fact], use_llm_evaluator: bool = True) -> List[Contradiction]:
    """
    Analyzes a collection of facts across episodes and identifies continuity contradictions.
    """
    resolver = EntityResolver()
    for f in facts:
        resolver.register(f.entity, f.aliases)

    # Group facts by canonical entity and normalized attribute
    grouped: Dict[Tuple[str, str], List[Fact]] = defaultdict(list)
    for f in facts:
        canon_entity = resolver.get_canonical(f.entity)
        norm_attr = f.attribute.lower().replace(" ", "_")
        grouped[(canon_entity, norm_attr)].append(f)

    contradictions: List[Contradiction] = []
    contra_counter = 1

    # 1. Check pairwise facts under same entity and attribute across different episodes
    for (entity, attr), attr_facts in grouped.items():
        if len(attr_facts) < 2:
            continue

        for i in range(len(attr_facts)):
            for j in range(i + 1, len(attr_facts)):
                fact_a = attr_facts[i]
                fact_b = attr_facts[j]

                # Only compare across different episodes or distinct scenes
                if fact_a.episode == fact_b.episode:
                    continue

                val_a = fact_a.value.strip().lower()
                val_b = fact_b.value.strip().lower()

                # If values match, no contradiction
                if val_a == val_b:
                    continue

                # Check invariant attributes (e.g. eye_color, mother, father)
                if attr in INVARIANT_ATTRIBUTES and fact_a.reliability == "stated" and fact_b.reliability == "stated":
                    c = Contradiction(
                        contradiction_id=f"CONTRA-{contra_counter:04d}",
                        entity=entity,
                        attribute=attr,
                        category=fact_a.category,
                        severity="CRITICAL",
                        fact_a=fact_a,
                        fact_b=fact_b,
                        explanation=f"Invariant attribute '{attr}' changed from '{fact_a.value}' (Ep {fact_a.episode}) to '{fact_b.value}' (Ep {fact_b.episode}).",
                    )
                    contradictions.append(c)
                    contra_counter += 1
                    continue

                # Semantic / Status evaluation via LLM if enabled
                if use_llm_evaluator:
                    prompt = CONTRADICTION_EVAL_PROMPT.format(
                        ep_a=fact_a.episode,
                        ts_a=fact_a.timestamp,
                        entity_a=fact_a.entity,
                        attr_a=fact_a.attribute,
                        val_a=fact_a.value,
                        rel_a=fact_a.reliability,
                        quote_a=fact_a.quote,
                        ep_b=fact_b.episode,
                        ts_b=fact_b.timestamp,
                        entity_b=fact_b.entity,
                        attr_b=fact_b.attribute,
                        val_b=fact_b.value,
                        rel_b=fact_b.reliability,
                        quote_b=fact_b.quote,
                    )
                    try:
                        raw = call_llm(prompt)
                        eval_data = json.loads(_clean_json_str(raw))
                        if eval_data.get("is_contradiction", False):
                            c = Contradiction(
                                contradiction_id=f"CONTRA-{contra_counter:04d}",
                                entity=entity,
                                attribute=attr,
                                category=fact_a.category,
                                severity=eval_data.get("severity", "HIGH"),
                                fact_a=fact_a,
                                fact_b=fact_b,
                                explanation=eval_data.get("explanation", "Narrative inconsistency detected across episodes."),
                            )
                            contradictions.append(c)
                            contra_counter += 1
                    except Exception as e:
                        logger.warning(f"Contradiction LLM eval failed for pair: {e}")

    return contradictions
