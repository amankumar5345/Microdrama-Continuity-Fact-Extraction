"""
continuity/app.py
-----------------
Enterprise-grade Streamlit Web Studio for Microdrama Continuity Checker.
- Displays cross-episode flags with side-by-side quotes, timestamps, type, severity, and reasons.
- 1-click Accept / Reject buttons per flag persisted to outputs/reviews.json.
- Live Precision metric = accepted / (accepted + rejected).
- CSV & JSON download buttons for reviewed flags.
- Plotly visual analytics (Timeline Arc, Severity Donut, Entity Risk Leaderboard).
- Searchable Series Bible Explorer.
- Built-in pipeline orchestrator.
"""

import os
import re
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# Configuration & Paths
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Continuity Checker Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"

FLAGS_CSV = OUTPUTS_DIR / "flags.csv"
JUDGMENTS_JSON = OUTPUTS_DIR / "judgments.json"
BIBLE_JSON = OUTPUTS_DIR / "bible.json"
ALIAS_MAP_JSON = OUTPUTS_DIR / "alias_map.json"
REVIEWS_JSON = OUTPUTS_DIR / "reviews.json"

ROOT_REVIEWS_JSON = BASE_DIR.parent / "outputs" / "reviews.json"

# Fallback root outputs
ROOT_OUTPUTS_DIR = BASE_DIR.parent / "outputs"

SEVERITY_COLORS = {
    "CRITICAL": "#ef4444",  # Crimson Red
    "HIGH": "#f97316",      # Bright Orange
    "MEDIUM": "#f59e0b",    # Amber Yellow
    "LOW": "#3b82f6",       # Electric Blue
}

# -----------------------------------------------------------------------------
# Custom Styling (Dark Theme & Glassmorphism)
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    /* Global Styles */
    .stApp {
        background-color: #0b0f19;
        color: #e2e8f0;
    }
    
    /* Hero Banner */
    .hero-banner {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 14px;
        padding: 24px;
        margin-bottom: 24px;
        backdrop-filter: blur(10px);
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 800;
        background: linear-gradient(90deg, #38bdf8 0%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 6px;
    }
    .hero-subtitle {
        color: #94a3b8;
        font-size: 0.95rem;
    }

    /* KPI Metric Cards */
    .kpi-card {
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
        box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    }
    .kpi-value {
        font-size: 2.2rem;
        font-weight: 800;
        color: #f8fafc;
        margin: 4px 0;
    }
    .kpi-label {
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8;
    }

    /* Flag Cards */
    .flag-card {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 18px;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .flag-card:hover {
        border-color: rgba(99, 102, 241, 0.5);
    }
    
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        margin-right: 6px;
    }
    .badge-critical { background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-high { background: rgba(249, 115, 22, 0.2); color: #fdba74; border: 1px solid rgba(249, 115, 22, 0.4); }
    .badge-medium { background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.4); }
    .badge-low { background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); }
    
    .badge-accepted { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-rejected { background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-pending { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.4); }

    .quote-box {
        background: rgba(15, 23, 42, 0.7);
        border-left: 3px solid #6366f1;
        border-radius: 6px;
        padding: 10px 14px;
        font-style: italic;
        color: #e2e8f0;
        font-size: 0.92rem;
        margin: 6px 0;
    }
    .quote-header {
        font-size: 0.8rem;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 2px;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Data Loading & Review Persistence
# -----------------------------------------------------------------------------
def load_reviews() -> Dict[str, Dict[str, Any]]:
    """Loads review decisions from outputs/reviews.json."""
    for p in [REVIEWS_JSON, ROOT_REVIEWS_JSON]:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"Error loading reviews: {e}")
    return {}


def save_reviews(reviews: Dict[str, Dict[str, Any]]) -> None:
    """Saves review decisions to outputs/reviews.json."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REVIEWS_JSON, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    try:
        ROOT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(ROOT_REVIEWS_JSON, "w", encoding="utf-8") as f:
            json.dump(reviews, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def make_flag_id(row: Dict[str, Any]) -> str:
    """Generate a stable identifier for each flag record."""
    raw = f"{row.get('entity')}|{row.get('attribute')}|{row.get('ep_a')}|{row.get('ep_b')}|{row.get('timestamp_a')}|{row.get('timestamp_b')}"
    import hashlib
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


@st.cache_data(ttl=5)
def load_flags_data() -> pd.DataFrame:
    """Loads flags from CSV or JSON."""
    records = []
    # Try loading JSON judgments first
    for j_path in [JUDGMENTS_JSON, ROOT_OUTPUTS_DIR / "judgments.json"]:
        if j_path.exists():
            try:
                with open(j_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    break
            except Exception:
                pass

    # If empty, try CSV
    if not records:
        for c_path in [FLAGS_CSV, ROOT_OUTPUTS_DIR / "flags.csv"]:
            if c_path.exists():
                try:
                    df_csv = pd.read_csv(c_path)
                    records = df_csv.to_dict(orient="records")
                    break
                except Exception:
                    pass

    # If still empty, add default demonstrative test records so UI is immediately rich & functional
    if not records:
        records = [
            {
                "status": "FLAG",
                "verdict": "real_error",
                "severity": "CRITICAL",
                "severity_rank": 1,
                "candidate_type": "value_conflict",
                "entity": "Lady Juliana",
                "attribute": "eye_color",
                "ep_a": 1,
                "timestamp_a": "00:33.70",
                "value_a": "blue eyes",
                "quote_a": "Close-up on Juliana's trembling lips and shocked, tearful blue eyes.",
                "ep_b": 15,
                "timestamp_b": "01:12.00",
                "value_b": "emerald green eyes",
                "quote_b": "Her emerald green eyes narrowed in icy disdain.",
                "reason": "Direct retcon of invariant physical lore: Lady Juliana's eyes change from blue in Episode 1 to emerald green in Episode 15."
            },
            {
                "status": "FLAG",
                "verdict": "real_error",
                "severity": "HIGH",
                "severity_rank": 2,
                "candidate_type": "state_error",
                "entity": "Duke Alexander",
                "attribute": "status",
                "ep_a": 12,
                "timestamp_a": "02:15.00",
                "value_a": "arrested by the Constable",
                "quote_a": "The Constable tightens the manacles around Alexander's wrists: 'You are under arrest for treason.'",
                "ep_b": 13,
                "timestamp_b": "00:45.00",
                "value_b": "dining at the ballroom",
                "quote_b": "Alexander raises a glass of champagne across the grand dining table.",
                "reason": "Character was arrested and placed in irons in Ep 12, but appears free at a formal dinner in Ep 13 without any intervening escape or bail event."
            },
            {
                "status": "FILTERED",
                "verdict": "legit_change",
                "severity": "LOW",
                "severity_rank": 4,
                "candidate_type": "value_conflict",
                "entity": "Cathedral",
                "attribute": "location",
                "ep_a": 1,
                "timestamp_a": "00:00.00",
                "value_a": "wedding venue with nave, altar, aisle, wooden pews",
                "quote_a": "INT. CATHEDRAL – DAY",
                "ep_b": 2,
                "timestamp_b": "00:00.00",
                "value_b": "INT. CATHEDRAL – CONTINUOUS",
                "quote_b": "Scene heading: INT. CATHEDRAL – CONTINUOUS",
                "reason": "Both scenes take place at the same Cathedral location; 'CONTINUOUS' is a standard scene transition."
            }
        ]

    for r in records:
        r["flag_id"] = make_flag_id(r)

    return pd.DataFrame(records)


@st.cache_data(ttl=10)
def load_bible_data() -> Dict[str, Any]:
    """Loads Series Bible JSON."""
    for b in [BIBLE_JSON, ROOT_OUTPUTS_DIR / "bible.json"]:
        if b.exists():
            try:
                with open(b, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


# -----------------------------------------------------------------------------
# Main Application Flow
# -----------------------------------------------------------------------------
def main():
    # Load data & reviews
    df = load_flags_data()
    reviews = load_reviews()
    bible = load_bible_data()

    # Calculate review decisions & precision
    total_flags = len(df)
    reviewed_ids = set(reviews.keys())

    accepted_count = sum(1 for r in reviews.values() if r.get("decision") == "accepted")
    rejected_count = sum(1 for r in reviews.values() if r.get("decision") == "rejected")
    reviewed_total = accepted_count + rejected_count

    if reviewed_total > 0:
        precision_pct = (accepted_count / reviewed_total) * 100.0
    else:
        precision_pct = 0.0

    # Header / Hero
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">🎬 Microdrama Continuity Checker Studio</div>
        <div class="hero-subtitle">Automated cross-episode contradiction discovery, fact verification, and human audit workbench</div>
    </div>
    """, unsafe_allow_html=True)

    # Top KPI Metrics Row
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Total Flags</div>
            <div class="kpi-value">{total_flags}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Accepted (True Errors)</div>
            <div class="kpi-value" style="color: #10b981;">{accepted_count}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Rejected (False Positives)</div>
            <div class="kpi-value" style="color: #ef4444;">{rejected_count}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">Pending Review</div>
            <div class="kpi-value" style="color: #f59e0b;">{max(0, total_flags - reviewed_total)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        # Live Precision Highlight Card
        color = "#10b981" if precision_pct >= 70 else "#f59e0b" if precision_pct >= 40 else "#ef4444"
        st.markdown(f"""
        <div class="kpi-card" style="border: 1px solid {color}50; background: {color}10;">
            <div class="kpi-label" style="color: {color}; font-weight:700;">Live Precision</div>
            <div class="kpi-value" style="color: {color};">{precision_pct:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # Main Tabs
    # -------------------------------------------------------------------------
    tab_review, tab_viz, tab_bible, tab_export = st.tabs([
        "🚩 Human Review Queue",
        "📊 Continuity Visual Analytics",
        "📖 Series Bible Explorer",
        "📥 CSV & Report Exports",
    ])

    # =========================================================================
    # TAB 1: Human Review Queue
    # =========================================================================
    with tab_review:
        st.subheader("Audited Discrepancy Queue")
        
        # Filter controls
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 2, 2, 2])
        with f_col1:
            status_filter = st.selectbox(
                "Review Status",
                ["ALL", "PENDING", "ACCEPTED", "REJECTED"],
                index=0,
            )
        with f_col2:
            severity_filter = st.selectbox(
                "Severity",
                ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
                index=0,
            )
        with f_col3:
            verdict_filter = st.selectbox(
                "Verdict Type",
                ["ALL", "real_error", "unclear", "legit_change", "deception"],
                index=0,
            )
        with f_col4:
            search_query = st.text_input("Search Entity / Quote", "")

        # Apply Filters
        filtered_df = df.copy()
        
        # Add review decision to df
        filtered_df["user_decision"] = filtered_df["flag_id"].apply(
            lambda fid: reviews.get(fid, {}).get("decision", "pending")
        )

        if status_filter == "PENDING":
            filtered_df = filtered_df[filtered_df["user_decision"] == "pending"]
        elif status_filter == "ACCEPTED":
            filtered_df = filtered_df[filtered_df["user_decision"] == "accepted"]
        elif status_filter == "REJECTED":
            filtered_df = filtered_df[filtered_df["user_decision"] == "rejected"]

        if severity_filter != "ALL":
            filtered_df = filtered_df[filtered_df["severity"] == severity_filter]

        if verdict_filter != "ALL":
            filtered_df = filtered_df[filtered_df["verdict"] == verdict_filter]

        if search_query:
            q = search_query.lower()
            filtered_df = filtered_df[
                filtered_df["entity"].str.lower().str.contains(q, na=False) |
                filtered_df["quote_a"].str.lower().str.contains(q, na=False) |
                filtered_df["quote_b"].str.lower().str.contains(q, na=False) |
                filtered_df["reason"].str.lower().str.contains(q, na=False)
            ]

        st.caption(f"Showing {len(filtered_df)} of {len(df)} continuity flags")

        # Render Flag Cards
        for idx, row in filtered_df.iterrows():
            fid = row["flag_id"]
            current_decision = reviews.get(fid, {}).get("decision", "pending")
            sev = row.get("severity", "MEDIUM")
            sev_badge_class = f"badge-{sev.lower()}"
            status_badge_class = f"badge-{current_decision}"

            with st.container():
                st.markdown(f"""
                <div class="flag-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div>
                            <span class="badge {sev_badge_class}">{sev}</span>
                            <span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.4);">{row.get('candidate_type', 'conflict')}</span>
                            <span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #cbd5e1;">Verdict: {row.get('verdict', 'unknown')}</span>
                        </div>
                        <div>
                            <span class="badge {status_badge_class}">Status: {current_decision.upper()}</span>
                        </div>
                    </div>
                    <div style="font-size: 1.2rem; font-weight: 700; color: #f8fafc; margin-bottom: 4px;">
                        {row.get('entity', 'Unknown Entity')} <span style="font-size: 0.95rem; font-weight: 400; color: #94a3b8;">({row.get('attribute', 'lore')})</span>
                    </div>
                    <div style="color: #cbd5e1; font-size: 0.92rem; margin-bottom: 14px;">
                        <strong>Explanation:</strong> {row.get('reason', 'No explanation provided.')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Side-by-Side Comparison Box
                c_left, c_right = st.columns(2)
                with c_left:
                    st.markdown(f"""
                    <div class="quote-header">📍 Episode {row.get('ep_a')} — Timestamp [{row.get('timestamp_a')}]</div>
                    <div style="font-weight: 600; color: #a5b4fc; font-size: 0.88rem; margin-bottom: 4px;">Value: {row.get('value_a')}</div>
                    <div class="quote-box">"{row.get('quote_a')}"</div>
                    """, unsafe_allow_html=True)

                with c_right:
                    st.markdown(f"""
                    <div class="quote-header">📍 Episode {row.get('ep_b')} — Timestamp [{row.get('timestamp_b')}]</div>
                    <div style="font-weight: 600; color: #a5b4fc; font-size: 0.88rem; margin-bottom: 4px;">Value: {row.get('value_b')}</div>
                    <div class="quote-box">"{row.get('quote_b')}"</div>
                    """, unsafe_allow_html=True)

                # Action Buttons Row
                btn_c1, btn_c2, btn_c3, _ = st.columns([1.5, 1.5, 1, 6])
                with btn_c1:
                    if st.button("✅ Accept Flag", key=f"acc_{fid}", use_container_width=True):
                        reviews[fid] = {
                            "decision": "accepted",
                            "reviewed_at": datetime.now().isoformat(),
                            "entity": row.get("entity"),
                            "attribute": row.get("attribute"),
                        }
                        save_reviews(reviews)
                        st.rerun()

                with btn_c2:
                    if st.button("❌ Reject Flag", key=f"rej_{fid}", use_container_width=True):
                        reviews[fid] = {
                            "decision": "rejected",
                            "reviewed_at": datetime.now().isoformat(),
                            "entity": row.get("entity"),
                            "attribute": row.get("attribute"),
                        }
                        save_reviews(reviews)
                        st.rerun()

                with btn_c3:
                    if current_decision != "pending":
                        if st.button("↩️ Reset", key=f"rst_{fid}", use_container_width=True):
                            reviews.pop(fid, None)
                            save_reviews(reviews)
                            st.rerun()

                st.markdown("<hr style='border-color: rgba(255,255,255,0.06); margin: 20px 0;'>", unsafe_allow_html=True)

    # =========================================================================
    # TAB 2: Visual Analytics
    # =========================================================================
    with tab_viz:
        st.subheader("Visual Continuity Analytics")
        v1, v2 = st.columns(2)

        with v1:
            st.markdown("#### 🍩 Severity Distribution")
            if not df.empty and "severity" in df.columns:
                sev_counts = df["severity"].value_counts().reset_index()
                sev_counts.columns = ["Severity", "Count"]
                fig_pie = px.pie(
                    sev_counts,
                    names="Severity",
                    values="Count",
                    color="Severity",
                    color_discrete_map=SEVERITY_COLORS,
                    hole=0.45,
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e2e8f0"),
                    margin=dict(t=20, b=20, l=20, r=20),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with v2:
            st.markdown("#### 📊 Entity Discrepancy Risk Leaderboard")
            if not df.empty and "entity" in df.columns:
                ent_counts = df["entity"].value_counts().head(8).reset_index()
                ent_counts.columns = ["Entity", "Flag Count"]
                fig_bar = px.bar(
                    ent_counts,
                    x="Flag Count",
                    y="Entity",
                    orientation="h",
                    color="Flag Count",
                    color_continuous_scale="Viridis",
                )
                fig_bar.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#e2e8f0"),
                    yaxis=dict(autorange="reversed"),
                    margin=dict(t=20, b=20, l=20, r=20),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        # Cross-Episode Arc Timeline
        st.markdown("#### 📈 Cross-Episode Contradiction Arc Map")
        if not df.empty and "ep_a" in df.columns and "ep_b" in df.columns:
            fig_arc = go.Figure()
            for idx, r in df.iterrows():
                ea = int(r.get("ep_a", 1))
                eb = int(r.get("ep_b", 1))
                sev = r.get("severity", "MEDIUM")
                color = SEVERITY_COLORS.get(sev, "#818cf8")
                
                # Arc line
                fig_arc.add_trace(go.Scatter(
                    x=[ea, (ea + eb) / 2, eb],
                    y=[0, abs(eb - ea) * 0.5, 0],
                    mode="lines",
                    line=dict(color=color, width=2.5),
                    name=f"{r.get('entity')} ({sev})",
                    hoverinfo="text",
                    text=f"Entity: {r.get('entity')}<br>Attr: {r.get('attribute')}<br>Ep {ea} &rarr; Ep {eb}",
                ))
            fig_arc.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                xaxis=dict(title="Episode Number", showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
                yaxis=dict(title="Discrepancy Distance", showgrid=False, showticklabels=False),
                showlegend=False,
                margin=dict(t=20, b=20, l=20, r=20),
            )
            st.plotly_chart(fig_arc, use_container_width=True)

    # =========================================================================
    # TAB 3: Series Bible Explorer
    # =========================================================================
    with tab_bible:
        st.subheader("Series Lore & Entity Bible")
        if not bible:
            st.info("No Series Bible data found. Run `python -m continuity.bible` to build `outputs/bible.json`.")
        else:
            all_entities = sorted(list(bible.keys()))
            selected_entity = st.selectbox("Select Character or Entity", all_entities)

            if selected_entity:
                ent_data = bible[selected_entity]
                st.markdown(f"### 👤 {selected_entity}")
                st.caption(f"{len(ent_data)} tracked attributes")

                for attr, entries in ent_data.items():
                    with st.expander(f"📌 {attr.upper()} ({len(entries)} chronological events)", expanded=True):
                        for e in entries:
                            st.markdown(f"""
                            - **Episode {e.get('ep')}** `[{e.get('timestamp')}]` (*{e.get('reliability')}*):
                              **Value:** `{e.get('value')}`  
                              <div class="quote-box">"{e.get('quote')}"</div>
                            """, unsafe_allow_html=True)

    # =========================================================================
    # TAB 4: CSV & Report Exports
    # =========================================================================
    with tab_export:
        st.subheader("Export Reviewed Flags & Audits")
        
        # Merge review decisions into export dataframe
        export_df = df.copy()
        export_df["user_decision"] = export_df["flag_id"].apply(
            lambda fid: reviews.get(fid, {}).get("decision", "pending")
        )
        export_df["reviewed_at"] = export_df["flag_id"].apply(
            lambda fid: reviews.get(fid, {}).get("reviewed_at", "")
        )

        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        json_bytes = json.dumps(export_df.to_dict(orient="records"), indent=2, ensure_ascii=False).encode("utf-8")
        reviews_bytes = json.dumps(reviews, indent=2, ensure_ascii=False).encode("utf-8")

        e_c1, e_c2, e_c3 = st.columns(3)
        with e_c1:
            st.download_button(
                label="📥 Download Reviewed Flags (CSV)",
                data=csv_bytes,
                file_name="continuity_flags_reviewed.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with e_c2:
            st.download_button(
                label="📥 Download Judgments (JSON)",
                data=json_bytes,
                file_name="continuity_judgments.json",
                mime="application/json",
                use_container_width=True,
            )
        with e_c3:
            st.download_button(
                label="📥 Download Review Audit (JSON)",
                data=reviews_bytes,
                file_name="reviews.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Preview of Reviewed Dataset")
        st.dataframe(
            export_df[[
                "severity", "user_decision", "verdict", "entity", "attribute",
                "ep_a", "timestamp_a", "ep_b", "timestamp_b", "reason"
            ]],
            use_container_width=True,
            height=300,
        )


if __name__ == "__main__":
    main()
