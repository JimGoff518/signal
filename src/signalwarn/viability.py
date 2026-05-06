"""Claude viability memo generation.

For every cluster scoring >= 50 (WATCH+), generate a brief legal viability memo
and store it on the cluster row. See spec §8.
"""
from __future__ import annotations

import logging

from anthropic import Anthropic

from signalwarn.config import settings
from signalwarn.db import connection


def _anthropic_client() -> Anthropic:
    """Build an Anthropic client, wrapped by LangSmith if tracing is configured."""
    client = Anthropic(api_key=settings.anthropic_api_key)
    if settings.langsmith_tracing and settings.langsmith_api_key:
        from langsmith.wrappers import wrap_anthropic

        return wrap_anthropic(client)
    return client

log = logging.getLogger(__name__)

WATCH_THRESHOLD = 50


def _build_prompt(cluster: dict, sample_descriptions: list[str], states: list[str]) -> str:
    samples = "\n\n---\n\n".join(sample_descriptions[:5]) or "(no narratives on file)"
    return f"""You are a Texas personal injury attorney evaluating a potential
class action or mass tort case opportunity. Analyze the following complaint
cluster and provide a brief legal viability assessment.

COMPLAINT CLUSTER DATA:
- Vehicle: {cluster['model_year'] or 'multi-year'} {cluster['make']} {cluster['model']}
- Component: {cluster['component']}
- Total Complaints: {cluster['complaint_count']}
- Injuries Reported: {cluster['injury_count']}
- Deaths Reported: {cluster['death_count']}
- Crashes Reported: {cluster['crash_count']}
- Complaints in Last 30 Days: {cluster['velocity_30d']}
- States Represented: {', '.join(states) or 'unknown'}
- Date Range: {cluster['first_complaint_date']} to {cluster['last_complaint_date']}

SAMPLE COMPLAINT DESCRIPTIONS:
{samples}

Provide a viability assessment in this exact format:

NUMEROSITY: [1-2 sentences — is there a sufficient number of potential plaintiffs?]

COMMONALITY: [1-2 sentences — is the defect consistent across complaints?]

ECONOMIC DAMAGE: [1-2 sentences — is there measurable economic loss even without physical injury?]

MANUFACTURER KNOWLEDGE: [1-2 sentences — what does the complaint pattern suggest about when the manufacturer knew?]

INJURY/DEATH SEVERITY: [1-2 sentences — assessment of physical harm reported]

OVERALL ASSESSMENT: [2-3 sentences — is this worth investigating further? What is the most likely legal theory?]

RECOMMENDED ACTION: [One of: INVESTIGATE NOW / MONITOR CLOSELY / LOW PRIORITY]

Keep the entire response under 400 words. Be direct. Do not use disclaimers.
Texas law applies."""


def _generate_memo(cluster: dict, sample_descriptions: list[str], states: list[str]) -> str:
    client = _anthropic_client()
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1000,
        messages=[{"role": "user", "content": _build_prompt(cluster, sample_descriptions, states)}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


def regenerate_memo_if_needed(cluster_id: int, force: bool = False) -> bool:
    """Generate a viability memo if the cluster crossed WATCH or doubled since last memo.

    Returns True if a new memo was written.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM clusters WHERE id = %s", (cluster_id,))
        cluster = cur.fetchone()
        if cluster is None:
            return False
        if cluster["score"] < WATCH_THRESHOLD:
            return False

        prior = cluster.get("memo_complaint_count_at_gen")
        already_written = cluster.get("viability_memo") is not None
        doubled = prior and cluster["complaint_count"] >= prior * 2
        if already_written and not doubled and not force:
            return False

        cur.execute(
            """
            SELECT description, state FROM complaints c
              JOIN cluster_complaints cc ON cc.complaint_id = c.id
             WHERE cc.cluster_id = %s
             ORDER BY c.date_complaint_filed DESC NULLS LAST
             LIMIT 5
            """,
            (cluster_id,),
        )
        sample_rows = cur.fetchall()
        descriptions = [r["description"] for r in sample_rows if r["description"]]

        cur.execute(
            "SELECT DISTINCT state FROM complaints c "
            "JOIN cluster_complaints cc ON cc.complaint_id = c.id "
            "WHERE cc.cluster_id = %s AND state IS NOT NULL",
            (cluster_id,),
        )
        states = sorted({r["state"] for r in cur.fetchall() if r["state"]})

        memo = _generate_memo(cluster, descriptions, states)

        cur.execute(
            """
            UPDATE clusters
               SET viability_memo = %s,
                   memo_generated_at = NOW(),
                   memo_complaint_count_at_gen = %s
             WHERE id = %s
            """,
            (memo, cluster["complaint_count"], cluster_id),
        )

    log.info("Wrote viability memo for cluster %s", cluster_id)
    return True
