"""
src/parser.py
-------------
Parses timestamped microdrama screenplays (.txt) into structured Episode models.
Supports:
1. Block-based formats (CAMERA / ACTION / CHARACTER with Start: (mm:ss) | End: (mm:ss))
2. Inline formats ([mm:ss] SPEAKER: dialogue)
3. Verbatim quote validation and verification against source screenplay.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple, Union
from src.models import Episode, Scene, ScriptEvent


_RE_EP_NUM = re.compile(r"EPISODE(?:\s+NUMBER)?\s*:\s*(?:Episode\s+)?(\d+)", re.I)
_RE_LOGLINE = re.compile(r"EPISODE\s+LOGLINE\s*:\s*(.+)", re.I)
_RE_CONTINUITY = re.compile(r"CONTINUITY\s+NOTES\s*:\s*(.+)", re.I)

_RE_SCENE_HEADER = re.compile(r"^SCENE\s+(\d+)", re.I)
_RE_SCENE_HEADING = re.compile(r"Scene\s+heading\s*:\s*(.+)", re.I)
_RE_SCENE_START = re.compile(r"Scene\s+start\s*:\s*([0-9:.,]+)", re.I)
_RE_SCENE_END = re.compile(r"Scene\s+end\s*:\s*([0-9:.,]+)", re.I)

_RE_BLOCK_HEADER = re.compile(r"^\*\*(.+?)\*\*:?\s*$", re.I)
_RE_BLOCK_TIMING = re.compile(r"Start:\s*[\(\[]([0-9:.,]+)[\)\]]\s*\|\s*End:\s*[\(\[]([0-9:.,]+)[\)\]]", re.I)
_RE_INLINE_LINE = re.compile(r"^\[([0-9:.,]+)\]\s*([^:]+):\s*(.+)$")


def _clean_str(s: str) -> str:
    """Normalize whitespace and quotes."""
    s = s.replace('"', '"').replace('"', '"').replace("'", "'").replace("'", "'")
    return re.sub(r"\s+", " ", s).strip()


def parse_screenplay(source: Union[str, Path]) -> Episode:
    """
    Parse a screenplay file or raw string into an Episode object.
    """
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        path = Path(source)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
    else:
        raw_text = str(source)

    # Extract top-level metadata
    ep_num_match = _RE_EP_NUM.search(raw_text)
    ep_number = int(ep_num_match.group(1)) if ep_num_match else 1

    logline_match = _RE_LOGLINE.search(raw_text)
    logline = logline_match.group(1).strip() if logline_match else ""

    cont_match = _RE_CONTINUITY.search(raw_text)
    continuity_notes = cont_match.group(1).strip() if cont_match else ""

    scenes: List[Scene] = []
    current_scene: Optional[Scene] = None

    lines = raw_text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # Check for Scene start
        scene_match = _RE_SCENE_HEADER.match(line)
        if scene_match:
            if current_scene:
                scenes.append(current_scene)
            s_num = int(scene_match.group(1))
            current_scene = Scene(
                scene_number=s_num,
                heading="",
                start_time="00:00.00",
                end_time="00:00.00",
                events=[],
            )
            i += 1
            continue

        if current_scene:
            hdg_m = _RE_SCENE_HEADING.match(line)
            if hdg_m:
                current_scene.heading = hdg_m.group(1).strip()
                i += 1
                continue

            start_m = _RE_SCENE_START.match(line)
            if start_m:
                current_scene.start_time = start_m.group(1).strip()
                i += 1
                continue

            end_m = _RE_SCENE_END.match(line)
            if end_m:
                current_scene.end_time = end_m.group(1).strip()
                i += 1
                continue

            # Check for block event, e.g. **CAMERA:** or **LADY JULIANA (Heartbroken):**
            blk_m = _RE_BLOCK_HEADER.match(line)
            if blk_m:
                header_content = blk_m.group(1).strip()
                # Parse event type and speaker
                if header_content.upper().startswith("CAMERA"):
                    ev_type = "camera"
                    speaker = None
                    tone = None
                elif header_content.upper().startswith("ACTION"):
                    ev_type = "action"
                    speaker = None
                    tone = None
                elif header_content.upper().startswith("SOUND"):
                    ev_type = "sound"
                    speaker = None
                    tone = None
                else:
                    ev_type = "dialogue"
                    # Extract character and tone, e.g. "MATRIARCH (Cold, Commanding)"
                    char_m = re.match(r"^([^\(]+)(?:\((.*)\))?", header_content)
                    if char_m:
                        speaker = char_m.group(1).strip()
                        tone = char_m.group(2).strip() if char_m.group(2) else None
                    else:
                        speaker = header_content
                        tone = None

                # Look for Start / End timing line
                ev_start = "00:00"
                ev_end = "00:00"
                i += 1
                while i < n and not lines[i].strip():
                    i += 1

                if i < n:
                    time_m = _RE_BLOCK_TIMING.search(lines[i].strip())
                    if time_m:
                        ev_start = time_m.group(1).strip()
                        ev_end = time_m.group(2).strip()
                        i += 1

                # Gather content text lines until next blank line or next block
                content_lines = []
                while i < n:
                    c_line = lines[i].strip()
                    if not c_line or c_line.startswith("**") or _RE_SCENE_HEADER.match(c_line) or c_line.startswith("---"):
                        break
                    content_lines.append(c_line)
                    i += 1

                body_text = " ".join(content_lines).strip()
                # Strip wrapping quotes if dialogue
                if body_text.startswith('"') and body_text.endswith('"'):
                    body_text = body_text[1:-1].strip()

                current_scene.events.append(
                    ScriptEvent(
                        event_type=ev_type,
                        start_time=ev_start,
                        end_time=ev_end,
                        speaker=speaker,
                        tone=tone,
                        text=body_text,
                    )
                )
                continue

            # Check for inline dialogue: [00:32] MAYA: My sister Priya is in jail.
            inline_m = _RE_INLINE_LINE.match(line)
            if inline_m:
                ts = inline_m.group(1).strip()
                spk = inline_m.group(2).strip()
                txt = inline_m.group(3).strip().strip('"')
                current_scene.events.append(
                    ScriptEvent(
                        event_type="dialogue",
                        start_time=ts,
                        end_time=ts,
                        speaker=spk,
                        text=txt,
                    )
                )
                i += 1
                continue

        i += 1

    if current_scene:
        scenes.append(current_scene)

    return Episode(
        number=ep_number,
        logline=logline,
        continuity_notes=continuity_notes,
        scenes=scenes,
        raw_text=raw_text,
    )


def verify_quote_in_screenplay(quote: str, raw_text: str) -> bool:
    """
    Verifies if a quote exists verbatim (accounting for punctuation and whitespace variations)
    in the screenplay raw text.
    """
    clean_q = _clean_str(quote)
    clean_src = _clean_str(raw_text)
    if not clean_q:
        return False
    return clean_q.lower() in clean_src.lower()


def find_quote_event(quote: str, episode: Episode) -> Optional[ScriptEvent]:
    """
    Finds the specific ScriptEvent that contains the verbatim quote.
    """
    clean_q = _clean_str(quote).lower()
    for ev in episode.get_all_events():
        if clean_q in _clean_str(ev.text).lower():
            return ev
    return None
