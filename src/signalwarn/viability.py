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
    return f"""You are a senior Texas plaintiff's attorney at Goff Law PLLC with 
20 years of experience in class actions, mass torts, and product liability. 
You are evaluating a potential case opportunity from NHTSA complaint data.

Your job is to reason like a trial lawyer, not a paralegal. Think about 
causation, manufacturer knowledge timelines, certification hurdles, damages 
models, and which Texas causes of action fit the facts. Be specific and direct.

COMPLAINT CLUSTER DATA:
- Vehicle: {cluster['model_year'] or 'multi-year'} {cluster['make']} {cluster['model']}
- Component: {cluster['component']}
- Total Complaints: {cluster['complaint_count']}
- Multi-year defect: {cluster.get('is_multi_year', False)}
- NHTSA investigation open: {cluster.get('nhtsa_investigation_open', False)}
- Recall already issued: {cluster.get('recall_issued', False)}
- Injuries Reported: {cluster['injury_count']}
- Deaths Reported: {cluster['death_count']}
- Crashes Reported: {cluster['crash_count']}
- Complaints in Last 30 Days: {cluster['velocity_30d']}
- States Represented: {', '.join(states) or 'unknown'}
- Date Range: {cluster['first_complaint_date']} to {cluster['last_complaint_date']}

SAMPLE COMPLAINT DESCRIPTIONS:
{samples}

Provide your analysis in this exact format:

CASE TYPE: [One of: CLASS ACTION / MASS TORT / MDL / INDIVIDUAL CASES / HYBRID]
Explain in 1-2 sentences why this routes to that vehicle rather than another.

CONFIDENCE SCORE: [1-10]
1-3 = low priority, 4-6 = monitor, 7-8 = investigate, 9-10 = move now.
Explain the score in one sentence.

NUMEROSITY (Rule 23(a)(1)): 
Is the class so numerous that joinder is impracticable? How many potential 
class members exist nationally and in Texas specifically?

COMMONALITY & PREDOMINANCE (Rule 23(a)(2) + (b)(3)): 
Is the defect uniform enough that one common question generates a common answer? 
Do common issues predominate over individual ones like causation and damages?

MANUFACTURER KNOWLEDGE TIMELINE:
Based on complaint volume, dates, and patterns — when did the manufacturer 
likely first know about this defect? What does that timeline suggest about 
concealment, failure to warn, or scienter? This is critical for punitive damages.

ECONOMIC DAMAGES MODEL:
What is the measurable uniform economic loss per class member? 
(Warranty denial, diminished value, repair costs, buyback refusal.)
Estimate a per-plaintiff damages range if possible.

TEXAS CAUSES OF ACTION:
List the specific Texas legal theories that fit these facts:
- Texas DTPA (Deceptive Trade Practices Act) — applicable?
- Breach of implied warranty of merchantability
- Design defect (risk-utility test)
- Manufacturing defect
- Failure to warn
- Fraud / fraudulent concealment
For each applicable theory, one sentence on why it fits.

INJURY SEVERITY ASSESSMENT:
If deaths or serious injuries are present, does this route to mass tort / MDL 
rather than class? Would *Amchem* predominance be defeated by individual 
injury issues?

RED FLAGS & RISKS:
What are the 2-3 biggest obstacles to certification or recovery? 
Be honest — what could defeat this case?

RECOMMENDED NEXT STEPS:
List 3 specific actions in priority order:
1. [Most urgent action]
2. [Second action]  
3. [Third action]

RECOMMENDED ACTION: [INVESTIGATE NOW / MONITOR CLOSELY / LOW PRIORITY]

Keep the entire response under 700 words. Be direct. No disclaimers. 
Texas law applies. Think like a trial lawyer, write like one."""


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
