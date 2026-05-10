"""SIGNAL FastAPI dashboard.

Server-rendered Jinja templates + HTMX for interactivity. Tailwind via CDN.
Replaces src/signalwarn/app.py (Streamlit).

Run locally:
    uvicorn web.app:app --reload --port 8080
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import threading
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from signalwarn.config import settings
from signalwarn.migrations import apply_pending
from signalwarn.viability import regenerate_memo_if_needed
from web import queries

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Apply pending DDL on every boot so deploys auto-migrate.

    Every statement in `signalwarn.migrations.PENDING` is idempotent
    (`IF NOT EXISTS`), so calling this on every container start is safe
    and a no-op once the schema is up to date. Failures are logged but
    don't crash the app — a transient DB blip at boot shouldn't take
    the web service down.
    """
    apply_pending()
    yield


app = FastAPI(title="SIGNAL", docs_url=None, redoc_url=None, lifespan=lifespan)
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
    sort: str = Query("score"),
    direction: str = Query("desc"),
    page: int = Query(1, ge=1),
) -> Response:
    year_int: int | None = None
    if year:
        try:
            year_int = int(year)
        except ValueError:
            year_int = None
    if sort not in queries.SORT_COLUMNS:
        sort = "score"
    direction = direction.lower()
    if direction not in ("asc", "desc"):
        direction = "desc"
    window_days = queries.ACTIVITY_WINDOWS.get(window)
    offset = (page - 1) * PAGE_SIZE
    clusters, total = queries.list_clusters(
        activity_window_days=window_days,
        make=make,
        model_year=year_int,
        classification=classification,
        search=q,
        sort=sort,
        direction=direction,
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
    # Filters only (no sort/direction) — used by sortable column headers so
    # clicking a header keeps the filter context.
    filter_params = {
        "window": window, "make": make or "", "year": year_int or "",
        "classification": classification or "", "q": q or "",
    }
    filters_qs = urlencode({k: v for k, v in filter_params.items() if v})
    # Filters + sort/direction — used by pagination links so the page stays sorted.
    base_params = {
        **filter_params,
        "sort": sort if sort != "score" else "",
        "direction": direction if (sort != "score" or direction != "desc") else "",
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
            "selected_sort": sort,
            "selected_direction": direction,
            "sort_default_dir": queries.SORT_DEFAULT_DIR,
            "selected_classification": classification or "ALL",
            "q": q or "",
            "page": page,
            "last_page": last_page,
            "page_size": PAGE_SIZE,
            "base_qs": base_qs,
            "filters_qs": filters_qs,
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


# ─── Admin operations ───────────────────────────────────────────────────
#
# Admin tasks (re-checking filings, rescoring all clusters, manually applying
# migrations) used to require `railway ssh` + manually running scripts. That
# was painful and brittle (PowerShell-on-Windows + remote SSH = bad). The
# admin page below exposes one-click triggers for each operation, runs them
# as background threads, and shows the latest status in-page. No SSH needed.
#
# Tasks run in daemon threads so they survive uvicorn worker recycling
# gracefully and write logs to stdout (visible in Railway Logs tab).

_admin_status: dict[str, dict] = {
    "check_filings": {"state": "idle", "started_at": None, "finished_at": None,
                      "summary": None, "args": None, "error": None},
    "rescore_all":   {"state": "idle", "started_at": None, "finished_at": None,
                      "summary": None, "args": None, "error": None},
}
_admin_lock = threading.Lock()


def _admin_run(task_key: str, args: dict, fn, *fn_args, **fn_kwargs) -> None:
    """Background-thread wrapper that updates _admin_status as the task progresses."""
    with _admin_lock:
        _admin_status[task_key].update(
            state="running",
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            summary=None,
            args=args,
            error=None,
        )
    try:
        result = fn(*fn_args, **fn_kwargs)
        with _admin_lock:
            _admin_status[task_key].update(
                state="done",
                finished_at=datetime.now(timezone.utc),
                summary=result,
            )
    except Exception as e:  # noqa: BLE001
        log.exception("admin task %s failed", task_key)
        with _admin_lock:
            _admin_status[task_key].update(
                state="error",
                finished_at=datetime.now(timezone.utc),
                error=str(e),
            )


def _admin_busy(task_key: str) -> bool:
    with _admin_lock:
        return _admin_status[task_key]["state"] == "running"


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: str = Depends(require_auth)) -> Response:
    """Operations dashboard. Shows current task status + buttons to trigger work."""
    with _admin_lock:
        status_snapshot = {k: dict(v) for k, v in _admin_status.items()}
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "title": "SIGNAL — Admin",
            "user": user,
            "status": status_snapshot,
            **_ticker_ctx(),
        },
    )


@app.post("/admin/check-filings")
def admin_check_filings(
    request: Request,
    user: str = Depends(require_auth),
    min_score: int = Form(70),
    matched_only: bool = Form(False),
) -> Response:
    """Kick off a CourtListener filings check as a background thread."""
    if _admin_busy("check_filings"):
        return RedirectResponse("/admin?msg=already-running", status_code=303)

    from signalwarn.filings_check import run_check_filings

    args = {"min_score": min_score, "matched_only": matched_only}
    threading.Thread(
        target=_admin_run,
        args=("check_filings", args, run_check_filings),
        kwargs={"min_score": min_score, "matched_only": matched_only},
        daemon=True,
        name="check_filings",
    ).start()
    return RedirectResponse("/admin?msg=started", status_code=303)


@app.post("/admin/rescore-all")
def admin_rescore_all(request: Request, user: str = Depends(require_auth)) -> Response:
    """Kick off a full rescore as a background thread."""
    if _admin_busy("rescore_all"):
        return RedirectResponse("/admin?msg=already-running", status_code=303)

    from signalwarn.historical import rescore_all_clusters

    def _run() -> dict:
        n = rescore_all_clusters()
        return {"clusters_rescored": n}

    threading.Thread(
        target=_admin_run,
        args=("rescore_all", {}, _run),
        daemon=True,
        name="rescore_all",
    ).start()
    return RedirectResponse("/admin?msg=started", status_code=303)


# ─── Cluster operations (existing) ──────────────────────────────────────


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
