"""Streamlit dashboard.

Two views:
  - Main table: ranked clusters with filters
  - Detail page: per-cluster stats, viability memo, raw complaints

Run: streamlit run src/signalwarn/app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from signalwarn.config import settings
from signalwarn.db import engine
from signalwarn.viability import regenerate_memo_if_needed

st.set_page_config(page_title="SIGNAL — Goff Law", layout="wide", page_icon="🔴")

CLASSIFICATION_EMOJI = {
    "CRITICAL": "🔴",
    "HOT": "🟠",
    "WATCH": "🟡",
    "MONITOR": "🟢",
}
CLASSIFICATION_ORDER = ["CRITICAL", "HOT", "WATCH", "MONITOR"]


# ─── Auth (single-user MVP) ─────────────────────────────────────────────

def _require_login() -> None:
    if st.session_state.get("authed"):
        return
    st.title("🔴 SIGNAL")
    st.caption("Goff Law PLLC — internal use only.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if username == settings.signal_username and password == settings.signal_password:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid credentials.")
    st.stop()


# ─── Data loaders ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_clusters() -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT id, cluster_key, make, model, model_year, component, is_multi_year,
               complaint_count, injury_count, death_count, crash_count, fire_count,
               velocity_30d, score, classification,
               first_complaint_date, last_complaint_date, updated_at
          FROM clusters
         WHERE classification != 'NOISE'
         ORDER BY score DESC, complaint_count DESC
        """,
        engine(),
    )


@st.cache_data(ttl=60)
def load_cluster(cluster_id: int) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT * FROM clusters WHERE id = %(id)s",
        engine(),
        params={"id": cluster_id},
    )


@st.cache_data(ttl=60)
def load_complaints(cluster_id: int) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT c.* FROM complaints c
          JOIN cluster_complaints cc ON cc.complaint_id = c.id
         WHERE cc.cluster_id = %(id)s
         ORDER BY c.date_complaint_filed DESC NULLS LAST
        """,
        engine(),
        params={"id": cluster_id},
    )


@st.cache_data(ttl=60)
def load_last_ingestion() -> dict | None:
    df = pd.read_sql(
        "SELECT * FROM ingestion_log ORDER BY run_at DESC LIMIT 1",
        engine(),
    )
    return None if df.empty else df.iloc[0].to_dict()


# ─── Pages ──────────────────────────────────────────────────────────────

def _render_main() -> None:
    df = load_clusters()
    last_run = load_last_ingestion()

    st.title("🔴 SIGNAL — Mass Tort Early Warning")
    if last_run:
        st.caption(f"Last ingestion: {last_run['run_at']} — status {last_run['status']}")

    counts = df["classification"].value_counts()
    cols = st.columns(4)
    for col, label in zip(cols, CLASSIFICATION_ORDER):
        col.metric(f"{CLASSIFICATION_EMOJI[label]} {label}", int(counts.get(label, 0)))

    with st.expander("Filters", expanded=True):
        makes = ["(all)", *sorted(df["make"].unique())]
        years = ["(all)", *sorted(df["model_year"].dropna().astype(int).unique().tolist())]
        cls = ["(all)", *CLASSIFICATION_ORDER]
        windows = {
            "All time": None,
            "Past year": 365,
            "Past 6 months": 180,
            "Past 90 days": 90,
            "Past 30 days": 30,
        }
        f_window = st.selectbox(
            "Activity window",
            list(windows.keys()),
            index=2,  # default "Past 6 months"
            help="Show only clusters with a complaint filed in this window. "
                 "Score still reflects lifetime data.",
        )
        f_make = st.selectbox("Make", makes, index=0)
        f_year = st.selectbox("Model year", years, index=0)
        f_cls = st.selectbox("Classification", cls, index=0)
        q = st.text_input("Search make / model / component")

    filt = df
    window_days = windows[f_window]
    if window_days is not None:
        floor = pd.Timestamp(date.today() - pd.Timedelta(days=window_days))
        last = pd.to_datetime(filt["last_complaint_date"], errors="coerce")
        filt = filt[last >= floor]
    if f_make != "(all)":
        filt = filt[filt["make"] == f_make]
    if f_year != "(all)":
        filt = filt[filt["model_year"] == f_year]
    if f_cls != "(all)":
        filt = filt[filt["classification"] == f_cls]
    if q:
        ql = q.lower()
        filt = filt[
            filt["make"].str.lower().str.contains(ql)
            | filt["model"].str.lower().str.contains(ql)
            | filt["component"].str.lower().str.contains(ql)
        ]

    st.divider()
    if filt.empty:
        st.info("No clusters match these filters.")
        return

    # Build a presentation-ready frame.
    display = filt.assign(
        Vehicle=filt.apply(
            lambda r: f"{'multi-year' if pd.isna(r['model_year']) else int(r['model_year'])} "
                      f"{r['make'].title()} {r['model'].title()}",
            axis=1,
        ),
        Status=filt["classification"].map(
            lambda c: f"{CLASSIFICATION_EMOJI.get(c, '')} {c}"
        ),
    ).rename(
        columns={
            "component": "Component",
            "complaint_count": "Complaints",
            "injury_count": "Injuries",
            "death_count": "Deaths",
            "velocity_30d": "Δ 30d",
            "score": "Score",
        }
    )[
        [
            "id",
            "Status",
            "Vehicle",
            "Component",
            "Complaints",
            "Injuries",
            "Deaths",
            "Δ 30d",
            "Score",
        ]
    ]

    st.caption(f"{len(display):,} cluster(s). Click a row to open detail.")
    event = st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=600,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "id": None,  # hidden — used only to look up the selected cluster
            "Status": st.column_config.TextColumn(width="small"),
            "Vehicle": st.column_config.TextColumn(width="medium"),
            "Component": st.column_config.TextColumn(width="medium"),
            "Complaints": st.column_config.NumberColumn(format="%d"),
            "Injuries": st.column_config.NumberColumn(format="%d"),
            "Deaths": st.column_config.NumberColumn(format="%d"),
            "Δ 30d": st.column_config.NumberColumn(format="%d"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
        },
        key="cluster_table",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        cluster_id = int(display.iloc[selected_rows[0]]["id"])
        st.session_state["cluster_id"] = cluster_id
        st.rerun()


def _render_detail(cluster_id: int) -> None:
    df = load_cluster(cluster_id)
    if df.empty:
        st.error("Cluster not found.")
        if st.button("← Back"):
            del st.session_state["cluster_id"]
            st.rerun()
        return

    cluster = df.iloc[0].to_dict()
    if st.button("← Back to dashboard"):
        del st.session_state["cluster_id"]
        st.rerun()

    emoji = CLASSIFICATION_EMOJI.get(cluster["classification"], "")
    year = "multi-year" if pd.isna(cluster["model_year"]) else int(cluster["model_year"])
    st.title(f"{emoji} {cluster['classification']} — Score {cluster['score']}/100")
    st.subheader(f"{year} {cluster['make'].title()} {cluster['model'].title()} · {cluster['component']}")

    cols = st.columns(6)
    cols[0].metric("Complaints", int(cluster["complaint_count"]))
    cols[1].metric("Injuries", int(cluster["injury_count"]))
    cols[2].metric("Deaths", int(cluster["death_count"]))
    cols[3].metric("Crashes", int(cluster["crash_count"]))
    cols[4].metric("Fires", int(cluster["fire_count"]))
    cols[5].metric("Δ 30 days", int(cluster["velocity_30d"]))

    st.divider()
    st.subheader("AI viability memo")
    if cluster.get("viability_memo"):
        st.markdown(cluster["viability_memo"])
        st.caption(f"Generated: {cluster.get('memo_generated_at')}")
    else:
        st.info("No memo generated yet.")
    if st.button("Regenerate memo", disabled=not settings.anthropic_api_key):
        with st.spinner("Calling Claude…"):
            regenerate_memo_if_needed(cluster_id, force=True)
        st.cache_data.clear()
        st.rerun()
    if not settings.anthropic_api_key:
        st.caption("Set ANTHROPIC_API_KEY in .env to enable memo generation.")

    st.divider()
    st.subheader("Complaint volume")
    complaints = load_complaints(cluster_id)
    if not complaints.empty and "date_complaint_filed" in complaints:
        per_month = (
            complaints.dropna(subset=["date_complaint_filed"])
            .assign(month=lambda d: pd.to_datetime(d["date_complaint_filed"]).dt.to_period("M").astype(str))
            .groupby("month")
            .size()
            .reset_index(name="count")
        )
        st.bar_chart(per_month, x="month", y="count")

    st.divider()
    st.subheader(f"Raw complaints ({len(complaints)})")
    if not complaints.empty:
        st.dataframe(
            complaints[
                [
                    "date_complaint_filed",
                    "state",
                    "crash",
                    "injuries",
                    "deaths",
                    "component",
                    "description",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


# ─── Entry point ────────────────────────────────────────────────────────

def main() -> None:
    _require_login()
    cluster_id = st.session_state.get("cluster_id")
    if cluster_id is None:
        _render_main()
    else:
        _render_detail(int(cluster_id))


if __name__ == "__main__":
    main()
else:
    main()
