"""
continuity/judge.py
-------------------
Judges candidate contradiction pairs via call_llm() using prompts/judge.txt.
- Records verdict, severity, and reason.
- Keeps 'real_error' and 'unclear' as active FLAGS.
- Marks 'legit_change' and 'deception' as FILTERED (kept in file).
- Exports outputs/flags.csv sorted by severity and outputs/judgments.json.
"""

import sys
import os
import csv
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from continuity.llm import call_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Base paths
BASE_DIR = Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "judge.txt"
OUTPUTS_DIR = BASE_DIR / "outputs"
ROOT_OUTPUTS_DIR = BASE_DIR.parent / "outputs"

CANDIDATES_FILE_1 = OUTPUTS_DIR / "candidates.json"
CANDIDATES_FILE_2 = ROOT_OUTPUTS_DIR / "candidates.json"

FLAGS_CSV_1 = OUTPUTS_DIR / "flags.csv"
FLAGS_CSV_2 = ROOT_OUTPUTS_DIR / "flags.csv"

JUDGMENTS_JSON_1 = OUTPUTS_DIR / "judgments.json"
JUDGMENTS_JSON_2 = ROOT_OUTPUTS_DIR / "judgments.json"

SEVERITY_ORDER = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
}

VALID_VERDICTS = {"real_error", "unclear", "legit_change", "deception"}


def load_candidates() -> List[Dict[str, Any]]:
    """Loads candidate pairs from outputs/candidates.json."""
    for p in [CANDIDATES_FILE_1, CANDIDATES_FILE_2]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    candidates = json.load(f)
                    logger.info(f"Loaded {len(candidates)} candidates from {p}")
                    return candidates
            except Exception as e:
                logger.warning(f"Failed to read candidates from {p}: {e}")
    return []


def format_judge_prompt(candidate: Dict[str, Any]) -> str:
    """Safely formats prompt from prompts/judge.txt without brace collision."""
    if not PROMPT_FILE.exists():
        fallback_prompt = BASE_DIR.parent / "prompts" / "judge.txt"
        prompt_path = fallback_prompt if fallback_prompt.exists() else PROMPT_FILE
    else:
        prompt_path = PROMPT_FILE

    if not prompt_path.exists():
        raise FileNotFoundError(f"Judge prompt template not found at {PROMPT_FILE}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    fact_a = candidate.get("fact_a", {})
    fact_b = candidate.get("fact_b", {})

    replacements = {
        "{candidate_type}": str(candidate.get("type", "conflict")),
        "{entity}": str(candidate.get("entity", "")),
        "{attribute}": str(candidate.get("attribute", "")),
        "{ep_a}": str(fact_a.get("ep", "")),
        "{timestamp_a}": str(fact_a.get("timestamp", "")),
        "{value_a}": str(fact_a.get("value", "")),
        "{quote_a}": str(fact_a.get("quote", "")),
        "{ep_b}": str(fact_b.get("ep", "")),
        "{timestamp_b}": str(fact_b.get("timestamp", "")),
        "{value_b}": str(fact_b.get("value", "")),
        "{quote_b}": str(fact_b.get("quote", "")),
    }

    has_placeholders = any(k in template for k in replacements.keys())
    if has_placeholders:
        prompt = template
        for k, v in replacements.items():
            prompt = prompt.replace(k, v)
        return prompt

    # Fallback if user pasted a custom prompt without matching placeholders
    candidate_summary = (
        f"\nCANDIDATE: {candidate.get('entity')} ({candidate.get('attribute')})\n"
        f"FACT A (Ep {fact_a.get('ep')} @ {fact_a.get('timestamp')}): \"{fact_a.get('quote')}\" (Value: {fact_a.get('value')})\n"
        f"FACT B (Ep {fact_b.get('ep')} @ {fact_b.get('timestamp')}): \"{fact_b.get('quote')}\" (Value: {fact_b.get('value')})\n"
    )
    return f"{template.strip()}\n\n{candidate_summary}"


def judge_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Judges a single candidate pair via call_llm()."""
    prompt = format_judge_prompt(candidate)
    
    try:
        resp = call_llm(prompt, json_mode=True)
    except Exception as e:
        logger.warning(f"Error calling LLM for candidate {candidate.get('entity')}: {e}")
        resp = {}

    if not isinstance(resp, dict):
        resp = {}

    raw_verdict = str(resp.get("verdict", "unclear")).strip().lower()
    if raw_verdict not in VALID_VERDICTS:
        raw_verdict = "unclear"

    raw_severity = str(resp.get("severity", "MEDIUM")).strip().upper()
    if raw_severity not in SEVERITY_ORDER:
        raw_severity = "MEDIUM"

    reason = str(resp.get("reason", "No reason provided.")).strip()

    # Keep real_error and unclear as FLAG; mark legit_change and deception as FILTERED
    status = "FLAG" if raw_verdict in ("real_error", "unclear") else "FILTERED"

    fact_a = candidate.get("fact_a", {})
    fact_b = candidate.get("fact_b", {})

    record = {
        "status": status,
        "verdict": raw_verdict,
        "severity": raw_severity,
        "severity_rank": SEVERITY_ORDER.get(raw_severity, 99),
        "candidate_type": candidate.get("type", "value_conflict"),
        "entity": candidate.get("entity", ""),
        "attribute": candidate.get("attribute", ""),
        "ep_a": fact_a.get("ep", ""),
        "timestamp_a": fact_a.get("timestamp", ""),
        "value_a": fact_a.get("value", ""),
        "quote_a": fact_a.get("quote", ""),
        "ep_b": fact_b.get("ep", ""),
        "timestamp_b": fact_b.get("timestamp", ""),
        "value_b": fact_b.get("value", ""),
        "quote_b": fact_b.get("quote", ""),
        "reason": reason,
    }

    return record


def export_flags_csv(records: List[Dict[str, Any]], output_path: Path) -> None:
    """Exports records sorted by severity to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Sort: active FLAGS first, then by severity rank (CRITICAL=1, HIGH=2, etc.), then episode
    sorted_records = sorted(
        records,
        key=lambda r: (
            0 if r["status"] == "FLAG" else 1,
            r["severity_rank"],
            int(r["ep_a"]) if str(r["ep_a"]).isdigit() else 0,
        )
    )

    fieldnames = [
        "severity",
        "verdict",
        "status",
        "candidate_type",
        "entity",
        "attribute",
        "ep_a",
        "timestamp_a",
        "value_a",
        "quote_a",
        "ep_b",
        "timestamp_b",
        "value_b",
        "quote_b",
        "reason",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in sorted_records:
            writer.writerow(r)

    # Also mirror to root
    try:
        FLAGS_CSV_2.parent.mkdir(parents=True, exist_ok=True)
        with open(FLAGS_CSV_2, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in sorted_records:
                writer.writerow(r)
    except Exception:
        pass

    logger.info(f"Saved {len(sorted_records)} judged records to {output_path}")


def export_judgments_json(records: List[Dict[str, Any]], output_path: Path) -> None:
    """Exports records to outputs/judgments.json."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    try:
        JUDGMENTS_JSON_2.parent.mkdir(parents=True, exist_ok=True)
        with open(JUDGMENTS_JSON_2, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def main():
    logger.info("Running Continuity Judge...")
    candidates = load_candidates()
    if not candidates:
        logger.warning("No candidates found in outputs/candidates.json. Run detect.py first!")
        sys.exit(0)

    judged_records = []
    verdict_counts = {"real_error": 0, "unclear": 0, "legit_change": 0, "deception": 0}
    status_counts = {"FLAG": 0, "FILTERED": 0}

    for idx, cand in enumerate(candidates, 1):
        logger.info(f"Judging candidate [{idx}/{len(candidates)}]: {cand.get('entity')} ({cand.get('attribute')})...")
        rec = judge_candidate(cand)
        judged_records.append(rec)

        v = rec["verdict"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        st = rec["status"]
        status_counts[st] = status_counts.get(st, 0) + 1

    # Export CSV & JSON
    export_flags_csv(judged_records, FLAGS_CSV_1)
    export_judgments_json(judged_records, JUDGMENTS_JSON_1)

    # Print summary
    print("\n" + "=" * 65)
    print("⚖️  CONTINUITY JUDGMENT SUMMARY")
    print("=" * 65)
    print(f"  Total Candidates Evaluated : {len(judged_records)}")
    print(f"  Active Flags (Human Review): {status_counts['FLAG']}")
    print(f"    - real_error             : {verdict_counts.get('real_error', 0)}")
    print(f"    - unclear                : {verdict_counts.get('unclear', 0)}")
    print(f"  Filtered Discrepancies     : {status_counts['FILTERED']}")
    print(f"    - legit_change           : {verdict_counts.get('legit_change', 0)}")
    print(f"    - deception              : {verdict_counts.get('deception', 0)}")
    print(f"  Output CSV File            : {FLAGS_CSV_1}")
    print(f"  Output JSON File           : {JUDGMENTS_JSON_1}")
    print("=" * 65)

    if judged_records:
        print("\nJudgments Overview:")
        for r in judged_records:
            icon = "🚩" if r["status"] == "FLAG" else "✅"
            print(f"  {icon} [{r['status']}] {r['severity']} - {r['entity']} ({r['attribute']}): {r['verdict'].upper()}")
            print(f"     Reason: {r['reason']}")
            print(f"     Quote A (Ep {r['ep_a']}): \"{r['quote_a']}\"")
            print(f"     Quote B (Ep {r['ep_b']}): \"{r['quote_b']}\"")
            print("-" * 65)
    print()


if __name__ == "__main__":
    main()
