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

from signalwarn.scoring import ClusterFacts, classify, compute_score


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

    Returns the updated cluster row as a dict.
    """
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*)                                    AS complaint_count,
              SUM(CASE WHEN c.injuries > 0 THEN 1 ELSE 0 END) AS injury_count,
              SUM(CASE WHEN c.deaths   > 0 THEN 1 ELSE 0 END) AS death_count,
              SUM(CASE WHEN c.crash         THEN 1 ELSE 0 END) AS crash_count,
              SUM(CASE WHEN c.fire          THEN 1 ELSE 0 END) AS fire_count,
              SUM(CASE WHEN c.date_complaint_filed >= %s THEN 1 ELSE 0 END) AS velocity_7d,
              SUM(CASE WHEN c.date_complaint_filed >= %s THEN 1 ELSE 0 END) AS velocity_30d,
              MIN(c.date_complaint_filed) AS first_complaint_date,
              MAX(c.date_complaint_filed) AS last_complaint_date,
              COUNT(DISTINCT c.model_year) AS distinct_years
            FROM cluster_complaints cc
            JOIN complaints c ON c.id = cc.complaint_id
            WHERE cc.cluster_id = %s
            """,
            (week_ago, month_ago, cluster_id),
        )
        agg = cur.fetchone()
        if agg is None or (agg["complaint_count"] or 0) == 0:
            return {}

        cur.execute(
            "SELECT model_year, nhtsa_investigation_open, recall_issued, class_action_filed "
            "FROM clusters WHERE id = %s",
            (cluster_id,),
        )
        meta = cur.fetchone() or {}

        is_multi_year = (meta.get("model_year") is None) and (agg["distinct_years"] or 0) > 1

        facts = ClusterFacts(
            complaint_count=int(agg["complaint_count"] or 0),
            velocity_30d=int(agg["velocity_30d"] or 0),
            injury_count=int(agg["injury_count"] or 0),
            death_count=int(agg["death_count"] or 0),
            crash_count=int(agg["crash_count"] or 0),
            fire_count=int(agg["fire_count"] or 0),
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
              complaint_count = %s,
              injury_count    = %s,
              death_count     = %s,
              crash_count     = %s,
              fire_count      = %s,
              velocity_7d     = %s,
              velocity_30d    = %s,
              first_complaint_date = %s,
              last_complaint_date  = %s,
              is_multi_year   = %s,
              score           = %s,
              classification  = %s,
              updated_at      = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                facts.complaint_count,
                facts.injury_count,
                facts.death_count,
                facts.crash_count,
                facts.fire_count,
                int(agg["velocity_7d"] or 0),
                facts.velocity_30d,
                agg["first_complaint_date"],
                agg["last_complaint_date"],
                is_multi_year,
                score,
                label,
                cluster_id,
            ),
        )
        return cur.fetchone() or {}
