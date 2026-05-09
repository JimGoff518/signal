"""Read queries used by the FastAPI dashboard.

Pure SQL via the shared psycopg connection helper. Returns plain dicts
(thanks to dict_row factory) — no ORM, no pandas.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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


def list_clusters(
    *,
    activity_window_days: int | None = 180,
    make: str | None = None,
    model_year: int | None = None,
    classification: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total_count) for the dashboard, applying optional filters.

    Always paginated — rendering thousands of HTML rows freezes the browser.
    """
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

    if classification and classification != "ALL":
        where.append("c.classification = %(classification)s")
        params["classification"] = classification.upper()

    if search:
        where.append(
            "(LOWER(c.make) LIKE %(q)s "
            "OR LOWER(c.model) LIKE %(q)s "
            "OR LOWER(c.component) LIKE %(q)s)"
        )
        params["q"] = f"%{search.lower()}%"

    where_sql = " AND ".join(where)

    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM clusters c WHERE {where_sql}", params)
        total = int(cur.fetchone()["n"])

        cur.execute(
            f"""
            SELECT c.id, c.make, c.model, c.model_year, c.component, c.is_multi_year,
                   c.complaint_count, c.injury_count, c.death_count, c.crash_count,
                   c.fire_count, c.velocity_30d, c.score, c.classification,
                   c.first_complaint_date, c.last_complaint_date,
                   c.recall_issued, c.nhtsa_investigation_open
              FROM clusters c
             WHERE {where_sql}
             ORDER BY c.score DESC, c.complaint_count DESC
             LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": limit, "offset": offset},
        )
        return list(cur.fetchall()), total


def classification_counts(activity_window_days: int | None = 180) -> dict[str, int]:
    """Counts per classification for the stats strip."""
    where = ["classification != 'NOISE'"]
    params: dict[str, Any] = {}
    if activity_window_days is not None:
        where.append("last_complaint_date >= %(floor)s")
        params["floor"] = date.today() - timedelta(days=activity_window_days)
    sql = f"""
      SELECT classification, COUNT(*) AS n
        FROM clusters
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


def sparklines_for_clusters(
    cluster_ids: list[int], months: int = 12
) -> dict[int, list[int]]:
    """Return {cluster_id: [count, count, ...]} of complaints per month for the
    last `months` months. Used to render row-level sparklines on the dashboard.
    """
    if not cluster_ids:
        return {}
    floor = date.today().replace(day=1) - timedelta(days=months * 31)

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
    months_axis: list[date] = []
    cursor = floor.replace(day=1)
    today_first = date.today().replace(day=1)
    while cursor <= today_first:
        months_axis.append(cursor)
        # advance to next month
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)

    out: dict[int, list[int]] = {cid: [0] * len(months_axis) for cid in cluster_ids}
    index_for_month = {m: i for i, m in enumerate(months_axis)}
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
    floor = date.today().replace(day=1) - timedelta(days=months * 31)
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

    months_axis: list[date] = []
    cursor = floor.replace(day=1)
    today_first = date.today().replace(day=1)
    while cursor <= today_first:
        months_axis.append(cursor)
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    index_for_month = {m: i for i, m in enumerate(months_axis)}

    out: dict[str, list[int]] = {
        c: [0] * len(months_axis)
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


def all_years() -> list[int]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT model_year FROM clusters "
            "WHERE classification != 'NOISE' AND model_year IS NOT NULL "
            "ORDER BY model_year DESC"
        )
        return [r["model_year"] for r in cur.fetchall()]


def header_stats() -> dict[str, Any]:
    """Headline numbers for the status-strip ticker.

    Cheap aggregates only — no joins, all on indexed columns.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM complaints)                                AS complaints_scanned,
              (SELECT COUNT(*) FROM clusters WHERE classification != 'NOISE') AS clusters_tracked,
              (SELECT COUNT(*) FROM clusters WHERE viability_memo IS NOT NULL) AS memos_written,
              (SELECT MAX(run_at) FROM ingestion_log)                          AS last_refresh
            """
        )
        return cur.fetchone() or {}


def last_ingestion() -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM ingestion_log ORDER BY run_at DESC LIMIT 1")
        return cur.fetchone()
