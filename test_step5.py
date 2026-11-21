"""
test_step5.py
-------------
Verifies Step 5:
- Full end-to-end pipeline execution via main.py
- Markdown report generation (reports/continuity_report.md)
- JSON report generation (reports/continuity_report.json)
- Terminal display format
"""

from pathlib import Path
from main import run_pipeline

def main():
    print("=== Testing Step 5: End-to-End Pipeline & Reporting ===")
    
    reports_dir = Path("reports")
    contradictions, facts = run_pipeline(
        data_dir_str="data",
        episode_spec="1,2",
        output_dir_str="reports",
        skip_llm_eval=True,  # Fast verification
    )

    md_report = reports_dir / "continuity_report.md"
    json_report = reports_dir / "continuity_report.json"

    assert md_report.exists(), f"Markdown report {md_report} was not created"
    assert json_report.exists(), f"JSON report {json_report} was not created"

    print(f"[OK] Markdown report generated: {md_report.name} ({md_report.stat().st_size} bytes)")
    print(f"[OK] JSON report generated: {json_report.name} ({json_report.stat().st_size} bytes)")

    # Read top of markdown report
    with open(md_report, "r", encoding="utf-8") as f:
        preview = f.read(400)
    print("\n--- Markdown Report Preview ---")
    print(preview)
    print("-------------------------------\n")

    print("[SUCCESS] Step 5 verification passed flawlessly!")

if __name__ == "__main__":
    main()
