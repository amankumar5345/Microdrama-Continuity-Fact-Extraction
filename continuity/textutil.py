"""
continuity/textutil.py
----------------------
Shared normalization helpers used by extraction, the Series Bible, and detection.

Keeping these in one place guarantees that an attribute written to
``facts_epN.json`` is grouped the same way when the Bible and detectors read it.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Iterable, List


def enable_utf8_console() -> None:
    """Make emoji/Unicode CLI output safe on Windows legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(
                encoding="utf-8", errors="replace", line_buffering=True
            )
        except Exception:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# Conservative synonyms only. Free-form LLM attributes are useful, but a small
# map stops the most common naming drift from hiding real conflicts.
ATTRIBUTE_SYNONYMS = {
    "eye colour": "eye_color",
    "eye color": "eye_color",
    "eye colours": "eye_color",
    "eye colors": "eye_color",
    "eyes": "eye_color",
    "hair colour": "hair_color",
    "hair color": "hair_color",
    "hair": "hair_color",
    "birth place": "birthplace",
    "birth_place": "birthplace",
    "job": "occupation",
    "profession": "occupation",
    "role": "occupation",
    "clothing": "attire",
    "outfit": "attire",
    "gown": "attire",
    "dress": "attire",
    "setting": "location",
    "venue": "location",
    "place": "location",
    "sister of": "sister",
    "brother of": "brother",
    "mother of": "mother",
    "father of": "father",
    "spouse of": "spouse",
    "owner": "owner",
    "ownership": "owner",
    "marital status": "marital_status",
    "marital-status": "marital_status",
}

# Names that are parser/section labels rather than story entities.
NOISE_ENTITY_PATTERNS = [
    re.compile(r"^(?:episode|ep|scene)\s*#?\s*\d+$", re.I),
    re.compile(r"^(?:timeline|actions?|dialogue|speaker|camera|sound(?:\s*fx)?|"
               r"script|screenplay|unknown|none|n/?a)$", re.I),
]


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_attribute(attribute: Any) -> str:
    """Return a stable snake_case attribute key."""
    raw = _collapse_whitespace(str(attribute or "")).lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    raw = re.sub(r"[^a-z0-9_]", "", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    spaced = raw.replace("_", " ")
    return ATTRIBUTE_SYNONYMS.get(spaced, raw)


def normalize_value(value: Any) -> str:
    """Normalize a fact value for equality comparison."""
    text = str(value or "").strip().lower()
    text = (
        text.replace('"', "")
        .replace("'", "")
        .replace("\u2019", "")
        .replace("\u201c", "")
        .replace("\u201d", "")
    )
    text = re.sub(r"[^\w\s]", " ", text)
    return _collapse_whitespace(text)


def normalize_text_for_matching(text: Any) -> str:
    """Normalize screenplay/fact text for verbatim substring matching."""
    text = str(text or "")
    text = (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    return _collapse_whitespace(text).lower()


def normalize_name(name: Any) -> str:
    """Normalize a character/entity name for case-insensitive lookup."""
    return _collapse_whitespace(str(name or "")).lower()


def is_noise_entity(name: Any) -> bool:
    """True when a name is a section label rather than a story entity."""
    clean = _collapse_whitespace(str(name or ""))
    if not clean:
        return True
    return any(pattern.match(clean) for pattern in NOISE_ENTITY_PATTERNS)


def clean_aliases(entity: str, aliases: Any) -> List[str]:
    """Strip, deduplicate, and remove self-references from an alias list."""
    if isinstance(aliases, str):
        candidates: Iterable[Any] = [aliases]
    elif isinstance(aliases, (list, tuple, set)):
        candidates = aliases
    else:
        candidates = []

    entity_key = normalize_name(entity)
    result: List[str] = []
    seen = {entity_key}
    for alias in candidates:
        clean = _collapse_whitespace(str(alias or ""))
        key = normalize_name(clean)
        if not clean or key in seen or is_noise_entity(clean):
            continue
        seen.add(key)
        result.append(clean)
    return result
