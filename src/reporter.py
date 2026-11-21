"""
src/reporter.py
---------------
Generates human review reports (Markdown, JSON, and CLI terminal tables)
for flagged cross-episode continuity contradictions.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from src.models import Contradiction, Fact


def generate_markdown_report(
    contradictions: List[Contradiction],
    facts: List[Fact],
    episode_count: int,
    output_path: Path,
) -> Path:
    """
    Generates a structured, human-readable Markdown report for review.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Calculate metrics
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for c in contradictions:
        sev_counts[c.severity] = sev_counts.get(c.severity, 0) + 1

    lines = [
        "# 🎬 Continuity Checker — Human Review Report",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Episodes Analyzed:** {episode_count}  ",
        f"**Total Verified Facts:** {len(facts)}  ",
        f"**Total Contradiction Flags:** {len(contradictions)}  ",
        "",
        "## 📊 Flag Summary by Severity",
        "",
        "| Severity | Flags Count | Description |",
        "| :--- | :--- | :--- |",
        f"| 🔴 **CRITICAL** | {sev_counts['CRITICAL']} | Invariant lore retcons (physical traits, biology, mortality) |",
        f"| 🟠 **HIGH** | {sev_counts['HIGH']} | Relational or status conflicts without narrative transition |",
        f"| 🟡 **MEDIUM** | {sev_counts['MEDIUM']} | Object ownership or location inconsistencies |",
        f"| 🟢 **LOW** | {sev_counts['LOW']} | Minor phrasing or timeline ambiguities |",
        "",
        "---",
        "",
        "## 🚩 Flagged Contradictions for Human Review",
        "",
    ]

    if not contradictions:
        lines.append("> ✅ **No continuity contradictions detected.** All stated facts are consistent across analyzed episodes.\n")
    else:
        for idx, c in enumerate(contradictions, 1):
            sev_icon = "🔴" if c.severity == "CRITICAL" else "🟠" if c.severity == "HIGH" else "🟡"
            lines.extend([
                f"### {idx}. [{c.contradiction_id}] {sev_icon} {c.severity}: {c.entity} ({c.attribute})",
                "",
                f"**Explanation:** {c.explanation}",
                "",
                "| Comparison Point | Fact A (Earlier Episode) | Fact B (Later Episode) |",
                "| :--- | :--- | :--- |",
                f"| **Episode & Time** | Ep {c.fact_a.episode} [{c.fact_a.timestamp}] | Ep {c.fact_b.episode} [{c.fact_b.timestamp}] |",
                f"| **Entity / Aliases** | {c.fact_a.entity} ({', '.join(c.fact_a.aliases) or 'none'}) | {c.fact_b.entity} ({', '.join(c.fact_b.aliases) or 'none'}) |",
                f"| **Attribute / Value** | `{c.fact_a.attribute}` = **{c.fact_a.value}** | `{c.fact_b.attribute}` = **{c.fact_b.value}** |",
                f"| **Reliability** | `{c.fact_a.reliability}` | `{c.fact_b.reliability}` |",
                f"| **Verbatim Quote** | *\"{c.fact_a.quote}\"* | *\"{c.fact_b.quote}\"* |",
                "",
                "---",
                "",
            ])

    # Entity Lore Bible Summary
    lines.extend([
        "## 📖 Verified Entity Lore Summary",
        "",
        "| Entity | Category | Attribute | Value | Episode | Timestamp | Verbatim Quote |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for f in sorted(facts, key=lambda x: (x.entity, x.episode, x.timestamp))[:30]:
        clean_q = f.quote.replace("|", "\\|")
        lines.append(
            f"| **{f.entity}** | {f.category} | {f.attribute} | {f.value} | Ep {f.episode} | {f.timestamp} | *\"{clean_q}\"* |"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_path


def generate_json_report(
    contradictions: List[Contradiction],
    facts: List[Fact],
    episode_count: int,
    output_path: Path,
) -> Path:
    """
    Exports a structured JSON report for machine consumption or dashboard integration.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "episodes_analyzed": episode_count,
            "total_facts": len(facts),
            "total_contradictions": len(contradictions),
        },
        "contradictions": [c.to_dict() for c in contradictions],
        "facts": [f.to_dict() for f in facts],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    return output_path


def print_cli_summary(contradictions: List[Contradiction], total_facts: int, episode_count: int):
    """
    Prints a clean, formatted terminal summary for immediate review.
    """
    print("\n" + "=" * 78)
    print("🎬 CONTINUITY CHECKER — HUMAN REVIEW FLAGS")
    print("=" * 78)
    print(f"Episodes Analyzed: {episode_count} | Verified Facts: {total_facts} | Flags: {len(contradictions)}\n")

    if not contradictions:
        print("  ✅ [CLEAN] No cross-episode contradictions found.\n")
        print("=" * 78)
        return

    for c in contradictions:
        sev_color = "🔴" if c.severity == "CRITICAL" else "🟠" if c.severity == "HIGH" else "🟡"
        print(f"  {sev_color} [{c.contradiction_id}] {c.severity}: {c.entity} -> {c.attribute}")
        print(f"     Explanation: {c.explanation}")
        print(f"     - Ep {c.fact_a.episode} [{c.fact_a.timestamp}]: \"{c.fact_a.quote}\" (Value: {c.fact_a.value})")
        print(f"     - Ep {c.fact_b.episode} [{c.fact_b.timestamp}]: \"{c.fact_b.quote}\" (Value: {c.fact_b.value})")
        print("-" * 78)
    print("=" * 78 + "\n")
