"""SIGNAL FastAPI dashboard.

Server-rendered Jinja templates + HTMX for interactivity. Tailwind via CDN.
Replaces src/signalwarn/app.py (Streamlit).

Run locally:
    uvicorn web.app:app --reload --port 8080
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from signalwarn.config import settings
from signalwarn.viability import regenerate_memo_if_needed
from web import queries

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))

app = FastAPI(title="SIGNAL", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.signal_password + "::" + settings.signal_username,
    same_site="lax",
    https_only=settings.environment == "production",
    max_age=60 * 60 * 24 * 365,  # 1 year — auth is for competitive protection, not turnover
)
app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")


# ─── Template globals ──────────────────────────────────────────────────

# Make header_stats available to every authenticated template via a context
# processor (Jinja global rebuilt per-request via templates.env... but simpler
# to fetch in the route and pass).


def _ticker_ctx() -> dict:
    """Stats for the top status-strip. Fetched per page load — sub-ms query."""
    return {"ticker": queries.header_stats()}


CLASSIFICATION_BADGE = {
    "CRITICAL": ("CRITICAL", "bg-rose-500/15 text-rose-300 ring-rose-500/30"),
    "HOT":      ("HOT",      "bg-orange-500/15 text-orange-300 ring-orange-500/30"),
    "WATCH":    ("WATCH",    "bg-amber-500/15 text-amber-300 ring-amber-500/30"),
    "MONITOR":  ("MONITOR",  "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"),
    "NOISE":    ("NOISE",    "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30"),
}
CLASSIFICATION_ORDER = ("CRITICAL", "HOT", "WATCH", "MONITOR")

templates.env.globals["CLASSIFICATION_BADGE"] = CLASSIFICATION_BADGE
templates.env.globals["CLASSIFICATION_ORDER"] = CLASSIFICATION_ORDER
templates.env.globals["ACTIVITY_WINDOWS"] = queries.ACTIVITY_WINDOWS


# ─── Auth ───────────────────────────────────────────────────────────────

def require_auth(request: Request) -> str:
    """Dependency: redirect to /login if not signed in."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


@app.exception_handler(303)
async def redirect_handler(_request: Request, exc: HTTPException) -> Response:
    return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None) -> Response:
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": error, "title": "Sign in"}
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    users = settings.users()
    if users.get(username) == password:
        request.session["user"] = username
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/login?error=invalid", status_code=303)


@app.get("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─── Dashboard ──────────────────────────────────────────────────────────

PAGE_SIZE = 50


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: str = Depends(require_auth),
    window: str = Query("Past 6 months"),
    make: str | None = Query(None),
    # Accept str so the empty-string the filter form submits when "All years"
    # is selected (year=) parses cleanly. Coerce to int below.
    year: str | None = Query(None),
    classification: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
) -> Response:
    year_int: int | None = None
    if year:
        try:
            year_int = int(year)
        except ValueError:
            year_int = None
    window_days = queries.ACTIVITY_WINDOWS.get(window)
    offset = (page - 1) * PAGE_SIZE
    clusters, total = queries.list_clusters(
        activity_window_days=window_days,
        make=make,
        model_year=year_int,
        classification=classification,
        search=q,
        limit=PAGE_SIZE,
        offset=offset,
    )
    counts = queries.classification_counts(activity_window_days=window_days)
    last_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    stat_sparks = queries.classification_sparklines(months=12)

    sparklines = queries.sparklines_for_clusters(
        [c["id"] for c in clusters], months=12
    )

    from datetime import date as _date
    today_local = _date.today()
    for c in clusters:
        last = c.get("last_complaint_date")
        c["days_since_last"] = (today_local - last).days if last else None
        c["sparkline"] = sparklines.get(c["id"], [])
        c["sparkline_max"] = max(c["sparkline"]) if c["sparkline"] else 0

    # Build a query string preserving filters for pagination links.
    from urllib.parse import urlencode
    base_params = {
        "window": window, "make": make or "", "year": year_int or "",
        "classification": classification or "", "q": q or "",
    }
    base_qs = urlencode({k: v for k, v in base_params.items() if v})

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "title": "SIGNAL",
            "user": user,
            "clusters": clusters,
            "total": total,
            "counts": counts,
            "stat_sparks": stat_sparks,
            "makes": queries.all_makes(),
            "years": queries.all_years(),
            "selected_window": window,
            "selected_make": make,
            "selected_year": year_int,
            "selected_classification": classification or "ALL",
            "q": q or "",
            "page": page,
            "last_page": last_page,
            "page_size": PAGE_SIZE,
            "base_qs": base_qs,
            "last_ingestion": queries.last_ingestion(),
            **_ticker_ctx(),
        },
    )


# ─── Cluster detail ─────────────────────────────────────────────────────

@app.get("/cluster/{cluster_id}", response_class=HTMLResponse)
def cluster_detail(
    request: Request,
    cluster_id: int,
    page: int = Query(1, ge=1),
    user: str = Depends(require_auth),
) -> Response:
    cluster = queries.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(404, "Cluster not found")

    page_size = 20
    offset = (page - 1) * page_size
    complaints = queries.list_complaints(cluster_id, limit=page_size, offset=offset)
    total = queries.count_complaints(cluster_id)
    last_page = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        request,
        "cluster.html",
        {
            "title": f"{cluster['make']} {cluster['model']} — {cluster['component']}",
            "user": user,
            "cluster": cluster,
            "complaints": complaints,
            "states": queries.states_for_cluster(cluster_id),
            "volume": queries.complaints_per_month(cluster_id),
            "page": page,
            "last_page": last_page,
            "total_complaints": total,
            **_ticker_ctx(),
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = Query("", max_length=120),
    user: str = Depends(require_auth),
) -> Response:
    """Cmd+K palette: returns an HTML fragment of matching clusters."""
    results = queries.search_clusters(q, limit=10)
    return templates.TemplateResponse(
        request, "_search_results.html", {"results": results, "q": q}
    )


@app.get("/cluster/{cluster_id}/panel", response_class=HTMLResponse)
def cluster_panel(
    request: Request,
    cluster_id: int,
    user: str = Depends(require_auth),
) -> Response:
    """Slim detail HTML for the dashboard's slide-in side panel."""
    cluster = queries.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "_panel.html",
        {
            "cluster": cluster,
            "complaints": queries.list_complaints(cluster_id, limit=20, offset=0),
            "states": queries.states_for_cluster(cluster_id),
            "volume": queries.complaints_per_month(cluster_id),
            "total_complaints": queries.count_complaints(cluster_id),
        },
    )


@app.post("/cluster/{cluster_id}/regenerate-memo", response_class=HTMLResponse)
def regenerate_memo(
    request: Request,
    cluster_id: int,
    user: str = Depends(require_auth),
) -> Response:
    if not settings.anthropic_api_key:
        return HTMLResponse(
            '<div class="text-rose-400 text-sm">ANTHROPIC_API_KEY not set; '
            'memo generation disabled.</div>',
            status_code=400,
        )
    try:
        regenerate_memo_if_needed(cluster_id, force=True)
    except Exception as e:  # noqa: BLE001
        log.exception("memo regen failed for cluster %s", cluster_id)
        return HTMLResponse(
            f'<div class="text-rose-400 text-sm">Failed: {e}</div>',
            status_code=500,
        )

    cluster = queries.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(404)
    # Return just the memo card so HTMX can swap it in place.
    return templates.TemplateResponse(
        request, "_memo_card.html", {"cluster": cluster}
    )
