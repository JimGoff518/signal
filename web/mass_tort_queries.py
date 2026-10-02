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
    source_urls, notes, priority_rank, updated_at, created_at,
    cl_filings_delta_7d, last_verified_at
"""

# Whitelist of columns PATCH may touch. invest_score intentionally absent.
PATCHABLE_FIELDS = frozenset({"human_label", "notes", "priority_rank"})

HUMAN_LABELS = frozenset({"WATCH", "INVEST", "CHASE", "PASS", "HOLD"})


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


# Searcher weekly harvest may touch these. human_label / invest_score / priority_rank
# stay Jimmy-only (PATCH). parent_slug / caption / slug are seed-locked.
HARVESTABLE_FIELDS = frozenset({
    "mdl_or_jccp_id",
    "court",
    "pending_count",
    "last_event_at",
    "last_event_type",
    "source_urls",
    "notes",
    "cl_filings_delta_7d",
    "last_verified_at",
})

EVENT_TYPES = frozenset({
    "jpml_motion",
    "transfer_order",
    "tag_along",
    "settlement",
    "bellwether",
    "other",
})


def apply_harvest_write(
    slug: str,
    fields: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write Searcher harvest fields by slug; optionally append one mdl_event.

    Does not write human_label, invest_score, priority_rank, caption, or
    parent_slug. Returns the updated matter row, or None if slug missing.
    Raises ValueError on empty / invalid input.
    """
    if not fields and not event:
        raise ValueError("no harvest fields provided")
    unknown = set(fields) - HARVESTABLE_FIELDS
    if unknown:
        raise ValueError(f"unharvestable fields: {sorted(unknown)}")
    if "last_event_type" in fields and fields["last_event_type"] is not None:
        if fields["last_event_type"] not in EVENT_TYPES:
            raise ValueError(f"invalid last_event_type: {fields['last_event_type']}")
    if event is not None:
        et = event.get("event_type")
        if not et or et not in EVENT_TYPES:
            raise ValueError(f"invalid event_type: {et}")

    with connection() as conn:
        with conn.cursor() as cur:
            if fields:
                sets: list[str] = []
                params: dict[str, Any] = {"slug": slug}
                for key, value in fields.items():
                    sets.append(f"{key} = %({key})s")
                    params[key] = value
                sets.append("updated_at = NOW()")
                cur.execute(
                    f"""
                    UPDATE mass_tort_matters
                       SET {", ".join(sets)}
                     WHERE slug = %(slug)s
                 RETURNING {MATTER_COLUMNS}
                    """,
                    params,
                )
                row = cur.fetchone()
            else:
                cur.execute(
                    f"""
                    SELECT {MATTER_COLUMNS}
                      FROM mass_tort_matters
                     WHERE slug = %(slug)s
                    """,
                    {"slug": slug},
                )
                row = cur.fetchone()
            if row is None:
                return None

            if event is not None:
                # Sync last_event_* from the appended event when caller omitted them.
                sync: dict[str, Any] = {}
                if "last_event_type" not in fields:
                    sync["last_event_type"] = event["event_type"]
                if "last_event_at" not in fields and event.get("event_date") is not None:
                    sync["last_event_at"] = event["event_date"]
                cur.execute(
                    """
                    INSERT INTO mdl_events (
                        matter_id, event_type, event_date, cite, source_url, summary
                    ) VALUES (
                        %(matter_id)s, %(event_type)s, %(event_date)s,
                        %(cite)s, %(source_url)s, %(summary)s
                    )
                    RETURNING id
                    """,
                    {
                        "matter_id": row["id"],
                        "event_type": event["event_type"],
                        "event_date": event.get("event_date"),
                        "cite": event.get("cite"),
                        "source_url": event.get("source_url"),
                        "summary": event.get("summary"),
                    },
                )
                cur.fetchone()
                if sync:
                    sync_sets = [f"{k} = %({k})s" for k in sync]
                    sync_sets.append("updated_at = NOW()")
                    sync["slug"] = slug
                    cur.execute(
                        f"""
                        UPDATE mass_tort_matters
                           SET {", ".join(sync_sets)}
                         WHERE slug = %(slug)s
                     RETURNING {MATTER_COLUMNS}
                        """,
                        sync,
                    )
                    row = cur.fetchone() or row
            return row


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


def decision_label(human_label: str | None) -> str:
    """Jimmy decision language: PASS displays as HOLD; prefer HOLD for new patches."""
    if human_label == "PASS":
        return "HOLD"
    return human_label or "—"


def preferred_source_url(urls: list | None) -> str | None:
    """First JPML or CourtListener URL, else first source_url, else None."""
    if not urls:
        return None
    items = [str(u) for u in urls if u]
    for u in items:
        low = u.lower()
        if "jpml.uscourts.gov" in low or "courtlistener.com" in low:
            return u
    return items[0] if items else None


def stage_strip_label(last_event_type: str | None) -> str:
    """Map last_event_type → filings / MDL / bellwether / settlement strip."""
    if not last_event_type:
        return "—"
    return {
        "jpml_motion": "Filings",
        "transfer_order": "MDL",
        "tag_along": "MDL",
        "bellwether": "Bellwether",
        "settlement": "Settlement",
        "other": "Other",
    }.get(last_event_type, last_event_type)

