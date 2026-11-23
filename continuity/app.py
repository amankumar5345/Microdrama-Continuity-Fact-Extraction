"""
continuity/app.py  ·  Microdrama Continuity Checker Studio
──────────────────────────────────────────────────────────────
Enterprise-grade Streamlit dashboard for continuity review.

Tabs
  1. Upload & Run Pipeline — Upload your own episode .txt files & run the full pipeline
  2. Human Review Queue   — Flag cards with Accept / Reject / Reset
  3. Visual Analytics     — Severity donut, Entity leaderboard, Arc timeline,
                            Verdict breakdown bar, Review progress gauge
  4. Series Bible         — Searchable entity explorer with attribute timeline
  5. CSV / JSON Exports   — Download reviewed data

Persistence: outputs/reviews.json
Live Precision = accepted / (accepted + rejected)
"""

import hashlib
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Page Config — MUST be first Streamlit call
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Continuity Checker Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"

FLAGS_CSV      = OUTPUTS_DIR / "flags.csv"
JUDGMENTS_JSON = OUTPUTS_DIR / "judgments.json"
BIBLE_JSON     = OUTPUTS_DIR / "bible.json"
ALIAS_MAP_JSON = OUTPUTS_DIR / "alias_map.json"
REVIEWS_JSON   = OUTPUTS_DIR / "reviews.json"

SEVERITY_ORDER  = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
SEVERITY_COLORS = {
    "CRITICAL": "#ef4444",
    "HIGH":     "#f97316",
    "MEDIUM":   "#f59e0b",
    "LOW":      "#3b82f6",
}

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Root / App Shell ─────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    background-color: #080c14 !important;
    color: #e2e8f0;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}
[data-testid="stSidebar"] {
    background-color: #0d1221 !important;
    border-right: 1px solid rgba(255,255,255,0.07);
}
[data-testid="stHeader"] { background: transparent !important; }

/* ── Hero Banner ──────────────────────────────────────────────────────────── */
.hero {
    background: linear-gradient(135deg, rgba(17,25,45,0.95) 0%, rgba(10,15,30,0.98) 100%);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
    box-shadow: 0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05);
}
.hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%);
    pointer-events: none;
}
.hero-title {
    font-size: 2.2rem;
    font-weight: 900;
    background: linear-gradient(90deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 6px;
    line-height: 1.1;
}
.hero-sub {
    color: #94a3b8;
    font-size: 0.95rem;
    max-width: 640px;
}
.hero-stats {
    display: flex;
    gap: 20px;
    margin-top: 16px;
    flex-wrap: wrap;
}
.hero-stat {
    background: rgba(99,102,241,0.1);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 0.82rem;
    color: #a5b4fc;
    font-weight: 600;
}

/* ── KPI Cards ────────────────────────────────────────────────────────────── */
.kpi-row { display: flex; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }
.kpi {
    flex: 1;
    min-width: 120px;
    background: rgba(17,25,45,0.8);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 16px 18px;
    text-align: center;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    transition: transform 0.2s;
}
.kpi:hover { transform: translateY(-2px); }
.kpi-val { font-size: 2.1rem; font-weight: 800; line-height: 1; margin: 6px 0; }
.kpi-lbl { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; }

/* ── Flag Cards ───────────────────────────────────────────────────────────── */
.flag-card {
    background: rgba(17,25,45,0.7);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 20px 24px;
    margin-bottom: 6px;
    transition: border-color 0.2s;
}
.flag-card:hover { border-color: rgba(99,102,241,0.4); }
.flag-title { font-size: 1.15rem; font-weight: 700; color: #f1f5f9; }
.flag-attr  { font-size: 0.9rem; font-weight: 400; color: #64748b; }
.flag-reason { font-size: 0.9rem; color: #cbd5e1; line-height: 1.55; }

/* ── Badges ───────────────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    margin-right: 5px;
    white-space: nowrap;
}
.b-crit    { background: rgba(239,68,68,0.15);  color:#fca5a5; border:1px solid rgba(239,68,68,0.35); }
.b-high    { background: rgba(249,115,22,0.15); color:#fdba74; border:1px solid rgba(249,115,22,0.35); }
.b-med     { background: rgba(245,158,11,0.15); color:#fcd34d; border:1px solid rgba(245,158,11,0.35); }
.b-low     { background: rgba(59,130,246,0.15); color:#93c5fd; border:1px solid rgba(59,130,246,0.35); }
.b-accept  { background: rgba(16,185,129,0.15); color:#6ee7b7; border:1px solid rgba(16,185,129,0.35); }
.b-reject  { background: rgba(239,68,68,0.15);  color:#fca5a5; border:1px solid rgba(239,68,68,0.35); }
.b-pending { background: rgba(100,116,139,0.15);color:#94a3b8; border:1px solid rgba(100,116,139,0.35); }
.b-purple  { background: rgba(99,102,241,0.15); color:#a5b4fc; border:1px solid rgba(99,102,241,0.35); }
.b-teal    { background: rgba(20,184,166,0.15); color:#5eead4; border:1px solid rgba(20,184,166,0.35); }

/* ── Quote Boxes ──────────────────────────────────────────────────────────── */
.quote-wrap { margin-top: 8px; }
.quote-label {
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; color: #475569; margin-bottom: 4px;
}
.quote-box {
    background: rgba(8,12,20,0.7);
    border-left: 3px solid #6366f1;
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    font-style: italic;
    font-size: 0.9rem;
    color: #e2e8f0;
    line-height: 1.55;
}
.quote-val {
    font-size: 0.82rem;
    font-weight: 600;
    color: #818cf8;
    margin-top: 2px;
}

/* ── Section Divider ──────────────────────────────────────────────────────── */
.divider { border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 20px 0; }

/* ── Bible Card ───────────────────────────────────────────────────────────── */
.attr-entry {
    background: rgba(8,12,20,0.5);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 8px;
    font-size: 0.9rem;
}

/* ── Precision Bar ────────────────────────────────────────────────────────── */
.prec-bar-bg {
    background: rgba(255,255,255,0.08);
    border-radius: 999px;
    height: 8px;
    overflow: hidden;
    margin-top: 6px;
}
.prec-bar-fill {
    height: 8px;
    border-radius: 999px;
    transition: width 0.6s ease;
}

/* ── Streamlit overrides ──────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    background: rgba(17,25,45,0.5);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    color: #94a3b8;
    padding: 8px 18px;
    font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background: rgba(99,102,241,0.2) !important;
    border-color: rgba(99,102,241,0.4) !important;
    color: #a5b4fc !important;
}
div[data-testid="stMetric"] {
    background: rgba(17,25,45,0.6);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
    padding: 12px;
}
.stButton > button {
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
}
.stSelectbox > div > div, .stTextInput > div > div > input {
    background: rgba(17,25,45,0.8) !important;
    border-color: rgba(255,255,255,0.1) !important;
    color: #e2e8f0 !important;
}
/* Plotly responsive */
.js-plotly-plot { border-radius: 12px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def make_flag_id(row: Dict[str, Any]) -> str:
    raw = "|".join(
        str(row.get(field, ""))
        for field in (
            "entity",
            "attribute",
            "ep_a",
            "ep_b",
            "timestamp_a",
            "timestamp_b",
            "value_a",
            "value_b",
        )
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def sev_badge(sev: str) -> str:
    cls = {"CRITICAL": "b-crit", "HIGH": "b-high", "MEDIUM": "b-med", "LOW": "b-low"}.get(sev, "b-low")
    return f'<span class="badge {cls}">{sev}</span>'


def decision_badge(dec: str) -> str:
    cls = {"accepted": "b-accept", "rejected": "b-reject", "pending": "b-pending"}.get(dec, "b-pending")
    return f'<span class="badge {cls}">{dec.upper()}</span>'


def _safe_int(v: Any, default: int = 1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _esc(value: Any) -> str:
    """Escape screenplay-derived text before injecting it into unsafe HTML."""
    return html.escape(str(value if value is not None else ""), quote=True)


_NOISE_ENTITY_RE = re.compile(
    r"^(?:episode|ep|scene)\s*#?\s*\d+$|"
    r"^(?:timeline|actions?|dialogue|speaker|camera|sound(?:\s*fx)?|"
    r"script|screenplay|unknown|none|n/?a)$",
    re.I,
)


def _is_noise_entity_name(name: Any) -> bool:
    return bool(_NOISE_ENTITY_RE.match(str(name or "").strip()))


def _review_counts(df: pd.DataFrame, reviews: Dict[str, Dict[str, Any]]) -> Tuple[int, int, int]:
    """Count decisions for the flags currently on screen (ignoring stale ids)."""
    flag_ids = set(df["flag_id"]) if "flag_id" in df.columns else set()
    accepted = sum(
        1 for fid in flag_ids if reviews.get(fid, {}).get("decision") == "accepted"
    )
    rejected = sum(
        1 for fid in flag_ids if reviews.get(fid, {}).get("decision") == "rejected"
    )
    pending = max(0, len(flag_ids) - accepted - rejected)
    return accepted, rejected, pending


# ─────────────────────────────────────────────────────────────────────────────
# Data Loaders  (cached with short TTL — refresh button clears cache)
# ─────────────────────────────────────────────────────────────────────────────
DEMO_RECORDS: List[Dict[str, Any]] = [
    {
        "status": "FLAG", "verdict": "real_error", "severity": "CRITICAL",
        "severity_rank": 1, "candidate_type": "value_conflict",
        "entity": "Lady Juliana", "attribute": "eye_color",
        "ep_a": 1, "timestamp_a": "00:33.70", "value_a": "blue eyes",
        "quote_a": "Close-up on Juliana's trembling lips and shocked, tearful blue eyes.",
        "ep_b": 15, "timestamp_b": "01:12.00", "value_b": "emerald green eyes",
        "quote_b": "Her emerald green eyes narrowed in icy disdain.",
        "reason": "Direct retcon: Lady Juliana's eyes described as blue in Ep 1, then emerald green in Ep 15 — invariant physical trait cannot change.",
    },
    {
        "status": "FLAG", "verdict": "real_error", "severity": "HIGH",
        "severity_rank": 2, "candidate_type": "state_error",
        "entity": "Duke Alexander", "attribute": "status",
        "ep_a": 12, "timestamp_a": "02:15.00", "value_a": "arrested for treason",
        "quote_a": "The Constable tightens the manacles around Alexander's wrists: 'You are under arrest for treason.'",
        "ep_b": 13, "timestamp_b": "00:45.00", "value_b": "free — dining at ballroom",
        "quote_b": "Alexander raises a glass of champagne across the grand dining table.",
        "reason": "Alexander placed in irons (Ep 12) but appears freely dining at a formal event in Ep 13 with no intervening escape or bail scene.",
    },
    {
        "status": "FLAG", "verdict": "unclear", "severity": "MEDIUM",
        "severity_rank": 3, "candidate_type": "value_conflict",
        "entity": "The Matriarch", "attribute": "relationship",
        "ep_a": 3, "timestamp_a": "01:05.00", "value_a": "Gerald's mother",
        "quote_a": "The Matriarch clutches Gerald's arm — 'My son, you must not do this.'",
        "ep_b": 8, "timestamp_b": "00:30.00", "value_b": "Gerald's aunt",
        "quote_b": "Gerald bows: 'Yes, Aunt. I will honour your command.'",
        "reason": "Unclear whether this is a retcon or deliberate plot twist revealing secret parentage.",
    },
    {
        "status": "FILTERED", "verdict": "legit_change", "severity": "LOW",
        "severity_rank": 4, "candidate_type": "value_conflict",
        "entity": "Cathedral", "attribute": "location",
        "ep_a": 1, "timestamp_a": "00:00.00", "value_a": "wedding venue — nave, altar, aisle, wooden pews",
        "quote_a": "INT. CATHEDRAL – DAY",
        "ep_b": 2, "timestamp_b": "00:00.00", "value_b": "INT. CATHEDRAL – CONTINUOUS",
        "quote_b": "Scene heading: INT. CATHEDRAL – CONTINUOUS",
        "reason": "Both scenes share the same Cathedral location; 'CONTINUOUS' is a standard screenplay transition — no contradiction.",
    },
]


def _read_flag_records_from_disk() -> List[Dict[str, Any]]:
    """Read real judged flags, preferring judgments.json over the CSV."""
    records: List[Dict[str, Any]] = []

    if JUDGMENTS_JSON.exists():
        try:
            with open(JUDGMENTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                records = [r for r in data if isinstance(r, dict)]
        except Exception as exc:
            logging.warning("judgments.json read error: %s", exc)

    if not records and FLAGS_CSV.exists():
        try:
            csv_df = pd.read_csv(FLAGS_CSV)
            if not csv_df.empty:
                records = csv_df.to_dict(orient="records")
        except Exception as exc:
            logging.warning("flags.csv read error: %s", exc)

    return records


def _normalize_flag_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for raw in records:
        r = dict(raw)
        r["severity"] = str(r.get("severity") or "LOW").upper()
        if r["severity"] not in SEVERITY_ORDER:
            r["severity"] = "LOW"
        r["verdict"] = str(r.get("verdict") or "unknown").lower()
        r["status"] = str(
            r.get("status")
            or ("FLAG" if r["verdict"] in ("real_error", "unclear") else "FILTERED")
        ).upper()
        r.setdefault("flag_id", make_flag_id(r))
        r.setdefault("candidate_type", "value_conflict")
        r.setdefault("ep_a", 1)
        r.setdefault("ep_b", 1)
        r.setdefault("entity", "Unknown")
        r.setdefault("attribute", "unknown")
        r.setdefault("quote_a", "")
        r.setdefault("quote_b", "")
        r.setdefault("value_a", "")
        r.setdefault("value_b", "")
        r.setdefault("reason", "")
        r.setdefault("timestamp_a", "")
        r.setdefault("timestamp_b", "")
        normalized.append(r)
    return normalized


@st.cache_data(ttl=30)
def load_flags_data() -> Tuple[pd.DataFrame, bool]:
    """
    Return (flags dataframe, using_demo_data).

    Demo records are only used when no real judged flags exist. They are never
    merged into real flags, so the review queue cannot show fabricated rows
    alongside production results.
    """
    records = _read_flag_records_from_disk()
    using_demo = not records
    if using_demo:
        records = [dict(record) for record in DEMO_RECORDS]

    return pd.DataFrame(_normalize_flag_records(records)), using_demo


@st.cache_data(ttl=30)
def load_facts_data() -> pd.DataFrame:
    """Load every extracted fact, tolerating both dict and legacy list schemas."""
    candidate_dirs = [OUTPUTS_DIR, BASE_DIR.parent / "outputs"]
    files: List[Path] = []
    for directory in candidate_dirs:
        if directory.exists():
            files = sorted(directory.glob("facts_ep*.json"))
            if files:
                break

    rows: List[Dict[str, Any]] = []
    for facts_file in files:
        try:
            data = json.loads(facts_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.warning("facts file read error %s: %s", facts_file, exc)
            continue

        file_episode = _episode_number_from_name(facts_file.name) or 0
        if isinstance(data, dict):
            episode = _safe_int(data.get("episode", file_episode), file_episode)
            facts = data.get("facts", [])
        elif isinstance(data, list):
            episode = file_episode
            facts = data
        else:
            continue

        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if _is_noise_entity_name(fact.get("entity")):
                continue
            row = dict(fact)
            row["_episode"] = episode
            rows.append(row)

    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def load_bible_data() -> Dict[str, Any]:
    if BIBLE_JSON.exists():
        try:
            with open(BIBLE_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logging.warning("bible.json read error: %s", exc)
    return {}


@st.cache_data(ttl=30)
def load_alias_data() -> Dict[str, str]:
    if ALIAS_MAP_JSON.exists():
        try:
            with open(ALIAS_MAP_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_reviews() -> Dict[str, Dict[str, Any]]:
    if REVIEWS_JSON.exists():
        try:
            with open(REVIEWS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_reviews(reviews: Dict[str, Dict[str, Any]]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = REVIEWS_JSON.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    tmp_path.replace(REVIEWS_JSON)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
def render_sidebar(df: pd.DataFrame, reviews: Dict, bible: Dict) -> None:
    with st.sidebar:
        st.markdown("### 🎬 Continuity Studio")
        st.markdown("---")

        # Pipeline status
        st.markdown("#### 📂 Pipeline Status")

        facts_files = list(OUTPUTS_DIR.glob("facts_ep*.json"))
        ep_count = len(facts_files)
        bible_ok = BIBLE_JSON.exists()
        cands_ok = (OUTPUTS_DIR / "candidates.json").exists()
        flags_ok = FLAGS_CSV.exists() or JUDGMENTS_JSON.exists()

        def status_icon(ok: bool) -> str:
            return "✅" if ok else "⬜"

        st.markdown(f"""
{status_icon(ep_count > 0)} **Facts extracted** — {ep_count} episode(s)  
{status_icon(bible_ok)} **Series Bible** built  
{status_icon(cands_ok)} **Candidates** detected  
{status_icon(flags_ok)} **Flags** judged  
        """)

        st.markdown("---")

        # Quick stats
        st.markdown("#### 📊 Quick Stats")
        total = len(df)
        flags = int((df["status"] == "FLAG").sum()) if "status" in df.columns else 0
        entities = len(bible)
        accepted, rejected, _ = _review_counts(df, reviews)
        st.metric("Total candidates", total)
        st.metric("Active flags (LLM)", flags)
        st.metric("Bible entities", entities)
        st.metric("Reviewed", accepted + rejected)

        st.markdown("---")

        # Refresh
        if st.button("🔄 Refresh Data", width="stretch"):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.caption("Microdrama Continuity Checker v1.0")
        st.caption("Pipeline: parse → extract → bible → detect → judge → review")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Human Review Queue
# ─────────────────────────────────────────────────────────────────────────────
def render_review_tab(df: pd.DataFrame, reviews: Dict[str, Dict]) -> Dict[str, Dict]:
    st.subheader("🚩 Discrepancy Review Queue")

    # ── Filters ──────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 3])
    with fc1:
        status_f = st.selectbox("Review Status", ["ALL", "PENDING", "ACCEPTED", "REJECTED"])
    with fc2:
        sev_f = st.selectbox("Severity", ["ALL"] + SEVERITY_ORDER)
    with fc3:
        verdict_f = st.selectbox("Verdict", ["ALL", "real_error", "unclear", "legit_change", "deception"])
    with fc4:
        search_q = st.text_input("🔍 Search entity / quote / reason", "")

    # ── Apply filters ─────────────────────────────────────────────────────────
    fdf = df.copy()
    fdf["user_decision"] = fdf["flag_id"].apply(
        lambda fid: reviews.get(fid, {}).get("decision", "pending")
    )

    if status_f != "ALL":
        fdf = fdf[fdf["user_decision"] == status_f.lower()]
    if sev_f != "ALL":
        fdf = fdf[fdf["severity"] == sev_f]
    if verdict_f != "ALL":
        fdf = fdf[fdf["verdict"] == verdict_f]
    if search_q:
        q = search_q.lower()
        mask = (
            fdf["entity"].str.lower().str.contains(q, na=False)
            | fdf["quote_a"].str.lower().str.contains(q, na=False)
            | fdf["quote_b"].str.lower().str.contains(q, na=False)
            | fdf["reason"].str.lower().str.contains(q, na=False)
            | fdf["attribute"].str.lower().str.contains(q, na=False)
        )
        fdf = fdf[mask]

    st.caption(f"Showing **{len(fdf)}** of **{len(df)}** flags")

    if fdf.empty:
        st.info("No flags match the current filters.")
        return reviews

    # ── Render cards ─────────────────────────────────────────────────────────
    for _, row in fdf.iterrows():
        fid = row["flag_id"]
        dec = reviews.get(fid, {}).get("decision", "pending")
        sev = str(row.get("severity", "LOW")).upper()
        verdict = row.get("verdict", "unknown")
        ctype = row.get("candidate_type", "value_conflict")
        entity = row.get("entity", "Unknown")
        attribute = row.get("attribute", "")
        reason = row.get("reason", "No explanation provided.")
        ep_a = _safe_int(row.get("ep_a", 1))
        ep_b = _safe_int(row.get("ep_b", 1))
        ts_a = row.get("timestamp_a", "")
        ts_b = row.get("timestamp_b", "")
        val_a = row.get("value_a", "")
        val_b = row.get("value_b", "")
        q_a = row.get("quote_a", "")
        q_b = row.get("quote_b", "")

        sev_cls = {"CRITICAL": "b-crit", "HIGH": "b-high", "MEDIUM": "b-med", "LOW": "b-low"}.get(sev, "b-low")
        dec_cls = {"accepted": "b-accept", "rejected": "b-reject", "pending": "b-pending"}.get(dec, "b-pending")

        st.markdown(f"""
<div class="flag-card">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
    <div>
      <span class="badge {sev_cls}">{_esc(sev)}</span>
      <span class="badge b-purple">{_esc(ctype)}</span>
      <span class="badge b-teal">{_esc(verdict)}</span>
    </div>
    <span class="badge {dec_cls}">● {_esc(dec.upper())}</span>
  </div>
  <div class="flag-title">{_esc(entity)} <span class="flag-attr">· {_esc(attribute)}</span></div>
  <div class="flag-reason" style="margin-top:8px;">
    <strong style="color:#64748b;">LLM Verdict:</strong> {_esc(reason)}
  </div>
</div>
""", unsafe_allow_html=True)

        # Side-by-side quote comparison
        qa_col, qb_col = st.columns(2)
        with qa_col:
            st.markdown(f"""
<div class="quote-wrap">
  <div class="quote-label">📍 Episode {ep_a} · {_esc(ts_a)}</div>
  <div class="quote-val">Value: {_esc(val_a)}</div>
  <div class="quote-box">"{_esc(q_a)}"</div>
</div>
""", unsafe_allow_html=True)
        with qb_col:
            st.markdown(f"""
<div class="quote-wrap">
  <div class="quote-label">📍 Episode {ep_b} · {_esc(ts_b)}</div>
  <div class="quote-val">Value: {_esc(val_b)}</div>
  <div class="quote-box">"{_esc(q_b)}"</div>
</div>
""", unsafe_allow_html=True)

        # Action buttons
        btn1, btn2, btn3, _ = st.columns([1.4, 1.4, 1, 6])
        with btn1:
            if st.button("✅ Accept", key=f"acc_{fid}", width="stretch"):
                reviews[fid] = {
                    "decision": "accepted",
                    "reviewed_at": datetime.now().isoformat(),
                    "entity": entity,
                    "attribute": attribute,
                }
                save_reviews(reviews)
                st.rerun()
        with btn2:
            if st.button("❌ Reject", key=f"rej_{fid}", width="stretch"):
                reviews[fid] = {
                    "decision": "rejected",
                    "reviewed_at": datetime.now().isoformat(),
                    "entity": entity,
                    "attribute": attribute,
                }
                save_reviews(reviews)
                st.rerun()
        with btn3:
            if dec != "pending":
                if st.button("↩ Reset", key=f"rst_{fid}", width="stretch"):
                    reviews.pop(fid, None)
                    save_reviews(reviews)
                    st.rerun()

        st.markdown('<hr class="divider">', unsafe_allow_html=True)

    return reviews


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Visual Analytics
# ─────────────────────────────────────────────────────────────────────────────
PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2e8f0", size=12),
    margin=dict(t=30, b=30, l=10, r=10),
)


def render_analytics_tab(df: pd.DataFrame, reviews: Dict) -> None:
    st.subheader("📊 Continuity Visual Analytics")

    # ── Row 1: Donut + Bar ───────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### Severity Distribution")
        if "severity" in df.columns:
            sev_counts = (
                df["severity"]
                .value_counts()
                .reindex(SEVERITY_ORDER)
                .dropna()
                .reset_index()
            )
            sev_counts.columns = ["Severity", "Count"]
            fig = px.pie(
                sev_counts, names="Severity", values="Count",
                color="Severity",
                color_discrete_map=SEVERITY_COLORS,
                hole=0.5,
            )
            fig.update_traces(
                textposition="outside",
                textinfo="label+percent",
                marker=dict(line=dict(color="#080c14", width=2)),
            )
            fig.update_layout(**PLOT_LAYOUT, showlegend=True,
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")

    with col2:
        st.markdown("##### Entity Risk Leaderboard")
        if "entity" in df.columns:
            ent_counts = df["entity"].value_counts().head(10).reset_index()
            ent_counts.columns = ["Entity", "Flags"]
            fig = px.bar(
                ent_counts, x="Flags", y="Entity",
                orientation="h",
                color="Flags",
                color_continuous_scale=[[0, "#3b82f6"], [0.5, "#818cf8"], [1, "#ef4444"]],
            )
            fig.update_layout(
                **PLOT_LAYOUT,
                yaxis=dict(autorange="reversed", showgrid=False),
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig, width="stretch")

    # ── Row 2: Review Progress Gauge + Verdict Breakdown ────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.markdown("##### Review Progress")
        total = len(df)
        accepted = sum(1 for r in reviews.values() if r.get("decision") == "accepted")
        rejected = sum(1 for r in reviews.values() if r.get("decision") == "rejected")
        pending  = max(0, total - accepted - rejected)
        precision_pct = (accepted / (accepted + rejected) * 100) if (accepted + rejected) > 0 else 0

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=precision_pct,
            delta={"reference": 70, "increasing": {"color": "#10b981"}, "decreasing": {"color": "#ef4444"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#64748b", "tickfont": {"color": "#64748b"}},
                "bar": {"color": "#6366f1"},
                "bgcolor": "rgba(0,0,0,0)",
                "bordercolor": "rgba(255,255,255,0.1)",
                "steps": [
                    {"range": [0, 40],  "color": "rgba(239,68,68,0.15)"},
                    {"range": [40, 70], "color": "rgba(245,158,11,0.15)"},
                    {"range": [70, 100],"color": "rgba(16,185,129,0.15)"},
                ],
                "threshold": {"line": {"color": "#f59e0b", "width": 2}, "thickness": 0.75, "value": 70},
            },
            title={"text": "Live Precision %", "font": {"color": "#94a3b8"}},
            number={"suffix": "%", "font": {"color": "#e2e8f0", "size": 36}},
        ))
        fig_gauge.update_layout(**PLOT_LAYOUT, height=280)
        st.plotly_chart(fig_gauge, width="stretch")

        # Mini progress bar row
        prog_cols = st.columns(3)
        prog_cols[0].metric("✅ Accepted", accepted)
        prog_cols[1].metric("❌ Rejected", rejected)
        prog_cols[2].metric("⏳ Pending",  pending)

    with col4:
        st.markdown("##### Verdict Breakdown")
        if "verdict" in df.columns:
            verd_counts = df["verdict"].value_counts().reset_index()
            verd_counts.columns = ["Verdict", "Count"]
            verdict_colors = {
                "real_error":   "#ef4444",
                "unclear":      "#f59e0b",
                "legit_change": "#3b82f6",
                "deception":    "#c084fc",
                "unknown":      "#64748b",
            }
            fig_v = px.bar(
                verd_counts, x="Verdict", y="Count",
                color="Verdict",
                color_discrete_map=verdict_colors,
                text="Count",
            )
            fig_v.update_traces(textposition="outside")
            fig_v.update_layout(
                **PLOT_LAYOUT,
                showlegend=False,
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
            )
            st.plotly_chart(fig_v, width="stretch")

    # ── Row 3: Arc Timeline ──────────────────────────────────────────────────
    st.markdown("##### Cross-Episode Contradiction Arc Map")
    if "ep_a" in df.columns and "ep_b" in df.columns and not df.empty:
        fig_arc = go.Figure()
        for _, r in df.iterrows():
            ea   = _safe_int(r.get("ep_a", 1))
            eb   = _safe_int(r.get("ep_b", ea))
            sev  = str(r.get("severity", "LOW")).upper()
            color = SEVERITY_COLORS.get(sev, "#818cf8")
            dist = max(abs(eb - ea), 1)  # guard against zero-height arcs

            xs = [ea, (ea + eb) / 2, eb]
            ys = [0, dist * 0.6, 0]

            fig_arc.add_trace(go.Scatter(
                x=xs, y=ys,
                mode="lines",
                line=dict(color=color, width=2.5, shape="spline"),
                name=f"{r.get('entity')} ({sev})",
                hovertemplate=(
                    f"<b>{_esc(r.get('entity'))}</b><br>"
                    f"Attribute: {_esc(r.get('attribute'))}<br>"
                    f"Ep {ea} → Ep {eb}<br>"
                    f"Severity: {_esc(sev)}<br>"
                    f"Verdict: {_esc(r.get('verdict'))}<extra></extra>"
                ),
            ))
            # Dot markers at endpoints
            fig_arc.add_trace(go.Scatter(
                x=[ea, eb], y=[0, 0],
                mode="markers",
                marker=dict(color=color, size=8, symbol="circle",
                            line=dict(color="#080c14", width=1.5)),
                showlegend=False,
                hoverinfo="skip",
            ))

        fig_arc.update_layout(
            **PLOT_LAYOUT,
            height=320,
            xaxis=dict(
                title="Episode Number",
                showgrid=True, gridcolor="rgba(255,255,255,0.06)",
                zeroline=False,
                tickformat="d",
            ),
            yaxis=dict(
                title="Contradiction Span",
                showgrid=False,
                showticklabels=False,
                zeroline=True,
                zerolinecolor="rgba(255,255,255,0.1)",
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                y=-0.25,
                font=dict(size=10),
                bgcolor="rgba(0,0,0,0)",
            ),
        )
        st.plotly_chart(fig_arc, width="stretch")
    else:
        st.info("No episode data available to draw arc map.")

    # ── Row 4: Candidate Type Bar ────────────────────────────────────────────
    if "candidate_type" in df.columns:
        st.markdown("##### Candidate Type Distribution")
        ct = df["candidate_type"].value_counts().reset_index()
        ct.columns = ["Type", "Count"]
        fig_ct = px.bar(
            ct, x="Type", y="Count",
            color="Type",
            color_discrete_sequence=["#6366f1", "#14b8a6", "#f59e0b"],
            text="Count",
        )
        fig_ct.update_traces(textposition="outside")
        fig_ct.update_layout(**PLOT_LAYOUT, showlegend=False,
                              yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"))
        st.plotly_chart(fig_ct, width="stretch")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Series Bible Explorer
# ─────────────────────────────────────────────────────────────────────────────
def render_bible_tab(bible: Dict[str, Any], alias_map: Dict[str, str]) -> None:
    st.subheader("📖 Series Bible Explorer")

    if not bible:
        st.info("No Series Bible found. Run `python continuity/bible.py` to build `outputs/bible.json`.")
        return

    all_entities = sorted(bible.keys())

    search_col, sel_col = st.columns([2, 3])
    with search_col:
        entity_search = st.text_input("🔍 Filter entities", "")
    with sel_col:
        filtered_entities = [e for e in all_entities if entity_search.lower() in e.lower()] if entity_search else all_entities
        if not filtered_entities:
            st.warning("No entities match your search.")
            return
        selected = st.selectbox("Select Character / Entity", filtered_entities)

    # Alias card
    canonical_aliases = [
        k
        for k, v in alias_map.items()
        if k != selected and v.strip().lower() == selected.strip().lower()
    ]
    if canonical_aliases:
        st.markdown(
            f'<div style="margin-bottom:12px;">'
            f'<span style="color:#64748b; font-size:0.82rem;">Also known as:</span> '
            + " ".join(f'<span class="badge b-teal">{_esc(a)}</span>' for a in canonical_aliases)
            + "</div>",
            unsafe_allow_html=True,
        )

    ent_data = bible[selected]
    st.markdown(f"### 👤 {selected}")
    st.caption(f"{len(ent_data)} tracked attribute(s)")

    for attr, entries in sorted(ent_data.items()):
        with st.expander(f"📌 {attr.replace('_', ' ').title()} — {len(entries)} record(s)", expanded=True):
            for e in entries:
                ep      = e.get("ep", "?")
                ts      = e.get("timestamp", "")
                rel     = e.get("reliability", "stated")
                val     = e.get("value", "")
                quote   = e.get("quote", "")
                rel_color = {"stated": "#10b981", "inferred": "#f59e0b", "unreliable": "#ef4444"}.get(rel, "#64748b")
                st.markdown(f"""
<div class="attr-entry">
  <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px; flex-wrap:wrap;">
    <span class="badge b-purple">Ep {_esc(ep)}</span>
    <span style="font-size:0.8rem; color:#475569;">[{_esc(ts)}]</span>
    <span class="badge" style="background:rgba(0,0,0,0.3); color:{rel_color}; border:1px solid {rel_color}40;">{_esc(rel)}</span>
    <span style="font-size:0.9rem; font-weight:600; color:#e2e8f0;">{_esc(val)}</span>
  </div>
  <div class="quote-box">"{_esc(quote)}"</div>
</div>
""", unsafe_allow_html=True)

    # Entity summary stats
    st.markdown("---")
    st.markdown("#### 🗂 All Entities Overview")
    overview_rows = []
    for ent, attrs in bible.items():
        total_facts = sum(len(v) for v in attrs.values())
        attr_list   = ", ".join(sorted(attrs.keys())[:5])
        overview_rows.append({"Entity": ent, "Attributes": len(attrs), "Total Facts": total_facts, "Tracked": attr_list})
    st.dataframe(
        pd.DataFrame(overview_rows).sort_values("Total Facts", ascending=False),
        width="stretch",
        height=320,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 — CSV / JSON Exports
# ─────────────────────────────────────────────────────────────────────────────
def render_export_tab(df: pd.DataFrame, reviews: Dict) -> None:
    st.subheader("📥 Export Reviewed Flags & Reports")

    export_df = df.copy()
    export_df["user_decision"] = export_df["flag_id"].apply(
        lambda fid: reviews.get(fid, {}).get("decision", "pending")
    )
    export_df["reviewed_at"] = export_df["flag_id"].apply(
        lambda fid: reviews.get(fid, {}).get("reviewed_at", "")
    )

    csv_bytes     = export_df.to_csv(index=False).encode("utf-8")
    json_bytes    = json.dumps(export_df.to_dict(orient="records"), indent=2, ensure_ascii=False).encode("utf-8")
    reviews_bytes = json.dumps(reviews, indent=2, ensure_ascii=False).encode("utf-8")

    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        st.download_button(
            "📥 Reviewed Flags (CSV)",
            data=csv_bytes,
            file_name="continuity_flags_reviewed.csv",
            mime="text/csv",
            width="stretch",
        )
    with dl2:
        st.download_button(
            "📥 Judgments (JSON)",
            data=json_bytes,
            file_name="continuity_judgments.json",
            mime="application/json",
            width="stretch",
        )
    with dl3:
        st.download_button(
            "📥 Review Audit (JSON)",
            data=reviews_bytes,
            file_name="reviews.json",
            mime="application/json",
            width="stretch",
        )

    st.markdown("---")

    # Summary stats
    st.markdown("#### Review Summary")
    s1, s2, s3, s4 = st.columns(4)
    accepted = len(export_df[export_df["user_decision"] == "accepted"])
    rejected = len(export_df[export_df["user_decision"] == "rejected"])
    pending  = len(export_df[export_df["user_decision"] == "pending"])
    total    = len(export_df)
    s1.metric("Total Flags",   total)
    s2.metric("Accepted",      accepted)
    s3.metric("Rejected",      rejected)
    s4.metric("Pending",       pending)

    st.markdown("#### Preview Dataset")
    preview_cols = [c for c in [
        "severity", "user_decision", "verdict", "entity", "attribute",
        "ep_a", "timestamp_a", "ep_b", "timestamp_b", "reason"
    ] if c in export_df.columns]
    st.dataframe(export_df[preview_cols], width="stretch", height=360)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 0 — Upload & Run Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _run_stage(cmd: List[str], cwd: Path, placeholder) -> Tuple[int, str]:
    """Run a subprocess stage and stream output into a Streamlit code block."""
    placeholder.code("⏳ Running…", language="")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=600,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout or "") + (result.stderr or "")
        placeholder.code(output[-3000:] if len(output) > 3000 else output, language="")
        return result.returncode, output
    except subprocess.TimeoutExpired:
        placeholder.error("⏱ Stage timed out after 10 min.")
        return -1, "Timeout"
    except Exception as exc:
        placeholder.error(f"Error: {exc}")
        return -1, str(exc)


def _episode_number_from_name(name: str) -> Optional[int]:
    """Extract episode number from a filename like 'episode_007.txt' or 'ep3.txt' or 'Episode 12.txt'."""
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def render_upload_tab() -> None:
    st.subheader("📤 Upload Your Episode Files & Run the Pipeline")

    st.markdown("""
<div style="background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.25);
     border-radius:12px; padding:16px 20px; margin-bottom:20px;">
  <strong style="color:#a5b4fc;">How it works</strong>
  <ol style="color:#cbd5e1; margin:10px 0 0 0; padding-left:18px; font-size:0.92rem; line-height:1.8;">
    <li>Upload one or more episode <code>.txt</code> screenplay files below.</li>
    <li>Files are saved to <code>continuity/data/</code> as <code>episode_NNN.txt</code>.</li>
    <li>Run each pipeline stage in order: <strong>Parse → Extract → Bible → Detect → Judge</strong>.</li>
    <li>Switch to the other tabs to explore contradictions, visual analytics, and the Series Bible.</li>
  </ol>
  <p style="color:#64748b; font-size:0.82rem; margin-top:10px;">
    ⚡ <em>Extract, Bible, and Judge stages call the LLM — they may take 30–90 seconds per episode.</em>
  </p>
</div>
""", unsafe_allow_html=True)

    # ── File Uploader ─────────────────────────────────────────────────────────
    st.markdown("### Step 1 · Upload Episode Files")

    uploaded_files = st.file_uploader(
        "Drop your screenplay `.txt` files here (one per episode, or multiple at once)",
        type=["txt"],
        accept_multiple_files=True,
        help="Each file should be a plain-text screenplay for one episode. "
             "Name them anything — the app will auto-assign episode numbers.",
    )

    # Custom episode number assignment
    ep_assignments: Dict[str, int] = {}
    if uploaded_files:
        st.markdown("#### Episode Number Assignment")
        st.caption("Auto-detected from filename. Override if needed.")
        used_nums: set = set()
        for uf in uploaded_files:
            auto_ep = _episode_number_from_name(uf.name) or (len(used_nums) + 1)
            while auto_ep in used_nums:
                auto_ep += 1
            col_name, col_num = st.columns([3, 1])
            with col_name:
                st.markdown(
                    f'<span style="font-size:0.9rem; color:#e2e8f0;">📄 {_esc(uf.name)}'
                    f' <span style="color:#64748b;">({uf.size:,} bytes)</span></span>',
                    unsafe_allow_html=True,
                )
            with col_num:
                ep_num = st.number_input(
                    "Episode #", min_value=1, max_value=999,
                    value=auto_ep, key=f"epnum_{uf.name}",
                    label_visibility="collapsed",
                )
            ep_assignments[uf.name] = int(ep_num)
            used_nums.add(int(ep_num))

        # Save button
        if st.button("💾 Save Files to data/", type="primary", width="content"):
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            saved = []
            for uf in uploaded_files:
                ep_num = ep_assignments[uf.name]
                dest   = DATA_DIR / f"episode_{ep_num:03d}.txt"
                dest.write_bytes(uf.read())
                saved.append(f"episode_{ep_num:03d}.txt  ← {uf.name}")
            st.success(f"✅ Saved {len(saved)} file(s):")
            for s in saved:
                st.code(s, language="")
            st.info("Now run the pipeline stages below ↓")

    st.markdown("<hr style='border-color:rgba(255,255,255,0.06);'>", unsafe_allow_html=True)

    # ── Current data/ contents ────────────────────────────────────────────────
    st.markdown("### 📂 Current Episode Files in data/")
    existing = sorted(DATA_DIR.glob("episode_*.txt"))
    if existing:
        rows = []
        for f in existing:
            ep_n = _episode_number_from_name(f.name) or 0
            facts_file = OUTPUTS_DIR / f"facts_ep{ep_n}.json"
            extracted  = "✅" if facts_file.exists() else "⬜"
            rows.append({
                "File": f.name,
                "Episode": ep_n,
                "Size (KB)": round(f.stat().st_size / 1024, 1),
                "Modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "Facts Extracted": extracted,
            })
        ep_df = pd.DataFrame(rows)
        st.dataframe(ep_df, width="stretch", height=min(40 + len(rows) * 35, 400))

        # Correlation / coverage bar chart
        st.markdown("#### Episode Size Distribution")
        fig_size = px.bar(
            ep_df, x="Episode", y="Size (KB)",
            color="Facts Extracted",
            color_discrete_map={"✅": "#10b981", "⬜": "#334155"},
            labels={"Facts Extracted": "Extracted"},
            title="",
        )
        fig_size.update_layout(
            **PLOT_LAYOUT,
            xaxis=dict(tickformat="d", dtick=5, showgrid=False),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
            showlegend=True,
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig_size, width="stretch")
    else:
        st.info("No episode files found in `continuity/data/`. Upload some files above.")

    st.markdown("<hr style='border-color:rgba(255,255,255,0.06);'>", unsafe_allow_html=True)

    # ── Pipeline Runner ───────────────────────────────────────────────────────
    st.markdown("### ⚙️ Step 2 · Run Pipeline Stages")

    ROOT = BASE_DIR.parent  # MicroDrama - Fix/

    # Stage 1: Parse
    with st.expander("**Stage 1 · Parse** — Split all episode files into structured JSON", expanded=True):
        st.caption("`parse.py` reads every `episode_NNN.txt` → `data/episodes.json`")
        if st.button("▶ Run Parser", key="run_parse"):
            ph = st.empty()
            code, out = _run_stage(
                [sys.executable, "-m", "continuity.parse"],
                ROOT, ph
            )
            if code == 0:
                st.success("✅ Parse complete! `data/episodes.json` updated.")
                st.cache_data.clear()
            else:
                st.error(f"❌ Parse failed (exit {code})")

    # Stage 2: Extract (per episode or all)
    with st.expander("**Stage 2 · Extract Facts** — Run LLM fact extraction per episode"):
        st.caption("`extract.py` calls the LLM for each episode → `outputs/facts_epN.json`")
        c_ep, c_all = st.columns([2, 1])
        with c_ep:
            ep_nums_available = sorted(
                set(
                    _episode_number_from_name(f.name)
                    for f in existing
                    if _episode_number_from_name(f.name) is not None
                )
            ) if existing else [1]
            ep_to_extract = st.multiselect(
                "Select episodes to extract",
                ep_nums_available,
                default=ep_nums_available[:2] if ep_nums_available else [],
                help="Select which episode numbers to run extraction on.",
            )
        with c_all:
            extract_all = st.checkbox("Extract ALL episodes", value=False)

        if st.button("▶ Run Extractor", key="run_extract"):
            targets = ep_nums_available if extract_all else ep_to_extract
            if not targets:
                st.warning("Select at least one episode.")
            else:
                for ep_n in targets:
                    st.markdown(f"**Episode {ep_n}…**")
                    ph = st.empty()
                    code, _ = _run_stage(
                        [sys.executable, "-m", "continuity.extract", "--eps", str(ep_n)],
                        ROOT, ph
                    )
                    if code == 0:
                        st.success(f"✅ Ep {ep_n} extracted.")
                    else:
                        st.error(f"❌ Ep {ep_n} failed (exit {code})")
                st.cache_data.clear()

    # Stage 3: Bible
    with st.expander("**Stage 3 · Build Series Bible** — Merge all facts into canonical entities"):
        st.caption("`bible.py` merges facts, normalises aliases → `outputs/bible.json` + `outputs/alias_map.json`")
        if st.button("▶ Build Bible", key="run_bible"):
            ph = st.empty()
            code, _ = _run_stage(
                [sys.executable, "-m", "continuity.bible"],
                ROOT, ph
            )
            if code == 0:
                st.success("✅ Bible built! Check the **Series Bible Explorer** tab.")
                st.cache_data.clear()
            else:
                st.error(f"❌ Bible failed (exit {code})")

    # Stage 4: Detect
    with st.expander("**Stage 4 · Detect Contradictions** — Find value conflicts and state errors"):
        st.caption("`detect.py` runs two-pass detection → `outputs/candidates.json`")
        if st.button("▶ Run Detector", key="run_detect"):
            ph = st.empty()
            code, _ = _run_stage(
                [sys.executable, "-m", "continuity.detect"],
                ROOT, ph
            )
            if code == 0:
                st.success("✅ Detection done! Candidates saved.")
                st.cache_data.clear()
            else:
                st.error(f"❌ Detect failed (exit {code})")

    # Stage 5: Judge
    with st.expander("**Stage 5 · Judge Flags** — LLM verdict on each candidate pair"):
        st.caption("`judge.py` sends each candidate to the LLM → `outputs/flags.csv` + `outputs/judgments.json`")
        if st.button("▶ Run Judge", key="run_judge"):
            ph = st.empty()
            code, _ = _run_stage(
                [sys.executable, "-m", "continuity.judge"],
                ROOT, ph
            )
            if code == 0:
                st.success("✅ Judgments complete! Switch to **Human Review Queue** to review flags.")
                st.cache_data.clear()
            else:
                st.error(f"❌ Judge failed (exit {code})")

    # Full pipeline shortcut
    st.markdown("<hr style='border-color:rgba(255,255,255,0.06);'>", unsafe_allow_html=True)
    st.markdown("### ⚡ Run Full Pipeline")
    st.caption("Runs Parse → Extract (all eps) → Bible → Detect → Judge sequentially. May take several minutes.")
    if st.button("🚀 Run ALL Stages", type="primary", key="run_all"):
        stages = [
            ("Parse",   [sys.executable, "-m", "continuity.parse"]),
            ("Bible",   [sys.executable, "-m", "continuity.bible"]),
            ("Detect",  [sys.executable, "-m", "continuity.detect"]),
            ("Judge",   [sys.executable, "-m", "continuity.judge"]),
        ]
        # Insert extract stages per episode (continuity/data first, then root data)
        data_files: List[Path] = []
        for data_dir in (DATA_DIR, BASE_DIR.parent / "data"):
            if data_dir.exists():
                data_files.extend(data_dir.glob("episode_*.txt"))
        all_eps = sorted(
            {
                number
                for number in (_episode_number_from_name(f.name) for f in data_files)
                if number is not None
            }
        )
        all_stages = [stages[0]]  # Parse first
        for ep_n in all_eps:
            all_stages.append(
                (f"Extract Ep {ep_n}", [sys.executable, "-m", "continuity.extract", "--eps", str(ep_n)])
            )
        all_stages += stages[1:]  # Bible, Detect, Judge

        progress = st.progress(0, text="Starting pipeline…")
        for i, (name, cmd) in enumerate(all_stages):
            st.markdown(f"**▶ {name}**")
            ph = st.empty()
            code, _ = _run_stage(cmd, ROOT, ph)
            if code != 0:
                st.error(f"❌ Pipeline stopped at **{name}** (exit {code}). Fix the error and retry.")
                break
            st.success(f"✅ {name} done")
            progress.progress((i + 1) / len(all_stages), text=f"Completed: {name}")
        else:
            st.balloons()
            st.success("🎉 Full pipeline complete! Refresh to see results.")
            st.cache_data.clear()

    # ── Correlation Explorer (from existing facts) ────────────────────────────
    st.markdown("<hr style='border-color:rgba(255,255,255,0.06);'>", unsafe_allow_html=True)
    st.markdown("### 🔗 Episode Correlation Explorer")
    st.caption("Explore which episodes share the same entities and attributes — before running the judge.")

    facts_df = load_facts_data()
    if facts_df.empty:
        st.info("No facts extracted yet. Run **Stage 2 · Extract Facts** first.")
    else:
        facts_df = facts_df.copy()
        facts_df["_episode"] = facts_df["_episode"].astype(int)

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("#### Facts per Episode")
            ep_fact_counts = facts_df.groupby("_episode").size().reset_index(name="Fact Count")
            fig_epc = px.bar(
                ep_fact_counts, x="_episode", y="Fact Count",
                labels={"_episode": "Episode"},
                color="Fact Count",
                color_continuous_scale=[[0, "#3b82f6"], [1, "#6366f1"]],
            )
            fig_epc.update_layout(**PLOT_LAYOUT, coloraxis_showscale=False,
                                   xaxis=dict(tickformat="d", dtick=1))
            st.plotly_chart(fig_epc, width="stretch")

        with col_b:
            st.markdown("#### Top Entities Across Episodes")
            if "entity" in facts_df.columns:
                ent_ep = facts_df.groupby("entity")["_episode"].nunique().reset_index()
                ent_ep.columns = ["Entity", "Episodes Mentioned"]
                ent_ep = ent_ep.sort_values("Episodes Mentioned", ascending=False).head(12)
                fig_ent = px.bar(
                    ent_ep, x="Episodes Mentioned", y="Entity",
                    orientation="h",
                    color="Episodes Mentioned",
                    color_continuous_scale=[[0, "#14b8a6"], [1, "#6366f1"]],
                )
                fig_ent.update_layout(**PLOT_LAYOUT, coloraxis_showscale=False,
                                      yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_ent, width="stretch")

        # Cross-episode entity heatmap
        if "entity" in facts_df.columns:
            st.markdown("#### Entity × Episode Heatmap (presence = number of facts)")
            top_entities = facts_df["entity"].value_counts().head(15).index.tolist()
            ep_range    = sorted(facts_df["_episode"].unique())
            heat_data   = facts_df[facts_df["entity"].isin(top_entities)]
            heat_pivot  = (
                heat_data.groupby(["entity", "_episode"])
                .size()
                .unstack(fill_value=0)
                .reindex(columns=ep_range, fill_value=0)
            )
            fig_heat = px.imshow(
                heat_pivot,
                labels=dict(x="Episode", y="Entity", color="# Facts"),
                color_continuous_scale="Blues",
                aspect="auto",
            )
            fig_heat.update_layout(
                **PLOT_LAYOUT,
                height=max(300, len(top_entities) * 32),
                xaxis=dict(tickformat="d"),
            )
            st.plotly_chart(fig_heat, width="stretch")

        # Attribute distribution
        if "attribute" in facts_df.columns:
            st.markdown("#### Most-Tracked Attributes")
            attr_counts = facts_df["attribute"].value_counts().head(15).reset_index()
            attr_counts.columns = ["Attribute", "Count"]
            fig_attr = px.bar(
                attr_counts, x="Count", y="Attribute", orientation="h",
                color="Count",
                color_continuous_scale=[[0, "#f59e0b"], [1, "#ef4444"]],
            )
            fig_attr.update_layout(**PLOT_LAYOUT, coloraxis_showscale=False,
                                    yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_attr, width="stretch")

        # Raw facts table with filters
        st.markdown("#### 🔎 Browse Raw Facts")
        fc1, fc2, fc3 = st.columns([2, 2, 3])
        with fc1:
            ep_filter = st.multiselect(
                "Episode", sorted(facts_df["_episode"].unique()),
                default=[], key="facts_ep_filter"
            )
        with fc2:
            ent_opts = ["ALL"] + sorted(facts_df["entity"].dropna().unique()) if "entity" in facts_df.columns else ["ALL"]
            ent_filter = st.selectbox("Entity", ent_opts, key="facts_ent_filter")
        with fc3:
            attr_opts = ["ALL"] + sorted(facts_df["attribute"].dropna().unique()) if "attribute" in facts_df.columns else ["ALL"]
            attr_filter = st.selectbox("Attribute", attr_opts, key="facts_attr_filter")

        view_df = facts_df.copy()
        if ep_filter:
            view_df = view_df[view_df["_episode"].isin(ep_filter)]
        if ent_filter != "ALL" and "entity" in view_df.columns:
            view_df = view_df[view_df["entity"] == ent_filter]
        if attr_filter != "ALL" and "attribute" in view_df.columns:
            view_df = view_df[view_df["attribute"] == attr_filter]

        display_cols = [c for c in ["_episode", "entity", "attribute", "value", "timestamp", "reliability", "quote"] if c in view_df.columns]
        st.dataframe(
            view_df[display_cols].rename(columns={"_episode": "Episode"}),
            width="stretch",
            height=380,
        )
        st.caption(f"Showing {len(view_df)} of {len(facts_df)} facts")


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    # Load all data
    df, using_demo = load_flags_data()
    reviews = load_reviews()
    bible = load_bible_data()
    aliases = load_alias_data()
    facts_df = load_facts_data()

    # Compute precision over the flags currently loaded (ignore stale review ids).
    accepted, rejected, pending_count = _review_counts(df, reviews)
    reviewed = accepted + rejected
    precision_pct = (accepted / reviewed * 100) if reviewed > 0 else None

    # Sidebar
    render_sidebar(df, reviews, bible)

    # ── Hero Banner ──────────────────────────────────────────────────────────
    ep_facts = int(facts_df["_episode"].nunique()) if not facts_df.empty else 0
    total_facts = len(facts_df)

    prec_display = f"{precision_pct:.1f}%" if precision_pct is not None else "—"
    prec_color   = "#10b981" if (precision_pct or 0) >= 70 else "#f59e0b" if (precision_pct or 0) >= 40 else "#ef4444"

    st.markdown(f"""
<div class="hero">
  <div class="hero-title">🎬 Microdrama Continuity Checker Studio</div>
  <div class="hero-sub">
    Automated cross-episode contradiction discovery, LLM judgment, and human audit workbench
    for serialized screenplays.
  </div>
  <div class="hero-stats">
    <span class="hero-stat">📺 {ep_facts} Episode(s) Extracted</span>
    <span class="hero-stat">📝 {total_facts} Facts in Bible</span>
    <span class="hero-stat">🚩 {len(df)} Candidates</span>
    <span class="hero-stat" style="color:{prec_color};">🎯 Precision: {prec_display}</span>
  </div>
</div>
""", unsafe_allow_html=True)

    if using_demo:
        st.info(
            "No judged flags were found, so the app is showing built-in demo data. "
            "Run the parse → extract → bible → detect → judge pipeline to review real results.",
            icon=":material/science:",
        )

    # ── KPI Row ──────────────────────────────────────────────────────────────
    kc1, kc2, kc3, kc4, kc5 = st.columns(5)
    total_flags = len(df)

    kc1.metric("🚩 Total flags", total_flags)
    kc2.metric("✅ Accepted",            accepted)
    kc3.metric("❌ Rejected",            rejected)
    kc4.metric("⏳ Pending",             pending_count)
    kc5.metric("🎯 Live Precision",
               f"{precision_pct:.1f}%" if precision_pct is not None else "—",
               delta="Target ≥ 70%" if precision_pct is not None else None)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab_up, tab_r, tab_v, tab_b, tab_e = st.tabs([
        "📤 Upload & Run Pipeline",
        "🚩 Human Review Queue",
        "📊 Visual Analytics",
        "📖 Series Bible Explorer",
        "📥 Export Reports",
    ])

    with tab_up:
        render_upload_tab()

    with tab_r:
        reviews = render_review_tab(df, reviews)

    with tab_v:
        render_analytics_tab(df, reviews)

    with tab_b:
        render_bible_tab(bible, aliases)

    with tab_e:
        render_export_tab(df, reviews)


if __name__ == "__main__":
    main()
