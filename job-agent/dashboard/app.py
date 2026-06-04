"""
dashboard/app.py – Streamlit analytics dashboard for the Job Application Agent.

Run via:
    streamlit run dashboard/app.py
Or via the CLI:
    python main.py --dashboard
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Allow imports from project root ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "db" / "jobs.db"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Job Agent Dashboard",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB helpers (all sync wrappers around async aiosqlite calls) ───────────────


def _run(coro):
    """Run a coroutine synchronously, reusing an event loop where possible."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _fetch_all_jobs() -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, title, company, url, platform, domain, relevance_score, "
            "status, applied_at, discovered_at FROM jobs ORDER BY discovered_at DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetch_applications() -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT a.id, a.job_id, a.applied_at, a.applied_via, "
            "j.title, j.company, j.platform, j.domain, j.relevance_score, j.status, j.url "
            "FROM applications a "
            "JOIN jobs j ON a.job_id = j.id "
            "ORDER BY a.applied_at DESC "
            "LIMIT 200"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetch_responses() -> list[dict]:
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT r.id, r.job_id, r.received_at, r.response_type, "
            "j.title, j.company "
            "FROM responses r "
            "LEFT JOIN jobs j ON r.job_id = j.id "
            "ORDER BY r.received_at DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _fetch_daily_counts(days: int = 30) -> list[dict]:
    """Applications per day for the last *days* days."""
    import aiosqlite
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT date(applied_at) AS day, COUNT(*) AS cnt
            FROM applications
            WHERE applied_at >= date('now', ? || ' days')
            GROUP BY day
            ORDER BY day
            """,
            (f"-{days}",),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Cached data loaders ───────────────────────────────────────────────────────


@st.cache_data(ttl=300)
def load_jobs() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    rows = _run(_fetch_all_jobs())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["applied_at"] = pd.to_datetime(df["applied_at"], errors="coerce", utc=True)
    df["discovered_at"] = pd.to_datetime(df["discovered_at"], errors="coerce", utc=True)
    df["relevance_score"] = pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0.0)
    return df


@st.cache_data(ttl=300)
def load_applications() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    rows = _run(_fetch_applications())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["applied_at"] = pd.to_datetime(df["applied_at"], errors="coerce", utc=True)
    df["relevance_score"] = pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0.0)
    return df


@st.cache_data(ttl=300)
def load_responses() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    rows = _run(_fetch_responses())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["received_at"] = pd.to_datetime(df["received_at"], errors="coerce", utc=True)
    return df


@st.cache_data(ttl=300)
def load_daily_counts(days: int = 30) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["day", "cnt"])
    rows = _run(_fetch_daily_counts(days))
    if not rows:
        return pd.DataFrame(columns=["day", "cnt"])
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    df["cnt"] = pd.to_numeric(df["cnt"], errors="coerce").fillna(0).astype(int)
    return df


# ── Status badge helper ───────────────────────────────────────────────────────

_STATUS_COLORS: dict[str, str] = {
    "new": "#6c757d",
    "scored": "#17a2b8",
    "applying": "#ffc107",
    "applied": "#007bff",
    "rejected": "#dc3545",
    "interview": "#28a745",
    "offer": "#fd7e14",
    "skipped": "#adb5bd",
}


def _badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, "#6c757d")
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:10px;font-size:0.78em;font-weight:600;">{status}</span>'
    )


# ── Main layout ───────────────────────────────────────────────────────────────

st.title("Job Agent Dashboard")

# ── Guard: no DB yet ──────────────────────────────────────────────────────────
if not DB_PATH.exists():
    st.info("No data yet — run `python main.py --run` or `--dry-run` to populate the database.")
    st.stop()

jobs_df = load_jobs()
apps_df = load_applications()
resp_df = load_responses()
daily_df = load_daily_counts(30)

if jobs_df.empty:
    st.info("Database exists but contains no jobs yet. Run the agent to start collecting data.")
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.header("Filters")

all_domains = sorted(jobs_df["domain"].dropna().unique().tolist()) if "domain" in jobs_df else []
all_statuses = sorted(jobs_df["status"].dropna().unique().tolist()) if "status" in jobs_df else []
all_platforms = sorted(jobs_df["platform"].dropna().unique().tolist()) if "platform" in jobs_df else []

sel_domains = st.sidebar.multiselect(
    "Domain", options=all_domains, default=all_domains
)
sel_statuses = st.sidebar.multiselect(
    "Status", options=all_statuses, default=all_statuses
)
sel_platforms = st.sidebar.multiselect(
    "Platform", options=all_platforms, default=all_platforms
)

today = date.today()
default_start = today - timedelta(days=30)
date_range = st.sidebar.date_input(
    "Date range",
    value=(default_start, today),
    min_value=today - timedelta(days=365),
    max_value=today,
)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    filter_start, filter_end = date_range
else:
    filter_start, filter_end = default_start, today

# Apply filters to jobs
mask = pd.Series(True, index=jobs_df.index)
if sel_domains:
    mask &= jobs_df["domain"].isin(sel_domains)
if sel_statuses:
    mask &= jobs_df["status"].isin(sel_statuses)
if sel_platforms:
    mask &= jobs_df["platform"].isin(sel_platforms)
if "discovered_at" in jobs_df.columns:
    ts_start = pd.Timestamp(filter_start, tz="UTC")
    ts_end = pd.Timestamp(filter_end, tz="UTC") + pd.Timedelta(days=1)
    mask &= (jobs_df["discovered_at"] >= ts_start) & (jobs_df["discovered_at"] < ts_end)

filtered_df = jobs_df[mask].copy()

# ── Metric cards ──────────────────────────────────────────────────────────────
total_applied = int((filtered_df["status"] == "applied").sum()) + \
                int((filtered_df["status"] == "interview").sum()) + \
                int((filtered_df["status"] == "offer").sum())

total_with_response = int((filtered_df["status"].isin(["interview", "offer", "rejected"])).sum())
response_rate = (
    round(total_with_response / total_applied * 100, 1) if total_applied > 0 else 0.0
)

active_interviews = int((filtered_df["status"] == "interview").sum())
offers = int((filtered_df["status"] == "offer").sum())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Applied", total_applied)
col2.metric("Response Rate", f"{response_rate}%")
col3.metric("Active Interviews", active_interviews)
col4.metric("Offers", offers)

st.divider()

# ── Row 2: bar chart + pie chart side-by-side ─────────────────────────────────
chart_col, pie_col = st.columns([3, 2])

with chart_col:
    st.subheader("Applications per Day (last 30 days)")
    if daily_df.empty:
        st.caption("No application data for the last 30 days.")
    else:
        fig_bar = px.bar(
            daily_df,
            x="day",
            y="cnt",
            labels={"day": "Date", "cnt": "Applications"},
            color_discrete_sequence=["#007bff"],
        )
        fig_bar.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor="#e0e0e0"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with pie_col:
    st.subheader("Status Distribution")
    status_counts = filtered_df["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    if status_counts.empty:
        st.caption("No jobs match the current filters.")
    else:
        color_map = {s: c for s, c in _STATUS_COLORS.items()}
        fig_pie = px.pie(
            status_counts,
            names="status",
            values="count",
            color="status",
            color_discrete_map=color_map,
            hole=0.35,
        )
        fig_pie.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.25),
        )
        fig_pie.update_traces(textinfo="percent+label")
        st.plotly_chart(fig_pie, use_container_width=True)

st.divider()

# ── Domain × response-type heatmap ───────────────────────────────────────────
st.subheader("Domain Response Rate Heatmap")

if resp_df.empty or jobs_df.empty:
    st.caption("Not enough response data to render heatmap.")
else:
    # Join responses with jobs to get domain
    resp_with_domain = resp_df.merge(
        jobs_df[["id", "domain"]].rename(columns={"id": "job_id"}),
        on="job_id",
        how="left",
    )
    resp_with_domain = resp_with_domain.dropna(subset=["domain", "response_type"])

    if resp_with_domain.empty:
        st.caption("No domain-labelled responses yet.")
    else:
        heat_pivot = (
            resp_with_domain
            .groupby(["domain", "response_type"])
            .size()
            .unstack(fill_value=0)
        )
        fig_heat = px.imshow(
            heat_pivot,
            labels=dict(x="Response Type", y="Domain", color="Count"),
            color_continuous_scale="Blues",
            aspect="auto",
            text_auto=True,
        )
        fig_heat.update_layout(
            margin=dict(l=0, r=0, t=30, b=0),
            coloraxis_showscale=True,
        )
        st.plotly_chart(fig_heat, use_container_width=True)

st.divider()

# ── Recent applications table ─────────────────────────────────────────────────
st.subheader("Recent Applications (last 50)")

display_cols = ["title", "company", "domain", "relevance_score", "status", "applied_at", "url"]
if not apps_df.empty:
    recent = apps_df.copy()
    # Filter to match sidebar date range
    if "applied_at" in recent.columns:
        ts_start = pd.Timestamp(filter_start, tz="UTC")
        ts_end = pd.Timestamp(filter_end, tz="UTC") + pd.Timedelta(days=1)
        recent = recent[
            (recent["applied_at"] >= ts_start) & (recent["applied_at"] < ts_end)
        ]
    if "domain" in recent.columns and sel_domains:
        recent = recent[recent["domain"].isin(sel_domains)]
    if "platform" in recent.columns and sel_platforms:
        recent = recent[recent["platform"].isin(sel_platforms)]

    recent = recent.sort_values("applied_at", ascending=False).head(50)

    if recent.empty:
        st.caption("No applications match the current filters.")
    else:
        # Format for display
        show = recent[
            [c for c in ["title", "url", "company", "domain", "relevance_score", "status", "applied_at"]
             if c in recent.columns]
        ].copy()

        show["relevance_score"] = show["relevance_score"].map(lambda x: f"{x:.2f}")
        show["applied_at"] = show["applied_at"].dt.strftime("%Y-%m-%d %H:%M UTC")

        # Build HTML table with clickable title and status badge
        rows_html = []
        for _, row in show.iterrows():
            url = row.get("url", "#") or "#"
            title = row.get("title", "—")
            link = f'<a href="{url}" target="_blank">{title}</a>'
            badge = _badge(str(row.get("status", "—")))
            rows_html.append(
                f"<tr>"
                f"<td>{link}</td>"
                f"<td>{row.get('company', '—')}</td>"
                f"<td>{row.get('domain', '—')}</td>"
                f"<td style='text-align:center'>{row.get('relevance_score', '—')}</td>"
                f"<td>{badge}</td>"
                f"<td>{row.get('applied_at', '—')}</td>"
                f"</tr>"
            )

        header = (
            "<thead><tr>"
            "<th>Job Title</th><th>Company</th><th>Domain</th>"
            "<th>Score</th><th>Status</th><th>Applied At</th>"
            "</tr></thead>"
        )
        table_html = (
            '<table style="width:100%;border-collapse:collapse;">'
            + header
            + "<tbody>"
            + "\n".join(rows_html)
            + "</tbody></table>"
        )
        st.markdown(table_html, unsafe_allow_html=True)
else:
    st.caption("No application records found.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    f"Dashboard refreshes every 5 minutes. Last loaded: "
    f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
    f"DB: `{DB_PATH}`"
)
