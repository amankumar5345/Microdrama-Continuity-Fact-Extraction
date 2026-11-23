# MicroDrama Continuity Checker

An end-to-end continuity auditor for serialized microdrama screenplays. It ingests
timestamped episode scripts, extracts verifiable story facts, builds a canonical
Series Bible, detects cross-episode contradiction candidates, asks an LLM to judge
them, and gives a human a review workbench.

**Live demo:** [Open the Streamlit app](https://microdrama-continuity-fact-extraction-sjqifcjst6gj4tzig667nu.streamlit.app/)

The repository contains **two implementations**:

| Implementation | Entry points | Status |
| --- | --- | --- |
| **Current system** (`continuity/` package) | `python run_all.py`, `python -m continuity.*`, `streamlit run continuity/app.py` | Primary product: aliases, Series Bible, two-pass detection, LLM judgment, review studio |
| **Legacy prototype** (`src/` + `main.py`) | `python main.py` | Kept for comparison: simpler parser, fact extraction, rule-based invariant checks, Markdown/JSON reports |

Both use the same 50 episode scripts in `continuity/data/` (mirrored in `data/`).

---

## Quick start

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Configure a provider in .env (never commit this file)
#    OPENROUTER_API_KEY=...
#    # or GEMINI_API_KEY=... / OPENAI_API_KEY=... / GROQ_API_KEY=...

# 3. Run the current pipeline. Start with a few episodes for a fast first run;
#    drop --eps to process every episode that has no cached facts yet.
python run_all.py --eps 1 2 3
python run_all.py

# 4. Launch the review studio
streamlit run continuity/app.py

# Optional: run the legacy report pipeline
python main.py --episodes 1-5
```

> LLM stages use deterministic temperature (`0.0`) and a disk cache, so reruns of
> unchanged prompts cost no tokens.

---

## Architecture

```text
continuity/data/episode_001.txt ... episode_050.txt
                    |
         1. PARSE  continuity/parse.py
                    |  -> continuity/data/episodes.json  (+ data/episodes.json)
                    v
         2. EXTRACT continuity/extract.py
                    |  LLM + strict verbatim-quote verification
                    |  -> continuity/outputs/facts_epN.json (+ outputs/)
                    v
         3. BIBLE  continuity/bible.py
                    |  canonical alias map + chronological facts
                    |  -> outputs/alias_map.json, outputs/bible.json
                    v
         4. DETECT continuity/detect.py
                    |  Pass 1: value conflicts
                    |  Pass 2: state errors (dead / arrested / injured)
                    |  -> outputs/candidates.json
                    v
         5. JUDGE  continuity/judge.py
                    |  real_error | legit_change | deception | unclear
                    |  -> outputs/flags.csv, outputs/judgments.json
                    v
         STREAMLIT continuity/app.py
                       -> outputs/reviews.json (human accept/reject)
```

### Stage details

**1. Parse** — `parse_screenplay_text()` handles block headers
(`**LADY JULIANA (Confused):**`), inline `[00:32] SPEAKER: line`, SRT arrow timing,
scene headers, and plain `SPEAKER:` lines. Output records are
`{ep, scene, timestamp, speaker, text}`. No LLM.

**2. Extract** — one prompt per episode (`continuity/prompts/extract.txt`). Every
fact must carry a quote that appears verbatim in that episode's text, otherwise it
is dropped and counted. Attribute names are normalized to snake_case, aliases are
cleaned, and section labels such as `Episode 3` / `Timeline` are rejected as
entities. A failed LLM call for one episode does not abort the pipeline or
overwrite a previous good facts file.

**3. Series Bible** — `alias_map.json` is incrementally extended as new episodes
arrive, preserving human edits. `bible.json` is structured as
`entity -> attribute -> [{value, ep, timestamp, quote, reliability}]`, sorted
chronologically. Lookup is case-insensitive and also falls back to aliases carried
by the facts themselves.

**4. Detect** — Pass 1 compares stated values for the same canonical entity and
normalized attribute across episodes. Pass 2 finds a stated disabling state
(dead / arrested / injured), then looks for a later stated fact with no reversal
(released / freed / healed / survived / ...) in between.

**5. Judge** — sends one candidate pair to the LLM and records
`status` (`FLAG` for `real_error` / `unclear`, `FILTERED` for `legit_change` /
`deception`), severity, and a reason. Failures degrade safely to `unclear`
(flagged for a human) and are recorded in `llm_error`. Empty candidate sets clear
stale `flags.csv` / `judgments.json`.

---

## Streamlit review studio

```bash
streamlit run continuity/app.py
```

Or use the hosted version:
[**Live app**](https://microdrama-continuity-fact-extraction-sjqifcjst6gj4tzig667nu.streamlit.app/)

Tabs:

1. **Upload & Run Pipeline** — upload `.txt` episodes, assign episode numbers, save
   to `continuity/data/episode_NNN.txt`, then run each stage (or all stages) as a
   subprocess. Includes episode-size and entity-correlation analytics.
2. **Human Review Queue** — filter by review status, severity, verdict, or free
   text; inspect side-by-side quotes; Accept / Reject / Reset each flag.
3. **Visual Analytics** — severity distribution, entity risk leaderboard, review
   progress gauge, live precision, verdict breakdown, contradiction arc map.
4. **Series Bible Explorer** — search entities, inspect aliases and every tracked
   attribute with its quote and timestamp.
5. **Export Reports** — download reviewed flags (CSV), judgments (JSON), and the
   review audit trail (JSON).

Human decisions persist to `continuity/outputs/reviews.json`.
**Live precision** = `accepted / (accepted + rejected)`, computed over the flags
currently loaded (stale review IDs are ignored).

Built-in demo rows are shown **only when no judged flags exist**; they are never
mixed into real results.

---

## CLI reference

### Full pipeline

```bash
python run_all.py                       # every episode not yet extracted in continuity/data (or data/)
python run_all.py --eps 1 2 3           # only these episodes
python run_all.py --skip-parse          # reuse data/episodes.json
python run_all.py --skip-extract        # reuse facts_ep*.json for all stages
python run_all.py --rebuild-aliases     # force a fresh LLM alias proposal
python run_all.py --force-extract      # re-extract even when facts_epN.json exists
```

> Existing `outputs/facts_epN.json` files are validated and reused automatically.
> Only new, changed, or `--force-extract` episodes call the LLM.

### Individual stages

```bash
python -m continuity.parse
python -m continuity.extract --eps 1 2 3
python -m continuity.bible              # incremental alias update (LLM for new names)
python -m continuity.bible --no-llm     # offline, rule-based aliases only
python -m continuity.bible --rebuild-aliases
python -m continuity.detect
python -m continuity.judge
```

### Legacy prototype

```bash
python main.py
python main.py --episodes 1-5
python main.py --skip-llm-eval
```

Legacy outputs: `data/facts/episode_NNN_facts.json` and
`reports/continuity_report.{md,json}`.

---

## Configuration

`continuity/config.yaml` (current pipeline):

```yaml
provider: "openai"            # "openai" (OpenAI-compatible) or "gemini"
model: "nvidia/nemotron-3-ultra-550b-a55b:free"
api_key_env: "OPENROUTER_API_KEY"
base_url: "https://openrouter.ai/api/v1"
temperature: 0.0
timeout_seconds: 60
```

`config.yaml` (legacy `src/llm.py`) uses a `llm:` block and supports
`openrouter`, `openai`, `gemini`, and `groq`.

Both configs read `.env` from the project root. Keep `.env` out of version control.

### LLM cache

- Current pipeline: `continuity/data/cache.json`. Cache keys include provider,
  model, base URL, temperature, and prompt. Legacy prompt-only keys are migrated
  automatically, and malformed JSON is never cached.
- Legacy prototype: `.cache/llm/<sha256>.json`, keyed by provider + model +
  temperature + prompt.

---

## Output artifacts

| File | Producer | Contents |
| --- | --- | --- |
| `continuity/data/episodes.json` | parse | parsed line records for every episode |
| `continuity/outputs/facts_epN.json` | extract | verified facts + drop count |
| `continuity/outputs/alias_map.json` | bible | variant → canonical name mapping (editable) |
| `continuity/outputs/bible.json` | bible | entity → attribute → chronological facts |
| `continuity/outputs/candidates.json` | detect | candidate contradiction pairs |
| `continuity/outputs/flags.csv` | judge | severity-sorted review table |
| `continuity/outputs/judgments.json` | judge | full structured verdicts |
| `continuity/outputs/reviews.json` | app | human accept/reject audit trail |
| `data/facts/*.json` | legacy | legacy extracted facts |
| `reports/*` | legacy | legacy Markdown/JSON reports |

Current-pipeline artifacts are mirrored to the root `outputs/` directory.

---

## Tests and checks

The test files are executable scripts (not pytest suites):

```bash
python test_step1.py                 # config + LLM cache
python test_step2.py                 # parser + data models
python test_step3.py                 # extraction + disk cache revalidation
python test_step4.py                 # contradiction logic
python test_step5.py                 # end-to-end legacy reports
python -m continuity.test_detect     # offline two-pass detector test
python -m continuity.test_llm        # cache/JSON parsing (may call the API once)
```

A full syntax check:

```bash
python -m compileall -q .
```

The Streamlit app is smoke-tested with `st.testing.v1.AppTest` (no browser needed).

---

## Repository layout

```text
.
├── continuity/
│   ├── app.py               Streamlit review studio
│   ├── parse.py             screenplay parser
│   ├── extract.py           fact extraction + verbatim verification
│   ├── bible.py             alias normalization + Series Bible
│   ├── detect.py            two-pass candidate detection
│   ├── judge.py             LLM judgment + CSV/JSON export
│   ├── llm.py               provider client, model-scoped disk cache
│   ├── textutil.py          shared normalization / console helpers
│   ├── run_all.py           pipeline orchestration
│   ├── prompts/             extract.txt, judge.txt
│   ├── data/                50 screenplays, episodes.json, cache.json
│   ├── outputs/             facts, bible, candidates, flags, judgments, reviews
│   └── config.yaml
├── src/                     legacy prototype modules
├── main.py                  legacy CLI pipeline
├── run_all.py               thin wrapper around continuity/run_all.py
├── config.yaml              legacy LLM config
├── requirements.txt
├── data/                    screenplay mirror + legacy facts
├── reports/                 legacy reports
└── test_step1.py ... test_step5.py
```

---

## Why runs can be slow

- **LLM latency dominates.** The default model is a large free OpenRouter model;
  a single call commonly takes 10–60 seconds, and free tiers can queue or
  rate-limit.
- **Extraction is one call per episode.** A first run over 50 episodes therefore
  needs ~50 calls. This is the main cost.
- **Existing facts are now reused.** `outputs/facts_epN.json` is validated and
  skipped on later runs, so only missing/changed episodes call the LLM. Use
  `--force-extract` only after changing prompts or scripts.
- **Judgments are cached by prompt.** Re-running `judge.py` with the same
  candidates is instant.
- **The Streamlit app executes stages as subprocesses.** It captures each stage's
  output and reports when the stage finishes, so a long extraction looks quiet
  until it returns.
- **Hosted Streamlit sleeps when idle.** The first load after inactivity can take
  ~30 seconds for the app to wake up.

Speed options: run a few episodes first (`--eps 1 2 3`), switch
`continuity/config.yaml` to a faster paid model, or run extraction in batches
overnight and keep the resulting `facts_epN.json` files.

## Tech stack

- **Language:** Python 3.10+
- **LLM access:** OpenAI-compatible APIs (OpenRouter, Groq, OpenAI) or Gemini
- **UI:** Streamlit, Plotly
- **Config and utilities:** PyYAML, python-dotenv, requests

## Known limitations

- LLM extraction is probabilistic. Strict quote verification prevents fabricated
  quotes, but attribute naming and entity attribution can still be noisy; the judge
  and human review are the final filters.
- Pass 1 intentionally over-generates candidate pairs for free-form attributes
  (e.g. `command`, `ownership`); expect the judge to filter many of them.
- The free OpenRouter model can be rate-limited; cached prompts still replay
  instantly.
- Only episodes 1–3 currently have extracted facts in `continuity/outputs/`.
  Episodes 4–50 have scripts and parsed lines but need extraction.
- The legacy prototype and current pipeline keep separate fact/report stores by
  design; they do not share extraction results.
