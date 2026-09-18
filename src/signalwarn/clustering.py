"""Cluster builder.

Each complaint slots into exactly one per-year cluster, identified by:
    {MAKE}::{MODEL}::{MODEL_YEAR}::{COMPONENT_NORMALIZED}

Every per-year cluster also rolls up into a cross-year aggregate:
    {MAKE}::{MODEL}::ALL_YEARS::{COMPONENT_NORMALIZED}

The aggregate cluster has model_year = NULL and is_multi_year = TRUE; it
gets the +10 multi-year scoring bonus when complaints span >1 model year.
"""
from __future__ import annotations

from datetime import date, timedelta

from psycopg import Connection

from signalwarn.config import settings
from signalwarn.scoring import ClusterFacts, classify, compute_score

# Statute-of-limitations predicate for a complaint aliased `c`. A complaint is
# a live claim when its accrual date (incident date, else NHTSA filing date) is
# on or after the SOL floor. Undated complaints are kept: we can't prove they
# are barred. Bind %(sol_floor)s from sol_floor().
LIVE_COMPLAINT_SQL = (
    "(COALESCE(c.date_of_incident, c.date_complaint_filed) >= %(sol_floor)s "
    "OR (c.date_of_incident IS NULL AND c.date_complaint_filed IS NULL))"
)

# Filed-case exclusion (2026-09-18) for a cluster aliased `c`. Every surface
# that should agree with the dashboard (tier counts, header stats, memo
# generation, digest, death alerts) uses this predicate. Pending or terminated
# makes no difference: once a class action is on file the opportunity is gone.
EXCLUDE_FILED_SQL = "c.class_action_filed = FALSE"


def sol_floor(today: date, years: int) -> date:
    """Earliest accrual date that is still inside the limitations window."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29 in a non-leap target year
        return today.replace(year=today.year - years, day=28)


def make_cluster_key(make: str, model: str, model_year: int | None, component: str) -> str:
    year = "ALL_YEARS" if model_year is None else str(model_year)
    return f"{make.upper()}::{model.upper()}::{year}::{component.upper()}"


def upsert_clusters_for_complaint(
    conn: Connection, complaint_id: int, make: str, model: str, model_year: int, component: str
) -> list[int]:
    """Attach a complaint to its per-year cluster and the cross-year aggregate.

    Returns the list of cluster ids the complaint was attached to.
    """
    cluster_ids: list[int] = []
    for year_value in (model_year, None):  # per-year, then aggregate
        key = make_cluster_key(make, model, year_value, component)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clusters (cluster_key, make, model, model_year, component)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (cluster_key) DO UPDATE
                  SET updated_at = NOW()
                RETURNING id
                """,
                (key, make.upper(), model.upper(), year_value, component.upper()),
            )
            row = cur.fetchone()
            cluster_id = row["id"]  # type: ignore[index]
            cluster_ids.append(cluster_id)

            cur.execute(
                """
                INSERT INTO cluster_complaints (cluster_id, complaint_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (cluster_id, complaint_id),
            )
    return cluster_ids


def recalculate_cluster(conn: Connection, cluster_id: int) -> dict:
    """Recompute a cluster's aggregates, score, and classification.

    Only *live* complaints (inside the statute-of-limitations window, see
    LIVE_COMPLAINT_SQL) feed the aggregates. Time-barred complaints stay
    attached to the cluster for the record and are counted separately in
    `time_barred_count`. A cluster whose every complaint has aged out is
    written as count 0 / score 0 / NOISE so it drops off the dashboard.

    Returns the updated cluster row as a dict.
    """
    today = date.today()
    params = {
        "cluster_id": cluster_id,
        "week_ago": today - timedelta(days=7),
        "month_ago": today - timedelta(days=30),
        "sol_floor": sol_floor(today, settings.sol_years),
    }

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE live)                    AS complaint_count,
              COUNT(*) FILTER (WHERE live AND c.injuries > 0) AS injury_count,
              COUNT(*) FILTER (WHERE live AND c.deaths > 0)   AS death_count,
              COUNT(*) FILTER (WHERE live AND c.crash)        AS crash_count,
              COUNT(*) FILTER (WHERE live AND c.fire)         AS fire_count,
              COUNT(*) FILTER (WHERE live AND c.date_complaint_filed >= %(week_ago)s)
                                                              AS velocity_7d,
              COUNT(*) FILTER (WHERE live AND c.date_complaint_filed >= %(month_ago)s)
                                                              AS velocity_30d,
              MIN(c.date_complaint_filed) FILTER (WHERE live) AS first_complaint_date,
              MAX(c.date_complaint_filed) FILTER (WHERE live) AS last_complaint_date,
              COUNT(DISTINCT c.model_year) FILTER (WHERE live) AS distinct_years,
              COUNT(*) FILTER (WHERE NOT live)                AS time_barred_count
            FROM cluster_complaints cc
            JOIN complaints c ON c.id = cc.complaint_id
            CROSS JOIN LATERAL (SELECT {LIVE_COMPLAINT_SQL} AS live) sol
            WHERE cc.cluster_id = %(cluster_id)s
            """,
            params,
        )
        agg = cur.fetchone() or {}

        cur.execute(
            "SELECT model_year, nhtsa_investigation_open, recall_issued, class_action_filed "
            "FROM clusters WHERE id = %(cluster_id)s",
            params,
        )
        meta = cur.fetchone() or {}

        is_multi_year = (meta.get("model_year") is None) and (agg.get("distinct_years") or 0) > 1

        facts = ClusterFacts(
            complaint_count=int(agg.get("complaint_count") or 0),
            velocity_30d=int(agg.get("velocity_30d") or 0),
            injury_count=int(agg.get("injury_count") or 0),
            death_count=int(agg.get("death_count") or 0),
            crash_count=int(agg.get("crash_count") or 0),
            fire_count=int(agg.get("fire_count") or 0),
            is_multi_year=is_multi_year,
            nhtsa_investigation_open=bool(meta.get("nhtsa_investigation_open")),
            recall_issued=bool(meta.get("recall_issued")),
            class_action_filed=bool(meta.get("class_action_filed")),
        )
        score = compute_score(facts)
        label = classify(score)

        cur.execute(
            """
            UPDATE clusters SET
              complaint_count = %(complaint_count)s,
              injury_count    = %(injury_count)s,
              death_count     = %(death_count)s,
              crash_count     = %(crash_count)s,
              fire_count      = %(fire_count)s,
              velocity_7d     = %(velocity_7d)s,
              velocity_30d    = %(velocity_30d)s,
              first_complaint_date = %(first_complaint_date)s,
              last_complaint_date  = %(last_complaint_date)s,
              is_multi_year   = %(is_multi_year)s,
              time_barred_count = %(time_barred_count)s,
              score           = %(score)s,
              classification  = %(classification)s,
              updated_at      = NOW()
            WHERE id = %(cluster_id)s
            RETURNING *
            """,
            {
                "complaint_count": facts.complaint_count,
                "injury_count": facts.injury_count,
                "death_count": facts.death_count,
                "crash_count": facts.crash_count,
                "fire_count": facts.fire_count,
                "velocity_7d": int(agg.get("velocity_7d") or 0),
                "velocity_30d": facts.velocity_30d,
                "first_complaint_date": agg.get("first_complaint_date"),
                "last_complaint_date": agg.get("last_complaint_date"),
                "is_multi_year": is_multi_year,
                "time_barred_count": int(agg.get("time_barred_count") or 0),
                "score": score,
                "classification": label,
                "cluster_id": cluster_id,
            },
        )
        return cur.fetchone() or {}
