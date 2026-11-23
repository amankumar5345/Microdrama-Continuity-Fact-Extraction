"""
run_all.py
----------
Orchestrates the complete Continuity Checker pipeline end-to-end:
1. Parse Screenplays (parse.py) -> data/episodes.json
2. Extract Facts (extract.py)   -> outputs/facts_epN.json (with verbatim quote filtering)
3. Build Series Bible (bible.py)-> outputs/alias_map.json & outputs/bible.json
4. Detect Candidates (detect.py)-> outputs/candidates.json (Pass 1: value conflicts, Pass 2: state errors)
5. Judge Contradictions (judge.py) -> outputs/flags.csv & outputs/judgments.json

Prints a clear summary of:
- Facts extracted
- Quotes dropped
- Candidates detected
- Flags kept (real_error & unclear vs filtered)
"""

import re
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import List, Optional

# Add project root to sys.path so continuity modules import cleanly
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from continuity.parse import parse_files, DATA_DIR as PARSE_DATA_DIR
from continuity.extract import extract_episode, find_screenplay_file
from continuity.bible import (
    load_all_fact_files,
    gather_entities_and_aliases,
    get_or_create_alias_map,
    build_series_bible,
    save_series_bible,
)
from continuity.detect import (
    load_bible,
    pass_1_value_conflicts,
    pass_2_state_errors,
    save_candidates,
)
from continuity.judge import (
    load_candidates,
    judge_candidate,
    export_flags_csv,
    export_judgments_json,
    FLAGS_CSV_1,
    JUDGMENTS_JSON_1,
)
from continuity.textutil import enable_utf8_console

enable_utf8_console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_all")


def discover_episode_numbers() -> List[int]:
    """Find every episode number available in continuity/data (or root data)."""
    candidate_dirs = [PARSE_DATA_DIR, ROOT_DIR / "data"]
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        numbers = set()
        for path in directory.glob("*.txt"):
            match = re.search(r"(\d+)", path.name)
            if match:
                numbers.add(int(match.group(1)))
        if numbers:
            return sorted(numbers)
    return []


def parse_arguments():
    parser = argparse.ArgumentParser(description="Run complete Continuity Checker pipeline.")
    parser.add_argument(
        "--eps",
        nargs="+",
        type=int,
        help="Specific episode numbers to process, e.g. --eps 1 2 3 (default: all available)",
    )
    parser.add_argument(
        "--skip-parse",
        action="store_true",
        help="Skip screenplay parsing stage if data/episodes.json already exists",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip fact extraction if outputs/facts_ep*.json already exist",
    )
    parser.add_argument(
        "--rebuild-aliases",
        action="store_true",
        help="Force LLM to re-propose alias mappings",
    )
    parser.add_argument(
        "--force-extract",
        action="store_true",
        help="Re-extract facts even when outputs/facts_epN.json already exists",
    )
    return parser.parse_args()


def run_pipeline(
    eps: Optional[List[int]] = None,
    skip_parse: bool = False,
    skip_extract: bool = False,
    rebuild_aliases: bool = False,
    force_extract: bool = False,
):
    start_time = time.time()
    print("\n" + "=" * 70)
    print("🚀 STARTING CONTINUITY CHECKER FULL PIPELINE")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # STAGE 1: Screenplay Parsing
    # -------------------------------------------------------------------------
    print("\n[STAGE 1/5] Screenplay Parsing...")
    episodes_parsed_count = 0
    scenes_parsed_count = 0
    lines_parsed_count = 0

    if not skip_parse:
        target_files = list(PARSE_DATA_DIR.glob("*.txt"))
        if not target_files:
            fallback = ROOT_DIR / "data"
            if fallback.exists():
                target_files = list(fallback.glob("*.txt"))

        if target_files:
            # Always parse every episode: parsing is fast, and --eps should only
            # limit extraction/judgment, not truncate the global episodes.json.
            records = parse_files(target_files)
            lines_parsed_count = len(records)
            eps_seen = {r["ep"] for r in records}
            scenes_seen = {(r["ep"], r["scene"]) for r in records}
            episodes_parsed_count = len(eps_seen)
            scenes_parsed_count = len(scenes_seen)
        else:
            logger.warning("No screenplay .txt files found to parse.")
    else:
        logger.info("Skipping Stage 1 (Screenplay Parsing) as requested.")

    # -------------------------------------------------------------------------
    # STAGE 2: Fact Extraction & Verbatim Verification
    # -------------------------------------------------------------------------
    print("\n[STAGE 2/5] Fact Extraction & Verbatim Quote Verification...")
    total_facts_extracted = 0
    total_quotes_dropped = 0
    cached_episodes = 0
    extracted_episodes = 0

    if not skip_extract:
        target_episodes = sorted(set(eps)) if eps else discover_episode_numbers()
        if not target_episodes:
            logger.warning("No episode files found; skipping extraction.")
        for ep_num in target_episodes:
            screenplay_path = find_screenplay_file(ep_num)
            if not screenplay_path:
                logger.warning(f"Screenplay file for Episode {ep_num} not found. Skipping.")
                continue

            res = extract_episode(ep_num, screenplay_path, force=force_extract)
            if res.get("error"):
                logger.error("Episode %d extraction failed: %s", ep_num, res["error"])
            if res.get("cached"):
                cached_episodes += 1
            elif not res.get("error"):
                extracted_episodes += 1
            total_facts_extracted += res.get("facts_count", 0)
            total_quotes_dropped += res.get("dropped_count", 0)
    else:
        logger.info("Skipping Stage 2 (Fact Extraction) as requested. Reading existing facts files...")
        all_fact_files = load_all_fact_files()
        cached_episodes = len(all_fact_files)
        for fd in all_fact_files:
            total_facts_extracted += len(fd.get("facts", []))
            total_quotes_dropped += fd.get("dropped_count", 0)

    # -------------------------------------------------------------------------
    # STAGE 3: Series Bible & Canonical Alias Mapping
    # -------------------------------------------------------------------------
    print("\n[STAGE 3/5] Building Series Bible & Normalizing Aliases...")
    all_facts_data = load_all_fact_files()
    entity_aliases = gather_entities_and_aliases(all_facts_data)
    alias_map = get_or_create_alias_map(entity_aliases, force_rebuild=rebuild_aliases)
    bible = build_series_bible(all_facts_data, alias_map)
    save_series_bible(bible)

    canonical_entities_count = len(bible)
    bible_facts_count = sum(len(entries) for attrs in bible.values() for entries in attrs.values())
    logger.info(f"Series Bible compiled: {canonical_entities_count} canonical entities, {bible_facts_count} facts.")

    # -------------------------------------------------------------------------
    # STAGE 4: Contradiction Candidate Detection
    # -------------------------------------------------------------------------
    print("\n[STAGE 4/5] Contradiction Candidate Detection (Pass 1 & Pass 2)...")
    v_conflicts = pass_1_value_conflicts(bible)
    s_errors = pass_2_state_errors(bible)
    candidates = v_conflicts + s_errors
    save_candidates(candidates)

    total_candidates = len(candidates)
    logger.info(f"Candidates Flagged: {total_candidates} (Value Conflicts: {len(v_conflicts)}, State Errors: {len(s_errors)})")

    # -------------------------------------------------------------------------
    # STAGE 5: Contradiction Judgment & Flag Export
    # -------------------------------------------------------------------------
    print("\n[STAGE 5/5] LLM Judgment & Severity Ranking...")
    judged_records = []
    flags_kept_count = 0
    filtered_count = 0

    if candidates:
        for idx, cand in enumerate(candidates, 1):
            logger.info(f"Judging candidate [{idx}/{len(candidates)}]: {cand.get('entity')} ({cand.get('attribute')})...")
            rec = judge_candidate(cand)
            judged_records.append(rec)
            if rec.get("status") == "FLAG":
                flags_kept_count += 1
            else:
                filtered_count += 1

        export_flags_csv(judged_records, FLAGS_CSV_1)
        export_judgments_json(judged_records, JUDGMENTS_JSON_1)
    else:
        logger.info("No candidates to judge. Writing empty flag artifacts.")
        export_flags_csv([], FLAGS_CSV_1)
        export_judgments_json([], JUDGMENTS_JSON_1)

    duration = time.time() - start_time

    # -------------------------------------------------------------------------
    # FINAL METRIC SUMMARY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("🏁 PIPELINE EXECUTION SUMMARY")
    print("=" * 70)
    print(f"  ⏱️  Total Duration          : {duration:.2f}s")
    if lines_parsed_count > 0:
        print(f"  📄 Screenplay Lines Parsed : {lines_parsed_count} across {episodes_parsed_count} ep(s) and {scenes_parsed_count} scene(s)")
    print(f"  ✅ Facts Extracted         : {total_facts_extracted}")
    print(f"  ♻️  Episodes Reused/Cached  : {cached_episodes}")
    print(f"  🧠 Episodes Freshly Extracted: {extracted_episodes}")
    print(f"  🗑️  Quotes Dropped (Halluc) : {total_quotes_dropped}")
    print(f"  👤 Canonical Entities      : {canonical_entities_count}")
    print(f"  🔍 Contradiction Candidates: {total_candidates}")
    print(f"     - Value Conflicts       : {len(v_conflicts)}")
    print(f"     - State Errors          : {len(s_errors)}")
    print(f"  🚩 Flags Kept for Review   : {flags_kept_count} (real_error / unclear)")
    print(f"  🛡️  Filtered Discrepancies  : {filtered_count} (legit_change / deception)")
    print("-" * 70)
    print("📁 Output Artifacts:")
    print("  - Parsed Episodes : continuity/data/episodes.json")
    print("  - Facts Directory : continuity/outputs/facts_ep*.json")
    print("  - Alias Merge Map : continuity/outputs/alias_map.json")
    print("  - Series Bible    : continuity/outputs/bible.json")
    print("  - Candidate Pairs : continuity/outputs/candidates.json")
    print("  - Reviewed Flags  : continuity/outputs/flags.csv")
    print("  - Judgments JSON  : continuity/outputs/judgments.json")
    print("=" * 70 + "\n")


def main() -> None:
    args = parse_arguments()
    run_pipeline(
        eps=args.eps,
        skip_parse=args.skip_parse,
        skip_extract=args.skip_extract,
        rebuild_aliases=args.rebuild_aliases,
        force_extract=args.force_extract,
    )


if __name__ == "__main__":
    main()
