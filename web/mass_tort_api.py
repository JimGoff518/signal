"""Lane B mass-tort JSON API under /api/mass-tort/.

List, detail + events, human-label PATCH, Searcher harvest write.
No Filevine. No Jev on score/labels. Alerts are a later slice.
Never joins Lane A digests or ads flags.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from web import mass_tort_queries as mtq

router = APIRouter(prefix="/api/mass-tort", tags=["mass-tort"])


class HumanLabel(str, Enum):
    WATCH = "WATCH"
    INVEST = "INVEST"
    CHASE = "CHASE"
    PASS = "PASS"  # back-compat; UI displays as HOLD
    HOLD = "HOLD"


class MatterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    caption: str
    parent_slug: str | None = None
    human_label: HumanLabel
    invest_score: int | None = None  # read-only; never written by this API
    mdl_or_jccp_id: str | None = None
    court: str | None = None
    pending_count: int | None = None
    last_event_at: datetime | None = None
    last_event_type: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    notes: str | None = None
    priority_rank: int | None = None
    updated_at: datetime
    created_at: datetime
    cl_filings_delta_7d: int | None = None
    last_verified_at: datetime | None = None


class MdlEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    matter_id: UUID
    event_type: str
    event_date: date | None = None
    cite: str | None = None
    source_url: str | None = None
    summary: str | None = None
    created_at: datetime


class MatterDetailOut(MatterOut):
    events: list[MdlEventOut] = Field(default_factory=list)


class MatterPatch(BaseModel):
    """Human label updates only. invest_score is not accepted."""

    human_label: HumanLabel | None = None
    notes: str | None = None
    priority_rank: int | None = None


def require_api_auth(request: Request) -> str:
    """Same session login as the dashboard; 401 for API clients (not 303)."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def _matter_out(row: dict[str, Any]) -> MatterOut:
    urls = row.get("source_urls") or []
    if not isinstance(urls, list):
        urls = list(urls)
    return MatterOut(
        id=row["id"],
        slug=row["slug"],
        caption=row["caption"],
        parent_slug=row.get("parent_slug"),
        human_label=row["human_label"],
        invest_score=row.get("invest_score"),
        mdl_or_jccp_id=row.get("mdl_or_jccp_id"),
        court=row.get("court"),
        pending_count=row.get("pending_count"),
        last_event_at=row.get("last_event_at"),
        last_event_type=row.get("last_event_type"),
        source_urls=[str(u) for u in urls],
        notes=row.get("notes"),
        priority_rank=row.get("priority_rank"),
        updated_at=row["updated_at"],
        created_at=row["created_at"],
        cl_filings_delta_7d=row.get("cl_filings_delta_7d"),
        last_verified_at=row.get("last_verified_at"),
    )


@router.get("/matters", response_model=list[MatterOut])
def list_matters(
    human_label: HumanLabel | None = Query(None),
    _user: str = Depends(require_api_auth),
) -> list[MatterOut]:
    """List matters. INVEST first, then priority_rank (nulls last), then caption."""
    try:
        rows = mtq.list_matters(
            human_label=human_label.value if human_label else None
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return [_matter_out(r) for r in rows]


@router.get("/matters/{slug}", response_model=MatterDetailOut)
def get_matter(
    slug: str,
    _user: str = Depends(require_api_auth),
) -> MatterDetailOut:
    """Matter detail plus recent mdl_events (newest first)."""
    row = mtq.get_matter_by_slug(slug)
    if row is None:
        raise HTTPException(status_code=404, detail="matter not found")
    events = mtq.list_events_for_matter(row["id"])
    base = _matter_out(row)
    return MatterDetailOut(
        **base.model_dump(),
        events=[MdlEventOut.model_validate(ev) for ev in events],
    )


@router.patch("/matters/{slug}", response_model=MatterOut)
def patch_matter(
    slug: str,
    body: MatterPatch,
    _user: str = Depends(require_api_auth),
) -> MatterOut:
    """Update human_label / notes / priority_rank. Auth required. No score writes."""
    fields = body.model_dump(exclude_unset=True)
    if "human_label" in fields and fields["human_label"] is not None:
        fields["human_label"] = fields["human_label"].value
    if not fields:
        raise HTTPException(status_code=422, detail="no patch fields provided")
    try:
        row = mtq.patch_matter(slug, fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail="matter not found")
    return _matter_out(row)

class HarvestEventIn(BaseModel):
    """One mdl_events row to append during a harvest write."""

    event_type: str
    event_date: date | None = None
    cite: str | None = None
    source_url: str | None = None
    summary: str | None = None


class MatterHarvestWrite(BaseModel):
    """Searcher weekly fields. human_label / invest_score are not accepted."""

    mdl_or_jccp_id: str | None = None
    court: str | None = None
    pending_count: int | None = None
    last_event_at: datetime | None = None
    last_event_type: str | None = None
    source_urls: list[str] | None = None
    notes: str | None = None
    cl_filings_delta_7d: int | None = None
    last_verified_at: datetime | None = None
    event: HarvestEventIn | None = None


@router.put("/matters/{slug}/harvest", response_model=MatterDetailOut)
def put_matter_harvest(
    slug: str,
    body: MatterHarvestWrite,
    _user: str = Depends(require_api_auth),
) -> MatterDetailOut:
    """Searcher harvest write by slug. Auth required. Never writes score/labels."""
    payload = body.model_dump(exclude_unset=True)
    event_raw = payload.pop("event", None)
    # Strip explicit Nones left in nested dump when event was set
    fields = {k: v for k, v in payload.items() if k != "event"}
    try:
        row = mtq.apply_harvest_write(slug, fields, event=event_raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail="matter not found")
    events = mtq.list_events_for_matter(row["id"])
    base = _matter_out(row)
    return MatterDetailOut(
        **base.model_dump(),
        events=[MdlEventOut.model_validate(ev) for ev in events],
    )

