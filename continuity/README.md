# 🎬 Continuity Checker for Serialized Microdramas

An enterprise-grade, deterministic Python system designed to audit serialized microdrama screenplays (up to 50 episodes with timestamps per scene and line). It extracts verifiable narrative facts, builds a canonical series bible, detects cross-episode contradictions via two-pass scanning, classifies discrepancies via LLM judgment, and presents an interactive human-in-the-loop review studio in Streamlit.

---

## 🌟 Key Architecture

```
MicroDrama - Fix/
├── continuity/
│   ├── config.yaml          # LLM provider, model, API key env, base_url, temp=0.0
│   ├── llm.py               # call_llm(prompt, json_mode=True) with SHA-256 disk cache & retry
│   ├── parse.py             # Screenplay parser handling timestamps, scenes, dialogue & actions
│   ├── extract.py           # Fact extractor with strict verbatim quote verification
│   ├── bible.py             # Series Bible builder with LLM canonical alias normalization
│   ├── detect.py            # Two-pass detector (Pass 1: Value Conflicts, Pass 2: State Errors)
│   ├── judge.py             # Severity ranker & classifier (real_error vs legit_change)
│   ├── app.py               # Interactive Streamlit Web Studio with live precision & Plotly charts
│   ├── prompts/
│   │   ├── extract.txt      # Prompt template for fact extraction
│   │   └── judge.txt        # Prompt template for contradiction judgment
│   ├── data/
│   │   ├── cache.json       # Deterministic LLM response cache ($0 token cost on reruns)
│   │   ├── episodes.json    # Structured screenplay lines with timestamps
│   │   └── *.txt            # Timestamped screenplay files (episodes 1 to 50)
│   └── outputs/
│       ├── facts_epN.json   # Verified facts extracted per episode
│       ├── alias_map.json   # Canonical name mapping (human-editable)
│       ├── bible.json       # Series Bible (entity -> attribute -> chronological facts)
│       ├── candidates.json  # Candidate contradiction pairs
│       ├── flags.csv        # Reviewed flags table sorted by severity
│       ├── judgments.json   # Machine-readable contradiction judgments
│       └── reviews.json     # Human audit decisions (accepted / rejected)
├── run_all.py               # One-click pipeline runner orchestrating stages 1 through 5
├── requirements.txt         # Minimal dependencies (pyyaml, requests, python-dotenv, streamlit, plotly)
└── .env                     # API keys configuration
```

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.11)
- Install minimal dependencies:
```bash
pip install -r requirements.txt
```

### 2. Configure API Key
Create or edit `.env` in the project root:
```bash
# Example for OpenRouter (Free-tier models supported out of the box)
OPENROUTER_API_KEY=sk-or-v1-...

# Or for Gemini:
# GEMINI_API_KEY=AIzaSy...

# Or for OpenAI:
# OPENAI_API_KEY=sk-...
```

Review `continuity/config.yaml` to adjust the model if desired:
```yaml
provider: "openai" # "openai" (covers OpenRouter, Groq, OpenAI) or "gemini"
model: "nvidia/nemotron-3-ultra-550b-a55b:free" # 100% Free on OpenRouter
api_key_env: "OPENROUTER_API_KEY"
base_url: "https://openrouter.ai/api/v1"
temperature: 0.0
```

---

## ⚡ Running the Pipeline

### Option A: Run the Entire Pipeline in One Click (`run_all.py`)
Run all stages (Parse &rarr; Extract &rarr; Bible &rarr; Detect &rarr; Judge):

```bash
# Run on episodes 1 and 2
python run_all.py --eps 1 2

# Run on all 50 episodes
python run_all.py

# Re-run bible, detect, and judge using already extracted facts (skips LLM extraction)
python run_all.py --skip-extract
```

**Terminal Summary Output:**
```
======================================================================
🏁 PIPELINE EXECUTION SUMMARY
======================================================================
  ⏱️  Total Duration          : 0.04s
  📄 Screenplay Lines Parsed : 169 across 2 ep(s) and 2 scene(s)
  ✅ Facts Extracted         : 50
  🗑️  Quotes Dropped (Halluc) : 9
  👤 Canonical Entities      : 16
  🔍 Contradiction Candidates: 1
     - Value Conflicts       : 1
     - State Errors          : 0
  🚩 Flags Kept for Review   : 0 (real_error / unclear)
  🛡️  Filtered Discrepancies  : 1 (legit_change / deception)
----------------------------------------------------------------------
📁 Output Artifacts:
  - Parsed Episodes : continuity/data/episodes.json
  - Facts Directory : continuity/outputs/facts_ep*.json
  - Alias Merge Map : continuity/outputs/alias_map.json
  - Series Bible    : continuity/outputs/bible.json
  - Candidate Pairs : continuity/outputs/candidates.json
  - Reviewed Flags  : continuity/outputs/flags.csv
  - Judgments JSON  : continuity/outputs/judgments.json
======================================================================
```

---

### Option B: Run Individual Pipeline Stages

#### Stage 1: Parse Screenplays into Structured Events
Splits screenplay files into episodes, scenes, and lines with timestamps, handling odd formats without crashing:
```bash
python -m continuity.parse
```
- **Output:** `continuity/data/episodes.json` formatted as `{ep, scene, timestamp, speaker, text}`.

#### Stage 2: Fact Extraction & Verbatim Verification
Extracts checkable facts per episode, strictly validating quotes against the text and dropping hallucinations:
```bash
python -m continuity.extract --eps 1 2
```
- **Output:** `continuity/outputs/facts_ep1.json`, `continuity/outputs/facts_ep2.json`, etc.

#### Stage 3: Build Series Bible & Normalize Aliases
Normalizes character names using alias lists and an LLM-proposed alias merge map:
```bash
python -m continuity.bible

# Or force re-generating the alias proposal:
python -m continuity.bible --rebuild-aliases
```
- **Output:**
  - `continuity/outputs/alias_map.json`: Human-editable alias mapping (e.g. `"The Former Groom": "Gerald"`).
  - `continuity/outputs/bible.json`: `entity -> attribute -> list of {value, ep, timestamp, quote, reliability}`.

#### Stage 4: Detect Contradiction Candidates
Runs two passes over the Series Bible:
1. **Pass 1 (Value Conflicts)**: Same entity + attribute with conflicting values in different episodes (filtering `reliability == "stated"`).
2. **Pass 2 (State Errors)**: Entities with disabling status (arrested, dead, injured) who reappear or speak later without an intervening reversal.
```bash
python -m continuity.detect
```
- **Output:** `continuity/outputs/candidates.json`.

#### Stage 5: Judge Contradictions & Rank by Severity
Evaluates candidate pairs via `call_llm()`, flags `real_error` and `unclear`, marks `legit_change` and `deception` as filtered, and sorts by severity:
```bash
python -m continuity.judge
```
- **Output:**
  - `continuity/outputs/flags.csv`: CSV table sorted by severity (`CRITICAL` &rarr; `HIGH` &rarr; `MEDIUM` &rarr; `LOW`).
  - `continuity/outputs/judgments.json`: Full structured JSON.

---

## 🖥️ Launch the Streamlit Review Studio

Open the interactive human review studio:
```bash
streamlit run continuity/app.py
```

### Studio Features:
1. **Side-by-Side Review Queue**:
   - Inspect **Episode A vs Episode B** with verbatim quote boxes, timestamps, and reasoning.
   - **`✅ Accept Flag`** (confirmed bug) vs **`❌ Reject Flag`** (benign change) buttons per flag.
   - Saves reviews persistently to `continuity/outputs/reviews.json`.
2. **Live Precision Gauge**:
   $$\text{Precision} = \frac{\text{Accepted}}{\text{Accepted} + \text{Rejected}} \times 100\%$$
   Updates live as you audit flags.
3. **Plotly Visual Analytics**:
   - Cross-episode discrepancy arc timeline.
   - Severity distribution donut chart.
   - Entity discrepancy risk leaderboard.
4. **Series Bible Explorer**:
   - Search and inspect any character's complete chronological lore and dialogue history.
5. **1-Click Downloads**:
   - Download reviewed flags as CSV, judgments JSON, or review audit trails.
