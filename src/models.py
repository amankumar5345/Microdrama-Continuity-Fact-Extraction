"""
src/models.py
-------------
Structured data models for Continuity Checker.
Uses Python dataclasses for lightweight, zero-overhead, minimal-dependency data representation.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum


class FactCategory(str, Enum):
    IDENTITY = "identity"
    RELATIONSHIP = "relationship"
    STATUS = "status"
    OBJECT = "object"
    PLACE = "place"
    TIMELINE = "timeline"


class Reliability(str, Enum):
    STATED = "stated"
    LIE = "lie"
    FLASHBACK = "flashback"
    HYPOTHETICAL = "hypothetical"
    JOKE = "joke"


@dataclass
class ScriptEvent:
    """Represents a single timed dialogue, action, or camera event in a scene."""
    event_type: str  # 'dialogue', 'action', 'camera', 'sound'
    start_time: str  # e.g. "00:11.30" or "00:11"
    end_time: str
    speaker: Optional[str] = None  # Character name if dialogue
    tone: Optional[str] = None     # Parenthetical direction, e.g. "Cold, Commanding"
    text: str = ""                # The verbatim line or description


@dataclass
class Scene:
    """Represents a parsed scene in a screenplay."""
    scene_number: int
    heading: str
    start_time: str
    end_time: str
    events: List[ScriptEvent] = field(default_factory=list)


@dataclass
class Episode:
    """Represents an entire parsed screenplay episode."""
    number: int
    logline: str
    continuity_notes: str
    scenes: List[Scene] = field(default_factory=list)
    raw_text: str = ""

    def get_all_events(self) -> List[ScriptEvent]:
        all_ev = []
        for s in self.scenes:
            all_ev.extend(s.events)
        return all_ev


@dataclass
class Fact:
    """
    Represents an extracted continuity fact.
    Strictly requires a verbatim quote and timestamp from the screenplay.
    """
    entity: str
    aliases: List[str]
    category: str  # identity, relationship, status, object, place, timeline
    attribute: str
    value: str
    reliability: str  # stated, lie, flashback, hypothetical
    timestamp: str
    quote: str
    episode: int
    scene: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("scene") is None:
            d.pop("scene", None)
        return d


@dataclass
class Contradiction:
    """
    Represents a detected contradiction or anomaly between two facts across episodes.
    """
    contradiction_id: str
    entity: str
    attribute: str
    category: str
    severity: str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    fact_a: Fact
    fact_b: Fact
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "entity": self.entity,
            "attribute": self.attribute,
            "category": self.category,
            "severity": self.severity,
            "explanation": self.explanation,
            "fact_a": self.fact_a.to_dict(),
            "fact_b": self.fact_b.to_dict(),
        }
