"""Lane B mass-tort read/write queries.

Isolated from Lane A dashboard queries — never join digests, ads flags,
or NHTSA clusters. Labels are the source of truth; invest_score is
read-only here (no auto writes).
"""
from __future__ import annotations

from typing import Any

from signalwarn.db import connection

# INVEST stack first, then Jimmy priority_rank (nulls last), then caption.
LIST_ORDER_SQL = (
    "CASE WHEN human_label = 'INVEST' THEN 0 ELSE 1 END ASC, "
    "priority_rank ASC NULLS LAST, "
    "caption ASC"
)

MATTER_COLUMNS = """
    id, slug, caption, parent_slug, human_label, invest_score,
    mdl_or_jccp_id, court, pending_count, last_event_at, last_event_type,
    source_urls, notes, priority_rank, updated_at, created_at
"""

# Whitelist of columns PATCH may touch. invest_score intentionally absent.
PATCHABLE_FIELDS = frozenset({"human_label", "notes", "priority_rank"})

HUMAN_LABELS = frozenset({"WATCH", "INVEST", "CHASE", "PASS"})


def list_matters(*, human_label: str | None = None) -> list[dict[str, Any]]:
    """List matters. Optional exact human_label filter."""
    where = ""
    params: dict[str, Any] = {}
    if human_label:
        if human_label not in HUMAN_LABELS:
            raise ValueError(f"invalid human_label: {human_label}")
        where = "WHERE human_label = %(human_label)s"
        params["human_label"] = human_label
    sql = f"""
        SELECT {MATTER_COLUMNS}
          FROM mass_tort_matters
          {where}
         ORDER BY {LIST_ORDER_SQL}
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def get_matter_by_slug(slug: str) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {MATTER_COLUMNS}
                  FROM mass_tort_matters
                 WHERE slug = %(slug)s
                """,
                {"slug": slug},
            )
            return cur.fetchone()


def list_events_for_matter(
    matter_id: Any,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent mdl_events for a matter, newest first."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, matter_id, event_type, event_date, cite,
                       source_url, summary, created_at
                  FROM mdl_events
                 WHERE matter_id = %(matter_id)s
                 ORDER BY event_date DESC NULLS LAST, created_at DESC
                 LIMIT %(limit)s
                """,
                {"matter_id": matter_id, "limit": limit},
            )
            return list(cur.fetchall())


def patch_matter(slug: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Apply human label / notes / priority_rank updates. Touches updated_at.

    `fields` must only contain PATCHABLE_FIELDS keys. Returns the updated
    row, or None if the slug is missing. Raises ValueError on empty /
    invalid input. Does not write invest_score.
    """
    if not fields:
        raise ValueError("no patch fields provided")
    unknown = set(fields) - PATCHABLE_FIELDS
    if unknown:
        raise ValueError(f"unpatchable fields: {sorted(unknown)}")
    if "human_label" in fields and fields["human_label"] not in HUMAN_LABELS:
        raise ValueError(f"invalid human_label: {fields['human_label']}")

    sets: list[str] = []
    params: dict[str, Any] = {"slug": slug}
    for key, value in fields.items():
        sets.append(f"{key} = %({key})s")
        params[key] = value
    sets.append("updated_at = NOW()")

    sql = f"""
        UPDATE mass_tort_matters
           SET {", ".join(sets)}
         WHERE slug = %(slug)s
     RETURNING {MATTER_COLUMNS}
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def nest_matters_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display nesting only: children follow parent with nest_depth=1.

    Does not merge scores or rewrite human_label / invest_score. Children whose
    parent is absent from `rows` stay at depth 0 (orphan after a label filter).
    """
    by_slug = {r["slug"]: r for r in rows}
    children: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        parent = r.get("parent_slug")
        if parent and parent in by_slug:
            children.setdefault(parent, []).append(r)
    nested_child_slugs = {c["slug"] for cs in children.values() for c in cs}
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["slug"] in nested_child_slugs:
            continue
        item = dict(r)
        item["nest_depth"] = 0
        out.append(item)
        for c in children.get(r["slug"], []):
            child = dict(c)
            child["nest_depth"] = 1
            out.append(child)
    return out
