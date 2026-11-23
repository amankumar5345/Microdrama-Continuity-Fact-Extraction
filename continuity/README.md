# Continuity Checker for Serialized Microdramas

The primary continuity pipeline: parse 50 timestamped screenplays, extract verified
facts, build a canonical Series Bible, detect cross-episode contradictions, judge
them with an LLM, and review flags in a Streamlit studio.

See the repository root `README.md` for the full project overview (including the
legacy `src/` prototype) and setup instructions.

---

## Pipeline

```text
data/*.txt
  -> parse.py    -> data/episodes.json
  -> extract.py  -> outputs/facts_epN.json       (verbatim quote gate)
  -> bible.py    -> outputs/alias_map.json + bible.json
  -> detect.py   -> outputs/candidates.json      (Pass 1 + Pass 2)
  -> judge.py    -> outputs/flags.csv + judgments.json
  -> app.py      -> outputs/reviews.json         (human review)
```

All current-pipeline outputs are also mirrored to the repository root `outputs/`.

### 1. Parse

```bash
python -m continuity.parse
```

Handles block headers, inline `[mm:ss] SPEAKER:` lines, SRT arrow timing, scene
metadata, and plain `SPEAKER:` lines. Writes `continuity/data/episodes.json` and
`data/episodes.json`.

### 2. Extract facts

```bash
python -m continuity.extract --eps 1 2 3
```

- One LLM call per episode using `prompts/extract.txt`.
- Reuses `outputs/facts_epN.json` when its quotes still verify against the
  screenplay, so repeated runs skip the LLM for unchanged episodes. Pass
  `--force` to re-extract.
- Drops any fact whose quote is not a case/whitespace-insensitive verbatim
  substring of that episode's screenplay text.
- Rejects section labels (`Episode N`, `Timeline`, etc.) as entities.
- Normalizes attributes to snake_case and cleans aliases.
- A failed episode call does not abort the pipeline or overwrite a previous good
  facts file.

### 3. Build the Series Bible

```bash
python -m continuity.bible
python -m continuity.bible --no-llm        # offline, rule-based aliases
python -m continuity.bible --rebuild-aliases
```

- Loads all `outputs/facts_ep*.json` files.
- Loads an existing `alias_map.json` and preserves human edits; new entities are
  added incrementally.
- Resolves canonical names case-insensitively and via aliases carried by facts.
- Normalizes attribute keys and filters non-character entities.
- Writes `entity -> attribute -> [{value, ep, timestamp, quote, reliability}]`.

### 4. Detect candidates

```bash
python -m continuity.detect
```

- **Pass 1 (value conflicts):** same canonical entity + normalized attribute with
  different stated values in different episodes.
- **Pass 2 (state errors):** a stated dead/arrested/injured state followed by a
  later stated fact, with no reversal (released, freed, healed, survived, ...) in
  between. Only stated facts can establish or clear a state.

### 5. Judge flags

```bash
python -m continuity.judge
```

Verdicts: `real_error`, `legit_change`, `deception`, `unclear`.

- `real_error` and `unclear` → **FLAG** (human review).
- `legit_change` and `deception` → **FILTERED** (still exported).
- LLM failures degrade to `unclear` and record `llm_error`.
- An empty candidate set clears stale `flags.csv` / `judgments.json`.

---

## One-click pipeline

```bash
python run_all.py                    # extract only episodes without usable cached facts
python run_all.py --eps 1 2 3
python run_all.py --skip-parse
python run_all.py --skip-extract
python run_all.py --rebuild-aliases
python run_all.py --force-extract    # re-extract even when facts_epN.json exists
```

`python -m continuity.run_all` is equivalent.

### Why a first run is slow

The default model is a large free OpenRouter model; one call can take 10–60
seconds and free tiers may queue or rate-limit. Extraction is one call per
episode, so a first pass over 50 episodes needs ~50 calls. Later runs reuse
`outputs/facts_epN.json` and skip the LLM for unchanged episodes. Judge calls are
cached by prompt, so re-judging identical candidates is instant.

---

## Streamlit studio

```bash
streamlit run continuity/app.py
```

Tabs:

1. **Upload & Run Pipeline** — save uploaded episodes as
   `continuity/data/episode_NNN.txt`, then run parse/extract/bible/detect/judge.
2. **Human Review Queue** — filters, side-by-side quotes, Accept / Reject / Reset.
3. **Visual Analytics** — severity donut, entity risk leaderboard, precision gauge,
   verdict breakdown, contradiction arc map.
4. **Series Bible Explorer** — search entities and inspect attribute timelines.
5. **Export Reports** — reviewed CSV, judgments JSON, review audit JSON.

Human decisions are stored in `outputs/reviews.json`.
Live precision = `accepted / (accepted + rejected)` over the currently loaded
flags. Demo rows appear only when no real judged flags exist and are never mixed
with real results.

---

## Configuration

`config.yaml`:

```yaml
provider: "openai"            # "openai" (OpenAI-compatible) or "gemini"
model: "nvidia/nemotron-3-ultra-550b-a55b:free"
api_key_env: "OPENROUTER_API_KEY"
base_url: "https://openrouter.ai/api/v1"
temperature: 0.0
timeout_seconds: 60
```

API keys are read from the repository-root `.env`.

### Cache

`data/cache.json` keys include provider, model, base URL, temperature, and prompt.
Legacy prompt-only keys are migrated automatically. Malformed JSON responses are
never cached.

---

## Outputs

| File | Meaning |
| --- | --- |
| `data/episodes.json` | parsed line records |
| `outputs/facts_epN.json` | verified facts per episode |
| `outputs/alias_map.json` | human-editable variant → canonical mapping |
| `outputs/bible.json` | Series Bible |
| `outputs/candidates.json` | candidate contradiction pairs |
| `outputs/flags.csv` | flagged/filtered review table |
| `outputs/judgments.json` | full verdicts and reasons |
| `outputs/reviews.json` | human decisions |

---

## Tests

```bash
python -m continuity.test_detect
python -m continuity.test_llm
python test_step2.py
python test_step3.py
python test_step4.py
python test_step5.py
```

`test_detect` is fully offline. `test_llm` may make one live API call.
