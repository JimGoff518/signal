# SIGNAL

> Mass tort early warning system for Goff Law PLLC.
> Reads public NHTSA complaint data, clusters defects, scores litigation potential,
> and surfaces emerging cases years before they become public.

**Phase 1 MVP — Confidential. Internal use only.**

For full business context, see [docs/SIGNAL_README.md](docs/SIGNAL_README.md).
For build details, see [docs/SIGNAL_TECHNICAL_SPEC.md](docs/SIGNAL_TECHNICAL_SPEC.md).
For roadmap, see [docs/SIGNAL_PLAN_AND_GOALS.md](docs/SIGNAL_PLAN_AND_GOALS.md).

---

## Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Database | PostgreSQL (Supabase-compatible) |
| Web UI | Streamlit |
| AI | Claude Sonnet 4.6 (viability memos) |
| Email | Resend |
| Hosting | Railway |

---

## Quickstart

```bash
# 1. Start Postgres in Docker (schema is applied automatically on first boot)
docker compose up -d

# 2. Create a virtual environment + install deps
python -m venv .venv
.venv\Scripts\activate                      # Windows PowerShell
pip install -r requirements.txt
pip install -e .                            # makes `signalwarn` importable everywhere (req'd for streamlit)

# (Phase 2 only) install the vendored crawl4ai for community scraping:
# pip install -e vendor/crawl4ai && playwright install chromium

# 3. Copy the env template
copy .env.example .env                      # Windows

# 4. (One-shot) Bulk-load 10 years of NHTSA history so the dashboard
#    launches with real clusters instead of an empty page.
#    Auto-downloads FLAT_CMPL.zip if missing; uses local FLAT_RCL/FLAT_INV
#    if you have them at the repo root.
python scripts/historical_import.py

# 5. Daily delta — pull the last 7 days of new complaints
python scripts/run_ingestion.py

# 6. Launch the dashboard
streamlit run src/signalwarn/app.py
```

To wipe the dev database and start over: `docker compose down -v`.

---

## Project layout

```
Signal/
├── docs/                          source business + technical specs
├── migrations/                    SQL schema migrations
├── scripts/                       one-shot CLIs (ingestion, scoring, etc.)
├── src/signalwarn/                    application code
│   ├── config.py                  env-driven settings
│   ├── db.py                      Postgres connection + helpers
│   ├── nhtsa.py                   NHTSA API client
│   ├── normalize.py               component normalization
│   ├── clustering.py              cluster builder
│   ├── scoring.py                 0–100 scoring engine
│   ├── ingestion.py               daily pull → store → cluster → score
│   ├── viability.py               Claude viability memo generation
│   ├── alerts.py                  Resend email alerts
│   └── app.py                     Streamlit dashboard
└── tests/                         pytest unit tests
```

---

## Daily ingestion (production)

Set up a Railway cron job to run `python scripts/run_ingestion.py` once per day at 02:00 CT.
The script will:
1. Pull complaints filed in the last 7 days for every tracked make/model/year.
2. Insert new complaints (deduped by `odi_number`).
3. Update or create clusters.
4. Recalculate scores for affected clusters.
5. Trigger viability memo generation for any cluster newly at WATCH or above.
6. Send the daily digest email and any death alerts.

---

## Tracked vehicles

Phase 1 monitors a hardcoded list of high-volume makes (Ford, Chevrolet, GMC, Ram,
Toyota, Honda, Nissan, Jeep, Tesla, Hyundai, Kia) for model years 2015–2025.
See `src/signalwarn/ingestion.py::TRACKED_VEHICLES` to edit.
