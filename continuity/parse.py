"""
continuity/parse.py
-------------------
Splits microdrama screenplays into episodes, scenes, and lines with timestamps.
Handles odd formatting without crashing.
Outputs data/episodes.json with records: {ep, scene, timestamp, speaker, text}
Prints counts of episodes, scenes, and lines, and lists any unparseable lines.
"""

import sys
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

try:
    from continuity.textutil import enable_utf8_console
except ModuleNotFoundError:  # allow `python continuity/parse.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from continuity.textutil import enable_utf8_console

enable_utf8_console()
logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_JSON_1 = DATA_DIR / "episodes.json"
OUTPUT_JSON_2 = BASE_DIR.parent / "data" / "episodes.json"

# Regex patterns for screenplay structures
_RE_EP_START = re.compile(r"^(?:EPISODE(?:\s+NUMBER)?\s*:\s*(?:Episode\s+)?(\d+)|#+\s*Episode\s+(\d+))", re.I)
_RE_SCENE_START = re.compile(r"^(?:SCENE\s+(\d+)|#+\s*Scene\s+(\d+))", re.I)
_RE_SCENE_HEADING = re.compile(r"^Scene\s+heading\s*:\s*(.+)", re.I)
_RE_SCENE_START_TIME = re.compile(r"^Scene\s+start\s*:\s*([0-9:.,]+)", re.I)
_RE_SCENE_END_TIME = re.compile(r"^Scene\s+end\s*:\s*([0-9:.,]+)", re.I)

# Timestamp block formats
_RE_TIMING_BLOCK = re.compile(r"Start:\s*[\(\[]([0-9:.,]+)[\)\]]\s*\|\s*End:\s*[\(\[]([0-9:.,]+)[\)\]]", re.I)
_RE_INLINE_TS = re.compile(r"^\[([0-9:.,]+)\]\s*(?:([A-Z0-9_\s\.\(\)\'\-]+?):\s*)?(.+)$")
_RE_ARROW_TS = re.compile(r"^([0-9:.,]+)\s*-->\s*([0-9:.,]+)")
_RE_BLOCK_HEADER = re.compile(r"^\*\*(.+?)\*\*:?\s*$")

# Known non-line noise / metadata patterns
_RE_IGNORED_HEADERS = re.compile(
    r"^(?:EPISODE\s+LOGLINE|CONTINUITY\s+NOTES|---\s*SCRIPT|Actions\s+and\s+dialogue|Scene\s+heading|Scene\s+start|Scene\s+end)",
    re.I
)


def _clean_text(s: str) -> str:
    """Normalize quotes and extraneous whitespace."""
    s = s.replace('"', '"').replace('"', '"').replace("'", "'").replace("'", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_screenplay_text(raw_text: str, default_ep: int = 1) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    """
    Parses screenplay text into a list of line dicts:
    [{ep, scene, timestamp, speaker, text}]
    Returns (records, metrics, unparsed_lines).
    """
    lines = raw_text.splitlines()
    records: List[Dict[str, Any]] = []
    unparsed: List[str] = []

    current_ep = default_ep
    current_scene = 1
    current_timestamp = "00:00"

    episodes_seen: Set[int] = set()
    scenes_seen: Set[Tuple[int, int]] = set()

    i = 0
    n = len(lines)

    while i < n:
        raw_line = lines[i]
        line = raw_line.strip()

        if not line:
            i += 1
            continue

        # 1. Episode Header
        ep_m = _RE_EP_START.match(line)
        if ep_m:
            ep_val = ep_m.group(1) or ep_m.group(2)
            if ep_val:
                current_ep = int(ep_val)
            episodes_seen.add(current_ep)
            current_scene = 1
            i += 1
            continue

        # 2. Scene Header
        sc_m = _RE_SCENE_START.match(line)
        if sc_m:
            sc_val = sc_m.group(1) or sc_m.group(2)
            if sc_val:
                current_scene = int(sc_val)
            episodes_seen.add(current_ep)
            scenes_seen.add((current_ep, current_scene))
            i += 1
            continue

        # 3. Scene Timings / Metadata
        if _RE_SCENE_START_TIME.match(line):
            m = _RE_SCENE_START_TIME.match(line)
            current_timestamp = m.group(1).strip()
            i += 1
            continue

        if _RE_IGNORED_HEADERS.match(line):
            i += 1
            continue

        # 4. Arrow SRT format: 00:01:13.500 --> 00:01:14.300
        arrow_m = _RE_ARROW_TS.match(line)
        if arrow_m:
            ts = arrow_m.group(1).strip()
            current_timestamp = ts
            i += 1
            if i < n:
                nxt = lines[i].strip()
                if nxt and not nxt.startswith("--"):
                    spk = "SPEAKER"
                    txt = nxt
                    if ":" in nxt:
                        parts = nxt.split(":", 1)
                        spk = parts[0].strip()
                        txt = parts[1].strip()
                    records.append({
                        "ep": current_ep,
                        "scene": current_scene,
                        "timestamp": current_timestamp,
                        "speaker": spk,
                        "text": _clean_text(txt),
                    })
                    episodes_seen.add(current_ep)
                    scenes_seen.add((current_ep, current_scene))
                    i += 1
                    continue
            continue

        # 5. Inline timestamp: [00:32] MAYA: My sister Priya is in jail.
        inline_m = _RE_INLINE_TS.match(line)
        if inline_m:
            ts = inline_m.group(1).strip()
            spk = (inline_m.group(2) or "SPEAKER").strip()
            txt = inline_m.group(3).strip().strip('"')
            current_timestamp = ts
            records.append({
                "ep": current_ep,
                "scene": current_scene,
                "timestamp": current_timestamp,
                "speaker": spk,
                "text": _clean_text(txt),
            })
            episodes_seen.add(current_ep)
            scenes_seen.add((current_ep, current_scene))
            i += 1
            continue

        # 6. Block Header: **LADY JULIANA (Heartbroken):** or **ACTION:** or **CAMERA:**
        blk_m = _RE_BLOCK_HEADER.match(line)
        if blk_m:
            header = blk_m.group(1).strip()
            # Clean speaker name & tone
            char_m = re.match(r"^([^\(]+)(?:\((.*)\))?", header)
            speaker_name = (char_m.group(1).strip() if char_m else header).rstrip(":")

            # Look for timing line (Start: ... | End: ...)
            ev_ts = current_timestamp
            i += 1
            while i < n and not lines[i].strip():
                i += 1

            if i < n:
                time_m = _RE_TIMING_BLOCK.search(lines[i].strip())
                if time_m:
                    ev_ts = time_m.group(1).strip()
                    current_timestamp = ev_ts
                    i += 1

            # Accumulate content body lines
            content_parts = []
            while i < n:
                c_line = lines[i].strip()
                if not c_line or c_line.startswith("**") or _RE_SCENE_START.match(c_line) or _RE_EP_START.match(c_line):
                    break
                content_parts.append(c_line)
                i += 1

            body_text = " ".join(content_parts).strip().strip('"')
            if body_text:
                records.append({
                    "ep": current_ep,
                    "scene": current_scene,
                    "timestamp": ev_ts,
                    "speaker": speaker_name,
                    "text": _clean_text(body_text),
                })
                episodes_seen.add(current_ep)
                scenes_seen.add((current_ep, current_scene))
            continue

        # If line contains dialogue format without bold: SPEAKER: "Dialogue"
        colon_m = re.match(r"^([A-Z0-9_\s\.\'\-]{2,25}):\s*[\"\']?(.+)[\"\']?$", line)
        if colon_m:
            records.append({
                "ep": current_ep,
                "scene": current_scene,
                "timestamp": current_timestamp,
                "speaker": colon_m.group(1).strip(),
                "text": _clean_text(colon_m.group(2).strip().strip('"')),
            })
            episodes_seen.add(current_ep)
            scenes_seen.add((current_ep, current_scene))
            i += 1
            continue

        # Track unparsed lines (excluding separators like ---)
        if not line.startswith("---") and not line.startswith("==="):
            unparsed.append(f"[Line {i+1}] {line}")
        i += 1

    # Ensure default episode registered if records exist
    if records and not episodes_seen:
        episodes_seen.add(current_ep)
    if records and not scenes_seen:
        scenes_seen.add((current_ep, current_scene))

    metrics = {
        "episodes": len(episodes_seen),
        "scenes": len(scenes_seen),
        "lines": len(records),
    }

    return records, metrics, unparsed


def parse_files(file_paths: List[Path], output_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Parses multiple screenplay files into data/episodes.json.
    """
    all_records: List[Dict[str, Any]] = []
    total_episodes: Set[int] = set()
    total_scenes: Set[Tuple[int, int]] = set()
    all_unparsed: List[str] = []

    for idx, f in enumerate(sorted(file_paths), 1):
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                raw_text = fh.read()
            recs, met, unp = parse_screenplay_text(raw_text, default_ep=idx)
            all_records.extend(recs)
            for r in recs:
                total_episodes.add(r["ep"])
                total_scenes.add((r["ep"], r["scene"]))
            all_unparsed.extend([f"[{f.name}] {u}" for u in unp])
        except Exception as e:
            all_unparsed.append(f"[{f.name}] Error reading file: {e}")

    # Write output to primary and secondary data paths
    out_file = output_path or OUTPUT_JSON_1
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    # Also sync to project root data/ if different
    try:
        OUTPUT_JSON_2.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_JSON_2, "w", encoding="utf-8") as f:
            json.dump(all_records, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    # Print requested statistics
    print("\n" + "=" * 60)
    print("🎬 SCREENPLAY PARSER SUMMARY")
    print("=" * 60)
    print(f"  Episodes parsed : {len(total_episodes)}")
    print(f"  Scenes parsed   : {len(total_scenes)}")
    print(f"  Lines parsed    : {len(all_records)}")
    print(f"  Output saved to : {out_file}")

    print("\n📋 Unparsed Lines:")
    if not all_unparsed:
        print("  None — 100% of screenplay text cleanly parsed!")
    else:
        print(f"  Total unparsed lines: {len(all_unparsed)}")
        for line in all_unparsed[:10]:
            print(f"    - {line}")
        if len(all_unparsed) > 10:
            print(f"    ... and {len(all_unparsed) - 10} more.")
    print("=" * 60 + "\n")

    return all_records


def main():
    """CLI execution for parse.py."""
    args = sys.argv[1:]
    target_files: List[Path] = []

    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                target_files.append(p)
            elif p.is_dir():
                target_files.extend(list(p.glob("*.txt")))
    else:
        # Default: search continuity/data/*.txt then data/*.txt
        if DATA_DIR.exists():
            target_files = list(DATA_DIR.glob("*.txt"))
        if not target_files:
            fallback = BASE_DIR.parent / "data"
            if fallback.exists():
                target_files = list(fallback.glob("*.txt"))

    if not target_files:
        print("No .txt screenplay files found to parse.")
        sys.exit(1)

    parse_files(target_files)


if __name__ == "__main__":
    main()
