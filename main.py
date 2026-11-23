"""
main.py
-------
Top-level entrypoint for Continuity Checker prototype.

Usage:
    python main.py
    python main.py --episodes 1-5
    python main.py --data-dir data/ --skip-llm-eval
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from src.parser import parse_screenplay
from src.extractor import extract_facts_from_episode
from src.checker import check_contradictions
from src.reporter import generate_markdown_report, generate_json_report, print_cli_summary
from src.models import Fact

# Windows legacy consoles default to cp1252, which cannot encode the emoji used
# in the CLI summary. Reconfigure defensively before any output is written.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("continuity")


def parse_args():
    parser = argparse.ArgumentParser(description="Continuity Checker for Serialized Microdramas")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Directory containing timestamped screenplay .txt files (default: data)",
    )
    parser.add_argument(
        "--episodes",
        type=str,
        default="",
        help="Range or list of episodes to check, e.g. '1-5' or '1,2,3' (default: all in data-dir)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports",
        help="Directory to save Markdown and JSON review reports (default: reports)",
    )
    parser.add_argument(
        "--skip-llm-eval",
        action="store_true",
        help="Skip LLM semantic validation step and run strict rule-based checking only",
    )
    return parser.parse_args()


def get_episode_files(data_dir: Path, episode_spec: str) -> List[Path]:
    """Find and filter episode screenplay files."""
    files = sorted(list(data_dir.glob("*.txt")))
    if not files:
        return []

    if not episode_spec:
        return files

    # Parse episode numbers
    target_nums = set()
    for part in episode_spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            target_nums.update(range(int(start), int(end) + 1))
        elif part.isdigit():
            target_nums.add(int(part))

    filtered = []
    for f in files:
        # Match episode number from file name
        import re
        m = re.search(r"(\d+)", f.name)
        if m and int(m.group(1)) in target_nums:
            filtered.append(f)
    return filtered or files


def run_pipeline(data_dir_str: str = "data", episode_spec: str = "", output_dir_str: str = "reports", skip_llm_eval: bool = False):
    data_dir = Path(data_dir_str)
    output_dir = Path(output_dir_str)
    output_dir.mkdir(parents=True, exist_ok=True)

    ep_files = get_episode_files(data_dir, episode_spec)
    if not ep_files:
        logger.error(f"No screenplay files found in {data_dir.resolve()}")
        sys.exit(1)

    logger.info(f"Loaded {len(ep_files)} episode screenplay(s) for continuity analysis.")

    all_facts: List[Fact] = []
    parsed_count = 0

    # 1. Parse & Extract Facts
    for ep_file in ep_files:
        logger.info(f"Parsing episode: {ep_file.name}...")
        ep = parse_screenplay(ep_file)
        facts = extract_facts_from_episode(ep, save_to_disk=True)
        all_facts.extend(facts)
        parsed_count += 1
        logger.info(f"  -> {len(facts)} facts verified for Episode {ep.number}")

    # 2. Check for Contradictions across episodes
    logger.info(f"Running cross-episode contradiction checks on {len(all_facts)} facts...")
    contradictions = check_contradictions(all_facts, use_llm_evaluator=(not skip_llm_eval))

    # 3. Generate Reports
    md_path = output_dir / "continuity_report.md"
    json_path = output_dir / "continuity_report.json"

    generate_markdown_report(contradictions, all_facts, parsed_count, md_path)
    generate_json_report(contradictions, all_facts, parsed_count, json_path)

    # 4. Print CLI summary
    print_cli_summary(contradictions, len(all_facts), parsed_count)
    logger.info(f"Review reports successfully generated:")
    logger.info(f"  - Markdown: {md_path.resolve()}")
    logger.info(f"  - JSON:     {json_path.resolve()}")

    return contradictions, all_facts


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(
        data_dir_str=args.data_dir,
        episode_spec=args.episodes,
        output_dir_str=args.output_dir,
        skip_llm_eval=args.skip_llm_eval,
    )
