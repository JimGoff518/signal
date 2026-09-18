"""Read queries used by the FastAPI dashboard.

Pure SQL via the shared psycopg connection helper. Returns plain dicts
(thanks to dict_row factory) — no ORM, no pandas.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from signalwarn.clustering import EXCLUDE_FILED_SQL
from signalwarn.db import connection

# Activity-window options shown in the filter dropdown. Keys are the labels;
# values are the day floor (or None for "all time").
ACTIVITY_WINDOWS: dict[str, int | None] = {
    "All time": None,
    "Past year": 365,
    "Past 6 months": 180,
    "Past 90 days": 90,
    "Past 60 days": 60,
    "Past 30 days": 30,
}

# Whitelist of dashboard table columns that can be sorted on. Keys are the
# `?sort=` URL param values; values are the SQL ORDER BY expression. The
# `vehicle` sort is special-cased in _build_order_by because it spans multiple
# columns and each needs the same direction applied.
SORT_COLUMNS: dict[str, str] = {
    "class": (
        "CASE c.classification WHEN 'CRITICAL' THEN 0 WHEN 'HOT' THEN 1 "
        "WHEN 'WATCH' THEN 2 WHEN 'MONITOR' THEN 3 ELSE 4 END"
    ),
    "vehicle": "c.make, c.model, c.model_year",
    "last": "c.last_complaint_date",
    "total": "c.complaint_count",
    "inj": "c.injury_count",
    "dth": "c.death_count",
    "velocity": "c.velocity_30d",
    "tx": "c.tx_complaint_count",
    "score": "c.score",
}

# Default direction for each sort column when first clicked. Strings/dates
# default to ASC (alphabetical / oldest-first); counts default to DESC.
SORT_DEFAULT_DIR: dict[str, str] = {
    "class": "asc",
    "vehicle": "asc",
    "last": "desc",
    "total": "desc",
    "inj": "desc",
    "dth": "desc",
    "velocity": "desc",
    "tx": "desc",
    "score": "desc",
}


def _build_order_by(sort: str, direction: str) -> str:
    """Resolve a `(sort, direction)` pair to a safe ORDER BY clause.

    Falls back to the default sort if `sort` isn't in the whitelist — that
    keeps a malformed URL from leaking SQL.
    """
    direction = "ASC" if direction.lower() == "asc" else "DESC"
    nulls = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
    if sort == "vehicle":
        # Apply the same direction to make/model/year for a stable alphabetical sort.
        return (
            f"c.make {direction}, c.model {direction}, c.model_year {direction} {nulls}"
        )
    expr = SORT_COLUMNS.get(sort, SORT_COLUMNS["score"])
    return f"{expr} {direction} {nulls}"


def _build_filters(
    *,
    activity_window_days: int | None = None,
    make: str | None = None,
    model_year: int | None = None,
    component: str | None = None,
    classification: str | None = None,
    recall: str | None = None,
    filed: str | None = None,
    tx_min: int | None = None,
    search: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Translate dashboard filter inputs into a WHERE clause + params.

    Pure function (no DB) so it can be unit-tested. Every query that has to
    agree with the dashboard table (counts, charts) goes through here so the
    numbers on screen always describe the same slice.

    `recall` / `filed` are tri-state strings from the form: "1" = only rows
    with the flag, "0" = only rows without it, anything else = no filter.
    """
    # Any cluster with a filed class action (pending or terminated) is not an
    # opportunity for the firm, so it is excluded by default. `filed="1"` is
    # the audit view that shows ONLY those clusters; `filed="0"` is the default.
    where = ["c.classification != 'NOISE'"]
    params: dict[str, Any] = {}

    if activity_window_days is not None:
        where.append("c.last_complaint_date >= %(floor)s")
        params["floor"] = date.today() - timedelta(days=activity_window_days)

    if make:
        where.append("c.make = %(make)s")
        params["make"] = make.upper()

    if model_year is not None:
        where.append("c.model_year = %(year)s")
        params["year"] = model_year

    if component:
        where.append("c.component = %(component)s")
        params["component"] = component.upper()

    if classification and classification != "ALL":
        where.append("c.classification = %(classification)s")
        params["classification"] = classification.upper()

    if recall == "1":
        where.append("c.recall_issued = TRUE")
    elif recall == "0":
        where.append("c.recall_issued = FALSE")

    if filed == "1":
        where.append("c.class_action_filed = TRUE")
    else:
        where.append(EXCLUDE_FILED_SQL)

    # Phase 2 Texas filter: at least N live complaints from Texas owners.
    if tx_min:
        where.append("c.tx_complaint_count >= %(tx_min)s")
        params["tx_min"] = int(tx_min)

    if search:
        where.append(
            "(LOWER(c.make) LIKE %(q)s "
            "OR LOWER(c.model) LIKE %(q)s "
            "OR LOWER(c.component) LIKE %(q)s)"
        )
        params["q"] = f"%{search.lower()}%"

    return " AND ".join(where), params


def list_clusters(
    *,
    activity_window_days: int | None = 180,
    make: str | None = None,
    model_year: int | None = None,
    component: str | None = None,
    classification: str | None = None,
    recall: str | None = None,
    filed: str | None = None,
    tx_min: int | None = None,
    search: str | None = None,
    sort: str = "score",
    direction: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total_count) for the dashboard, applying optional filters.

    Always paginated — rendering thousands of HTML rows freezes the browser.
    """
    where_sql, params = _build_filters(
        activity_window_days=activity_window_days,
        make=make,
        model_year=model_year,
        component=component,
        classification=classification,
        recall=recall,
        filed=filed,
        tx_min=tx_min,
        search=search,
    )
    order_by = _build_order_by(sort, direction)

    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM clusters c WHERE {where_sql}", params)
        total = int(cur.fetchone()["n"])

        cur.execute(
            f"""
            SELECT c.id, c.make, c.model, c.model_year, c.component, c.is_multi_year,
                   c.complaint_count, c.injury_count, c.death_count, c.crash_count,
                   c.fire_count, c.velocity_30d, c.score, c.classification,
                   c.first_complaint_date, c.last_complaint_date,
                   c.recall_issued, c.nhtsa_investigation_open,
                   c.class_action_filed, c.class_action_status, c.tx_complaint_count,
                   (c.viability_memo IS NOT NULL) AS has_memo
              FROM clusters c
             WHERE {where_sql}
             ORDER BY {order_by}, c.id
             LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": limit, "offset": offset},
        )
        return list(cur.fetchall()), total


def breakdown_in_view(column: str, limit: int = 8, **filters: Any) -> list[dict[str, Any]]:
    """Top-N `column` values among per-year clusters matching the current
    dashboard filters. Feeds the "in view by component / by make" bar charts.

    Per-year only (model_year IS NOT NULL): the ALL_YEARS aggregates would
    double-count every cluster.
    """
    if column not in ("component", "make"):
        raise ValueError(f"unsupported breakdown column: {column!r}")
    where_sql, params = _build_filters(**filters)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.{column} AS label, COUNT(*) AS n
              FROM clusters c
             WHERE {where_sql} AND c.model_year IS NOT NULL
             GROUP BY c.{column}
             ORDER BY n DESC, c.{column}
             LIMIT %(limit)s
            """,
            {**params, "limit": limit},
        )
        return list(cur.fetchall())


def signal_counts_in_view(**filters: Any) -> dict[str, int]:
    """Manufacturer-knowledge / legal-status signals across the current slice:
    how many per-year clusters carry a recall, an open NHTSA probe, or an AI
    memo. `filed` is counted with the filed-case exclusion lifted, since those
    clusters are hidden from the slice by default and the number feeds the
    "class action" audit link."""
    where_sql, params = _build_filters(**filters)
    filed_where, filed_params = _build_filters(**{**filters, "filed": "1"})
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)                                            AS clusters,
                   COUNT(*) FILTER (WHERE c.recall_issued)              AS recall,
                   COUNT(*) FILTER (WHERE c.nhtsa_investigation_open)   AS probe,
                   COUNT(*) FILTER (WHERE c.viability_memo IS NOT NULL) AS memo
              FROM clusters c
             WHERE {where_sql} AND c.model_year IS NOT NULL
            """,
            params,
        )
        row = dict(cur.fetchone() or {})
        cur.execute(
            f"""
            SELECT COUNT(*) AS filed
              FROM clusters c
             WHERE {filed_where} AND c.model_year IS NOT NULL
            """,
            filed_params,
        )
        row.update(cur.fetchone() or {})
        return {k: int(v or 0) for k, v in row.items()}


def classification_counts(activity_window_days: int | None = 180) -> dict[str, int]:
    """Counts per classification for the stats strip. Excludes clusters with a
    filed class action, mirroring the dashboard filter."""
    where = ["c.classification != 'NOISE'", EXCLUDE_FILED_SQL]
    params: dict[str, Any] = {}
    if activity_window_days is not None:
        where.append("c.last_complaint_date >= %(floor)s")
        params["floor"] = date.today() - timedelta(days=activity_window_days)
    sql = f"""
      SELECT c.classification, COUNT(*) AS n
        FROM clusters c
       WHERE {' AND '.join(where)}
       GROUP BY classification
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return {r["classification"]: int(r["n"]) for r in cur.fetchall()}


def get_cluster(cluster_id: int) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM clusters WHERE id = %s", (cluster_id,))
        return cur.fetchone()


def list_complaints(cluster_id: int, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.odi_number, c.date_complaint_filed, c.state,
                   c.crash, c.fire, c.injuries, c.deaths,
                   c.component, c.description
              FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
             WHERE cc.cluster_id = %s
             ORDER BY c.date_complaint_filed DESC NULLS LAST
             LIMIT %s OFFSET %s
            """,
            (cluster_id, limit, offset),
        )
        return list(cur.fetchall())


def count_complaints(cluster_id: int) -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM cluster_complaints WHERE cluster_id = %s",
            (cluster_id,),
        )
        return int(cur.fetchone()["n"])


def states_for_cluster(cluster_id: int) -> list[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT state FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
             WHERE cc.cluster_id = %s AND state IS NOT NULL
             ORDER BY state
            """,
            (cluster_id,),
        )
        return [r["state"] for r in cur.fetchall() if r["state"]]


def complaints_per_month(cluster_id: int, months: int = 24) -> list[dict[str, Any]]:
    """Bucket complaints by month for the volume chart."""
    floor = date.today().replace(day=1) - timedelta(days=months * 31)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT date_trunc('month', c.date_complaint_filed)::date AS month,
                   COUNT(*) AS n
              FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
             WHERE cc.cluster_id = %s
               AND c.date_complaint_filed >= %s
             GROUP BY 1
             ORDER BY 1
            """,
            (cluster_id, floor),
        )
        return list(cur.fetchall())


def months_axis(months: int) -> list[date]:
    """First-of-month dates covering the last `months` months through today.

    Shared by every monthly bucketed query so sparklines, the volume chart and
    their x-axis labels always agree on the buckets.
    """
    cursor = date.today().replace(day=1)
    axis: list[date] = []
    for _ in range(months):
        axis.append(cursor)
        cursor = (cursor.replace(day=1) - timedelta(days=1)).replace(day=1)
    axis.reverse()
    return axis


def sparklines_for_clusters(
    cluster_ids: list[int], months: int = 12
) -> dict[int, list[int]]:
    """Return {cluster_id: [count, count, ...]} of complaints per month for the
    last `months` months. Used to render row-level sparklines on the dashboard.
    """
    if not cluster_ids:
        return {}
    axis = months_axis(months)
    floor = axis[0]

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT cc.cluster_id,
                   date_trunc('month', c.date_complaint_filed)::date AS month,
                   COUNT(*) AS n
              FROM cluster_complaints cc
              JOIN complaints c ON c.id = cc.complaint_id
             WHERE cc.cluster_id = ANY(%s)
               AND c.date_complaint_filed >= %s
             GROUP BY cc.cluster_id, 2
             ORDER BY cc.cluster_id, 2
            """,
            (cluster_ids, floor),
        )
        rows = cur.fetchall()

    # Build a list of `months` buckets for each cluster, zero-filled.
    out: dict[int, list[int]] = {cid: [0] * len(axis) for cid in cluster_ids}
    index_for_month = {m: i for i, m in enumerate(axis)}
    for r in rows:
        idx = index_for_month.get(r["month"])
        if idx is not None:
            out[r["cluster_id"]][idx] = int(r["n"])
    return out


def classification_sparklines(months: int = 12) -> dict[str, list[int]]:
    """Return {classification: [n_per_month]} of monthly complaint volume in
    clusters currently classified at that level. Only counts per-year clusters
    (excludes the cross-year aggregates) so each complaint is counted once.
    """
    axis = months_axis(months)
    floor = axis[0]
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT cl.classification AS cls,
                   date_trunc('month', c.date_complaint_filed)::date AS month,
                   COUNT(DISTINCT c.id) AS n
              FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
              JOIN clusters cl ON cl.id = cc.cluster_id
             WHERE cl.classification IN ('CRITICAL','HOT','WATCH','MONITOR')
               AND cl.model_year IS NOT NULL
               AND c.date_complaint_filed >= %s
             GROUP BY cl.classification, 2
             ORDER BY cl.classification, 2
            """,
            (floor,),
        )
        rows = cur.fetchall()

    index_for_month = {m: i for i, m in enumerate(axis)}

    out: dict[str, list[int]] = {
        c: [0] * len(axis)
        for c in ("CRITICAL", "HOT", "WATCH", "MONITOR")
    }
    for r in rows:
        idx = index_for_month.get(r["month"])
        if idx is not None and r["cls"] in out:
            out[r["cls"]][idx] = int(r["n"])
    return out


def search_clusters(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Cmd+K palette search across make / model / component."""
    if not q or not q.strip():
        return []
    needle = f"%{q.lower()}%"
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, make, model, model_year, component, classification,
                   complaint_count, score, is_multi_year
              FROM clusters
             WHERE classification != 'NOISE'
               AND (LOWER(make) LIKE %s OR LOWER(model) LIKE %s OR LOWER(component) LIKE %s)
             ORDER BY score DESC, complaint_count DESC
             LIMIT %s
            """,
            (needle, needle, needle, limit),
        )
        return list(cur.fetchall())


def all_makes() -> list[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT make FROM clusters WHERE classification != 'NOISE' ORDER BY make"
        )
        return [r["make"] for r in cur.fetchall()]


def all_components() -> list[str]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT component FROM clusters "
            "WHERE classification != 'NOISE' ORDER BY component"
        )
        return [r["component"] for r in cur.fetchall()]


def all_years() -> list[int]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT model_year FROM clusters "
            "WHERE classification != 'NOISE' AND model_year IS NOT NULL "
            "ORDER BY model_year DESC"
        )
        return [r["model_year"] for r in cur.fetchall()]


def list_memos(
    *, search: str | None = None, limit: int = 25, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Every cluster with a viability memo, newest memo first.

    Shows terminated class actions too (the memo is still history) — the
    template flags them. `memo_complaint_count_at_gen` lets the page say how
    many complaints have arrived since the memo was written.
    """
    where = ["(c.viability_memo IS NOT NULL OR c.research_memo IS NOT NULL)"]
    params: dict[str, Any] = {}
    if search:
        where.append(
            "(LOWER(c.make) LIKE %(q)s OR LOWER(c.model) LIKE %(q)s "
            "OR LOWER(c.component) LIKE %(q)s OR LOWER(c.viability_memo) LIKE %(q)s)"
        )
        params["q"] = f"%{search.lower()}%"
    where_sql = " AND ".join(where)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM clusters c WHERE {where_sql}", params)
        total = int(cur.fetchone()["n"])
        cur.execute(
            f"""
            SELECT c.id, c.make, c.model, c.model_year, c.component, c.classification,
                   c.score, c.complaint_count, c.injury_count, c.death_count,
                   c.recall_issued, c.nhtsa_investigation_open,
                   c.class_action_filed, c.class_action_status,
                   c.viability_memo, c.memo_generated_at, c.memo_complaint_count_at_gen,
                   c.research_memo, c.research_generated_at
              FROM clusters c
             WHERE {where_sql}
             ORDER BY GREATEST(c.memo_generated_at, c.research_generated_at) DESC NULLS LAST,
                      c.score DESC, c.id
             LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": limit, "offset": offset},
        )
        return list(cur.fetchall()), total


def header_stats() -> dict[str, Any]:
    """Headline numbers for the status-strip ticker.

    Cheap aggregates only — no joins, all on indexed columns.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              (SELECT COUNT(*) FROM complaints) AS complaints_scanned,
              (SELECT COUNT(*) FROM clusters c
                WHERE c.classification != 'NOISE' AND {EXCLUDE_FILED_SQL}) AS clusters_tracked,
              (SELECT COUNT(*) FROM clusters WHERE viability_memo IS NOT NULL) AS memos_written,
              (SELECT MAX(run_at) FROM ingestion_log) AS last_refresh
            """
        )
        return cur.fetchone() or {}


def last_ingestion() -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ingestion_log ORDER BY run_at DESC LIMIT 1")
        return cur.fetchone()
