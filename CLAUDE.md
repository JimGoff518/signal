# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

SIGNAL is a **consumer class-action + product-liability** early warning system for Goff Law PLLC, with mass-tort patterns surfaced as a secondary lens. It pulls NHTSA vehicle complaint data, clusters defects by make/model/year/component, scores each cluster 0-100 against Rule 23 class-certification criteria (numerosity, commonality, manufacturer knowledge, economic harm) plus mass-tort severity signals, generates Anthropic-powered viability memos for high-scoring clusters, and emails periodic digests + death alerts. Phase 1 MVP, currently in production. The full business + algorithmic context lives in [docs/SIGNAL_README.md](docs/SIGNAL_README.md), [docs/SIGNAL_TECHNICAL_SPEC.md](docs/SIGNAL_TECHNICAL_SPEC.md), and [docs/SIGNAL_PLAN_AND_GOALS.md](docs/SIGNAL_PLAN_AND_GOALS.md) — read those if anything in code feels arbitrary; the *why* lives there.

**Why class-action-first matters:** Personal-injury cases with severe individual harm rarely survive Rule 23 certification (predominance defeats class treatment per *Amchem*) — they go mass-tort instead. Consumer class actions and product liability thrive on widespread *uniform* harm: economic damage, warranty failures, systemic design defects across many units/years. The scoring algorithm reflects this: numerosity and commonality outweigh injury severity. See [docs/SIGNAL_TECHNICAL_SPEC.md §7](docs/SIGNAL_TECHNICAL_SPEC.md) for the formula.

## Common commands

Use the project venv's Python (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on POSIX) for all Python invocations so you stay on the pinned interpreter.

| Task | Command |
|---|---|
| Run all tests | `.venv/Scripts/python.exe -m pytest` |
| Run one test file | `.venv/Scripts/python.exe -m pytest tests/test_scoring.py` |
| Run one test | `.venv/Scripts/python.exe -m pytest tests/test_scoring.py::test_compute_score_basic` |
| Tests with coverage | `.venv/Scripts/python.exe -m pytest --cov=signalwarn --cov=web` |
| Lint | `.venv/Scripts/python.exe -m ruff check .` (config in `pyproject.toml`) |
| Format | `.venv/Scripts/python.exe -m ruff format .` |
| FastAPI dev server | `.venv/Scripts/python.exe -m uvicorn web.app:app --reload --port 8080` |
| Streamlit dev server (legacy) | `.venv/Scripts/python.exe -m streamlit run src/signalwarn/app.py` |
| Daily ingest (one-off) | `.venv/Scripts/python.exe scripts/run_ingestion.py` |
| Bulk historical seed | `.venv/Scripts/python.exe scripts/historical_import.py` |
| Mirror NHTSA datasets | `.venv/Scripts/python.exe scripts/download_nhtsa_datasets.py` |
| Local Postgres up/down | `docker compose up -d` / `docker compose down -v` |
| Rebuild dashboard CSS | `npm install` once, then `npm run css` (or `npm run css:watch`) |

There is no Python build step — `pip install -e .` makes `signalwarn` importable across the project. The only compiled asset is the dashboard stylesheet: Tailwind is compiled ahead of time into `web/static/app.css`, which is **committed** (Railway's image has no Node). Run `npm run css` after touching any template or `web/tailwind.css` / `tailwind.config.js`, and commit the result.

## Architecture (the big picture)

**One pipeline, two front-ends.** The data pipeline is the product; the dashboards are read-only views over the cluster table.

```
NHTSA API/flatfiles ──▶ ingestion ──▶ complaints (table)
                                          │
                                          ▼
                                     clustering ──▶ clusters (table)
                                          │
                                          ▼
                                       scoring ──▶ score + classification on cluster row
                                          │
                                          ▼
                            (score >= 50)  viability memo (Claude) ──▶ stored on cluster row
                                          │
                                          ▼
                                        alerts (Resend) — daily digest + death alert
```

The pipeline is invoked two ways:
- **`scripts/historical_import.py`** — one-shot bulk seed from NHTSA flat-file zips (FLAT_CMPL.zip auto-downloads; FLAT_RCL/FLAT_INV optional from repo root). Skip flags: `--skip-complaints`, `--skip-recalls`, `--skip-investigations`. Run once on initial deploy.
- **`scripts/run_ingestion.py`** — incremental delta. Pulls each tracked vehicle's full complaint list via the live API and keeps rows filed in the last N days (`NHTSA_LOOKBACK_DAYS`, default **180**), then re-clusters, re-scores, regenerates memos for newly-WATCH+ clusters, and sends alerts. Runs as a Railway cron service named `signal` on schedule `0 7 */3 * *` UTC = 02:00 CT every 3 days. **Keep the window wide:** NHTSA publishes complaints weeks after filing, so a 7-day window silently discards most of them (this caused a five-month volume gap in 2026). Duplicates are impossible (`ON CONFLICT (odi_number)`). The same refresh can be triggered from `/admin`.

**Cluster model.** Every complaint joins **two** clusters: a per-year cluster (`{MAKE}::{MODEL}::{YEAR}::{COMPONENT}`) and a cross-year aggregate (`{MAKE}::{MODEL}::ALL_YEARS::{COMPONENT}`, with `model_year=NULL` and `is_multi_year=TRUE`). The aggregate gets a +20 multi-year bonus when complaints span multiple years. See [src/signalwarn/clustering.py](src/signalwarn/clustering.py).

**Scoring (rebalanced 2026-05-09 for class-action lens).** Pure function in [src/signalwarn/scoring.py](src/signalwarn/scoring.py): `ClusterFacts → 0-100 int`. Formula: `min(complaints, 50)` (numerosity) × velocity multiplier (×3 if 30-day count ≥ 0.66 of total, else ×2 if ≥ 0.5) + 20 if multi-year (commonality) + 25 if NHTSA investigation open + 30 if recall issued (manufacturer knowledge) + reduced severity escalators (10 injury / 20 death / 5 crash / 10 fire — secondary mass-tort lens) − 30 if class action already filed. Clamped to [0, 100]. See `docs/SIGNAL_TECHNICAL_SPEC.md §7.2` for the rationale and `tests/test_scoring.py` for archetype tests that lock in the intended behavior shift.

**Exclusions (added 2026-09-18, spec §7.6).** Two rules sit in front of scoring. (1) *Statute of limitations, complaint level:* only complaints whose incident date (falling back to the NHTSA filing date) is within the last `SOL_YEARS` years (default 4) feed any cluster aggregate; the rest stay attached but are counted in `clusters.time_barred_count`. Because the window is relative to today, `run_ingestion.py` rescores every cluster each run. (2) *Filed class action, cluster level:* any cluster with `class_action_filed = TRUE`, pending or terminated, is hidden from the dashboard, tier counts, memos, digest and death alerts via the shared `EXCLUDE_FILED_SQL` predicate in [src/signalwarn/clustering.py](src/signalwarn/clustering.py). The dashboard's "Show filed only" option is the audit view.

**Two front-ends, one DB.** [web/app.py](web/app.py) is the current FastAPI + Jinja + HTMX + Tailwind dashboard. [src/signalwarn/app.py](src/signalwarn/app.py) is the legacy Streamlit app being phased out — make UI changes in `web/`, not Streamlit, unless explicitly asked. Both share `signalwarn.db` and read the same tables.

**DB connection nuance.** [src/signalwarn/db.py](src/signalwarn/db.py) supports both raw psycopg (`connection()` context manager, dict-row cursors, auto-commit on success) and SQLAlchemy (`engine()`, used by Streamlit + pandas). The URL massaging functions handle `postgresql://`, `postgres://` (Heroku), and `postgresql+psycopg://` so callers can pass any form.

**Config.** [src/signalwarn/config.py](src/signalwarn/config.py) is the single source of truth — pydantic-settings reading `.env`. Pinecone vars are *declared* but *unused* (Phase 2). LangSmith tracing is opt-in via `LANGSMITH_TRACING=true`. The single-user login uses `SIGNAL_USERNAME` + `SIGNAL_PASSWORD`; multi-user JSON map via `SIGNAL_USERS={"user":"pass",...}` takes precedence when set.

## Things that bite

- **Tracked vehicles are hardcoded** in [src/signalwarn/ingestion.py](src/signalwarn/ingestion.py) (`TRACKED_VEHICLES`, model years 2015-2025). Adding/removing makes happens here, not in config.
- **EWR (manufacturer death/injury reports) has no API.** NHTSA only exposes Early Warning Reporting data through its interactive search, so Jim exports one text file per manufacturer per quarter and uploads them on `/admin`; [src/signalwarn/ewr.py](src/signalwarn/ewr.py) parses, dedupes and rolls them up onto `clusters.ewr_*`. The site blocks scripted fetches; don't try to automate the download.
- **Component normalization** in [src/signalwarn/normalize.py](src/signalwarn/normalize.py) maps NHTSA's free-text component strings to ~15 canonical buckets. The cluster key uses the *normalized* component, so changes to the mapping change cluster identity.
- **Migrations are unversioned.** Only [migrations/001_initial_schema.sql](migrations/001_initial_schema.sql) exists; there's no migration runner. The Dockerfile and `docker-compose.yml` apply it on first boot. New schema changes need to land in this file *and* in any prod DB by hand — coordinate with Jim before changing schema.
- **Vendored crawl4ai** lives in [vendor/crawl4ai/](vendor/crawl4ai/) (~30M, intentionally committed to repo, intentionally **excluded** from Railway uploads via `.railwayignore`). It's reserved for Phase 2 (Reddit / CarComplaints scraping); no current code imports it.
- **Bulk data files in repo root** (`FLAT_CMPL.zip`, `FLAT_RCL_POST_2010.zip`, `FLAT_INV.zip`, `Safercar_data.csv`, etc.) are gitignored and railwayignored — `scripts/historical_import.py` reads from there but `scripts/download_nhtsa_datasets.py` writes new mirrors to `data/raw/`.

## Production (Railway)

- Project: `signal`, environment: `production`. Two services: **`signal-app`** (FastAPI web dashboard at https://signal-mtw.up.railway.app, status "Online") and **`signal`** (cron service running `python scripts/run_ingestion.py` every 3 days at 02:00 CT, status "Ready" between firings). The cron service shares the same repo/Dockerfile as `signal-app` — env vars are configured separately on each.
- The Postgres DB Railway provisions for the app uses `postgres.railway.internal` for in-cluster traffic. **That hostname does not resolve from a developer laptop** — running scripts that hit prod requires either (a) `railway ssh` into `signal-app` and running there, or (b) using the *public* Postgres URL from the Railway dashboard in your local `.env`. Plain `railway run` injects the internal URL and will time out trying to connect.
- Multiple Postgres services exist in the project (`Postgres-LPM7`, `Postgres-D5kM`, etc.) — only the one wired to `signal-app`'s `DATABASE_URL` is live. Don't assume from the names; check the linked variable. The cron service must reference the same DB.
- Deploy: `railway up` from the repo root. The build uses `Dockerfile` (Python 3.12-slim — note: differs from the local 3.14 venv); `.railwayignore` keeps uploads small by excluding `vendor/`, `*.zip`, and `data/raw/`. Healthcheck path is `/healthz` (web service only). A single `railway up` redeploys both services.
- **Collaborators:** as of 2026-05-09, **Jack Kelley** (GitHub: `JKLaw123`) is a repo collaborator and has dashboard credentials. Some sessions may be working alongside him; don't assume Jim is solo.

## Operating notes for Claude Code

- The user's harness blocks production-affecting commands (`railway up`, `railway run` against prod DB, `railway ssh`). Tell the user the exact command to run themselves; don't loop trying variants.
- Don't read `.env` or run `railway variables` — secrets land in transcript.
- New UI work goes in [web/templates/](web/templates/) (Jinja). Design tokens live in `tailwind.config.js`, component classes (`.card`, `.field`, `.meter`, `.pill`, `.eyebrow`) in `web/tailwind.css`; rebuild with `npm run css`. Never build Tailwind class names by string concatenation in templates — the compiler can't see them. Tier colors come from the `PALETTE` template global (`CLASSIFICATION_PALETTE` in `web/app.py`). Design rationale: [docs/plans/2026-09-17-dashboard-ui-refresh-design.md](docs/plans/2026-09-17-dashboard-ui-refresh-design.md).
- When in doubt about *why* something is shaped a certain way, the SIGNAL_TECHNICAL_SPEC.md is the authoritative source — the code has comments tagged with section numbers (`§7.2`, etc.) that point back to it.
