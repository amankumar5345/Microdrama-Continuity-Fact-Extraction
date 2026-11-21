# 🎬 Microdrama Continuity Fact Extraction
 
A deterministic Python pipeline that audits serialized microdrama screenplays (up to 50 episodes, with timestamps on every scene and line). It extracts verifiable narrative facts, builds a canonical **Series Bible**, detects cross-episode contradictions, classifies them with an LLM, and presents the results in an interactive **human-in-the-loop review studio** built with Streamlit.
 
**🔗 Live demo:** [Open the Streamlit app](https://microdrama-continuity-fact-extraction-sjqifcjst6gj4tzig667nu.streamlit.app/)
 
---
 
## Table of Contents
 
1. [The Problem](#-the-problem)
2. [Key Features](#-key-features)
3. [How It Works](#-how-it-works)
4. [Project Structure](#-project-structure)
5. [Setup](#-setup)
6. [Usage](#-usage)
7. [Review Studio (Streamlit)](#-review-studio-streamlit)
8. [Output Files](#-output-files)
9. [Sample Run](#-sample-run)
10. [Tech Stack](#-tech-stack)
---
 
## 🎯 The Problem
 
Serialized microdramas can run to 50 short episodes, often written by different people. Facts drift between episodes:
 
- A character's name, job or relationship changes without explanation.
- A character who was arrested, injured or dead appears again with no reversal.
Checking this by hand means re-reading every episode. This project automates the search and leaves the final decision to a human reviewer.
 
## ✨ Key Features
 
| Feature | Description |
|---|---|
| **Verbatim quote verification** | Every extracted fact must include a quote that exists in the script. Facts with unverifiable quotes are dropped, which removes LLM hallucinations. |
| **Canonical Series Bible** | All facts are organised as entity → attribute → chronological values, with character aliases merged into one canonical name. |
| **Two-pass detection** | Pass 1 finds value conflicts; Pass 2 finds state errors (for example, a dead character who speaks later). |
| **LLM judgment** | Each candidate is classified as `real_error`, `unclear`, `legit_change` or `deception`, then ranked by severity. |
| **Deterministic and cheap** | Temperature 0.0 and a SHA-256 disk cache mean reruns give the same results at $0 token cost. |
| **Human-in-the-loop review** | Accept or reject each flag in the Streamlit studio; a live precision gauge tracks reviewer agreement. |
 
## ⚙️ How It Works
 
```
Screenplays (.txt) → Parse → Extract → Bible → Detect → Judge → Review Studio
```
 
| Stage | Module | What it does | Output |
|---|---|---|---|
| 1. Parse | `parse.py` | Splits screenplay files into episodes, scenes and lines with timestamps. Handles odd formats without crashing. | `data/episodes.json` |
| 2. Extract | `extract.py` | Extracts checkable facts per episode and verifies each quote against the source text. | `outputs/facts_epN.json` |
| 3. Bible | `bible.py` | Builds the Series Bible and normalises aliases using an LLM-proposed, human-editable map. | `alias_map.json`, `bible.json` |
| 4. Detect | `detect.py` | Pass 1: same entity and attribute with conflicting values across episodes (only `reliability == "stated"`). Pass 2: entities with a disabling status (arrested, dead, injured) who reappear or speak later without a reversal. | `candidates.json` |
| 5. Judge | `judge.py` | Classifies candidates via `call_llm()`. Flags `real_error` and `unclear`; filters out `legit_change` and `deception`; sorts by severity. | `flags.csv`, `judgments.json` |
 
## 📁 Project Structure
 
```
Microdrama-Continuity-Fact-Extraction/
├── continuity/
│   ├── config.yaml        # LLM provider, model, API key env var, base_url, temperature
│   ├── llm.py             # call_llm(prompt, json_mode=True) with SHA-256 disk cache and retry
│   ├── parse.py           # Screenplay parser (timestamps, scenes, dialogue, actions)
│   ├── extract.py         # Fact extractor with verbatim quote verification
│   ├── bible.py           # Series Bible builder with alias normalisation
│   ├── detect.py          # Two-pass contradiction detector
│   ├── judge.py           # Severity ranker and classifier
│   ├── app.py             # Streamlit review studio
│   ├── prompts/
│   │   ├── extract.txt    # Prompt template: fact extraction
│   │   └── judge.txt      # Prompt template: contradiction judgment
│   ├── data/
│   │   ├── cache.json     # LLM response cache
│   │   ├── episodes.json  # Parsed screenplay lines with timestamps
│   │   └── *.txt          # Timestamped screenplay files (episodes 1 to 50)
│   └── outputs/
│       ├── facts_epN.json     # Verified facts per episode
│       ├── alias_map.json     # Canonical name mapping (human-editable)
│       ├── bible.json         # Series Bible
│       ├── candidates.json    # Candidate contradiction pairs
│       ├── flags.csv          # Flags sorted by severity
│       ├── judgments.json     # Machine-readable judgments
│       └── reviews.json       # Human review decisions
├── run_all.py             # One-click runner for stages 1 to 5
├── requirements.txt       # Dependencies
├── .env.example           # Template for API keys
└── README.md
```
 
## 🚀 Setup
 
**Prerequisites:** Python 3.10+ (tested on 3.11).
 
**1. Install dependencies**
 
```bash
pip install -r requirements.txt
```
 
Dependencies: `pyyaml`, `requests`, `python-dotenv`, `streamlit`, `plotly`.
 
**2. Add your API key**
 
Copy `.env.example` to `.env` and set **one** key:
 
```bash
# OpenRouter (free-tier models supported out of the box)
OPENROUTER_API_KEY=sk-or-v1-...
 
# or Gemini
# GEMINI_API_KEY=AIzaSy...
 
# or OpenAI
# OPENAI_API_KEY=sk-...
```
 
**3. (Optional) Configure the model** in `continuity/config.yaml`:
 
```yaml
provider: "openai"            # "openai" (covers OpenRouter, Groq, OpenAI) or "gemini"
model: "nvidia/nemotron-3-ultra-550b-a55b:free"   # free on OpenRouter
api_key_env: "OPENROUTER_API_KEY"
base_url: "https://openrouter.ai/api/v1"
temperature: 0.0
```
 
## ▶️ Usage
 
### Option A: Run the whole pipeline
 
```bash
python run_all.py --eps 1 2        # episodes 1 and 2 only
python run_all.py                  # all 50 episodes
python run_all.py --skip-extract   # rerun bible, detect and judge using existing facts
```
 
### Option B: Run stages one at a time
 
| Stage | Command |
|---|---|
| 1. Parse | `python -m continuity.parse` |
| 2. Extract | `python -m continuity.extract --eps 1 2` |
| 3. Bible | `python -m continuity.bible` (add `--rebuild-aliases` to regenerate the alias proposal) |
| 4. Detect | `python -m continuity.detect` |
| 5. Judge | `python -m continuity.judge` |
 
## 🖥️ Review Studio (Streamlit)
 
```bash
streamlit run continuity/app.py
```
 
Or use the hosted version: **[Live app](https://microdrama-continuity-fact-extraction-sjqifcjst6gj4tzig667nu.streamlit.app/)**
 
| Feature | Description |
|---|---|
| **Review queue** | Episode A vs Episode B side by side, with verbatim quotes, timestamps and the judge's reasoning. |
| **Accept / Reject** | `✅ Accept Flag` (confirmed bug) or `❌ Reject Flag` (benign change). Decisions are saved to `outputs/reviews.json`. |
| **Live precision gauge** | `Precision = Accepted / (Accepted + Rejected) × 100%`, updated as you review. |
| **Plotly analytics** | Discrepancy timeline across episodes, severity donut chart, entity risk leaderboard. |
| **Series Bible explorer** | Search any character and see their full chronological facts and dialogue history. |
| **Downloads** | Flags as CSV, judgments as JSON, and the review audit trail. |
 
## 📤 Output Files
 
| File | Contents |
|---|---|
| `data/episodes.json` | Parsed lines as `{ep, scene, timestamp, speaker, text}` |
| `outputs/facts_epN.json` | Verified facts per episode |
| `outputs/alias_map.json` | Canonical name mapping, for example `"The Former Groom": "Gerald"` (edit by hand if needed) |
| `outputs/bible.json` | `entity → attribute → list of {value, ep, timestamp, quote, reliability}` |
| `outputs/candidates.json` | Candidate contradiction pairs from both detection passes |
| `outputs/flags.csv` | Flags sorted by severity: `CRITICAL` → `HIGH` → `MEDIUM` → `LOW` |
| `outputs/judgments.json` | Full structured judgments |
| `outputs/reviews.json` | Human accept / reject decisions |
 
## 📊 Sample Run
 
`python run_all.py --eps 1 2`
 
```
======================================================================
🏁 PIPELINE EXECUTION SUMMARY
======================================================================
⏱️ Total Duration            : 0.04s
📄 Screenplay Lines Parsed   : 169 across 2 ep(s) and 2 scene(s)
✅ Facts Extracted           : 50
🗑️ Quotes Dropped (Halluc)   : 9
👤 Canonical Entities        : 16
🔍 Contradiction Candidates  : 1
   - Value Conflicts         : 1
   - State Errors            : 0
🚩 Flags Kept for Review     : 0 (real_error / unclear)
🛡️ Filtered Discrepancies    : 1 (legit_change / deception)
======================================================================
```
 
## 🧰 Tech Stack
 
- **Language:** Python 3.10+
- **LLM access:** OpenAI-compatible API (OpenRouter, Groq, OpenAI) or Gemini, configured in `config.yaml`
- **UI:** Streamlit, Plotly
- **Config and utilities:** PyYAML, python-dotenv, requests
 
