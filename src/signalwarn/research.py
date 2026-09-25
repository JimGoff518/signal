"""Helpers behind `scripts/research.py` and the `/investigate` skill.

The skill runs in a Claude Code session (Descrybe only authenticates
interactively, so the cron pipeline can't do this research itself). These
helpers pull a cluster out of the DB in a form the skill can read, and write
the finished research addendum back.
Design: docs/plans/2026-09-18-investigate-skill-design.md
"""
from __future__ import annotations

import re
from typing import Any

from signalwarn.db import connection

RESEARCH_CLASSIFICATIONS = ("CRITICAL", "HOT")

# The value is a run of capital letters and spaces ("INVESTIGATE NOW"); it
# ends at the first character that isn't one, so brackets, dashes, periods
# and line breaks all terminate it without being listed here.
_ACTION_RE = re.compile(r"RECOMMENDED ACTION:\s*\[?\s*([A-Z][A-Z ]*[A-Z])(?![A-Za-z])")


def recommended_action(memo: str | None) -> str | None:
    """Pull the RECOMMENDED ACTION value out of a viability memo, if present."""
    if not memo:
        return None
    m = _ACTION_RE.search(memo)
    return m.group(1).strip() if m else None


def candidates_query(limit: int = 15) -> tuple[str, dict[str, Any]]:
    """SQL for clusters worth researching: CRITICAL/HOT, no addendum yet,
    class action not already resolved. Highest score first."""
    classes = ", ".join(f"'{c}'" for c in RESEARCH_CLASSIFICATIONS)
    sql = f"""
        SELECT c.id, c.make, c.model, c.model_year, c.is_multi_year, c.component,
               c.classification, c.score, c.complaint_count, c.injury_count,
               c.death_count, c.velocity_30d, c.recall_issued,
               c.nhtsa_investigation_open, c.class_action_filed,
               c.viability_memo
          FROM clusters c
         WHERE c.research_memo IS NULL
           AND c.classification IN ({classes})
           AND (c.class_action_status IS NULL OR c.class_action_status NOT IN ('terminated', 'cert_denied'))
         ORDER BY c.score DESC, c.complaint_count DESC, c.id
         LIMIT %(limit)s
    """
    return sql, {"limit": limit}


def list_candidates(limit: int = 15) -> list[dict[str, Any]]:
    sql, params = candidates_query(limit)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    for r in rows:
        r["recommended_action"] = recommended_action(r.get("viability_memo"))
    return rows


def load_cluster(
    cluster_id: int, narratives: int = 8
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]] | None:
    """Cluster row + distinct states + most recent complaint narratives."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM clusters WHERE id = %s", (cluster_id,))
        cluster = cur.fetchone()
        if cluster is None:
            return None
        cur.execute(
            "SELECT DISTINCT state FROM complaints c "
            "JOIN cluster_complaints cc ON cc.complaint_id = c.id "
            "WHERE cc.cluster_id = %s AND state IS NOT NULL ORDER BY state",
            (cluster_id,),
        )
        states = [r["state"] for r in cur.fetchall() if r["state"]]
        cur.execute(
            """
            SELECT c.date_complaint_filed, c.state, c.description
              FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
             WHERE cc.cluster_id = %s AND c.description IS NOT NULL
             ORDER BY c.date_complaint_filed DESC NULLS LAST
             LIMIT %s
            """,
            (cluster_id, narratives),
        )
        rows = list(cur.fetchall())
    return cluster, states, rows


def format_show(
    cluster: dict[str, Any], states: list[str], narratives: list[dict[str, Any]]
) -> str:
    """Plain-text dossier the /investigate skill reads before researching."""
    c = cluster
    if c.get("is_multi_year") or not c.get("model_year"):
        year = "multi-year (ALL_YEARS)"
    else:
        year = str(c["model_year"])
    flags = []
    if c.get("recall_issued"):
        flags.append("recall issued")
    if c.get("nhtsa_investigation_open"):
        flags.append("NHTSA investigation open")
    if c.get("class_action_filed"):
        flags.append("class action filed")
    lines = [
        f"Cluster {c['id']} — {c['make']} {c['model']} · {year} · {c['component']}",
        f"Classification: {c['classification']} (score {c['score']})",
        (
            f"Complaints: {c['complaint_count']} · injuries {c['injury_count']}"
            f" · deaths {c['death_count']} · crashes {c['crash_count']}"
            f" · fires {c['fire_count']} · last 30 days {c['velocity_30d']}"
        ),
        f"Date range: {c.get('first_complaint_date') or '?'}"
        f" to {c.get('last_complaint_date') or '?'}",
        f"Flags: {', '.join(flags) or 'none'}",
        f"States: {', '.join(states) or 'unknown'}",
    ]
    if c.get("class_action_filed"):
        lines.append(
            f"Class action: {c.get('class_action_case_name') or '?'}"
            f" ({c.get('class_action_court') or '?'}),"
            f" status {c.get('class_action_status') or '?'} — {c.get('class_action_url') or ''}"
        )
    if c.get("research_memo"):
        lines.append(
            "Existing research addendum: yes"
            f" (generated {c.get('research_generated_at')}) — saving again overwrites it"
        )

    lines += ["", "== VIABILITY MEMO ==", c.get("viability_memo") or "(no viability memo)"]
    lines += ["", "== RECENT COMPLAINT NARRATIVES =="]
    if narratives:
        for n in narratives:
            lines.append(
                f"[{n.get('date_complaint_filed') or '?'} | {n.get('state') or '??'}]"
                f" {n['description']}"
            )
            lines.append("")
    else:
        lines.append("(no narratives on file)")
    return "\n".join(lines)


def save_research(cluster_id: int, text: str) -> None:
    """Store the research addendum on the cluster row. Empty text is refused."""
    if not text or not text.strip():
        raise ValueError("research addendum is empty; nothing saved")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE clusters SET research_memo = %s, research_generated_at = NOW() WHERE id = %s",
            (text.strip(), cluster_id),
        )
        if cur.rowcount == 0:
            raise LookupError(f"no cluster with id {cluster_id}")
