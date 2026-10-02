# Lane A hard purge — pre-2026 NHTSA filings

**Locked 2026-10-01** (Jimmy exact-yes via CoS / Signal room). Soft-delete / staff-hide rejected.

## Decision

1. **Hard purge** Lane A complaints whose **`date_complaint_filed`** is before calendar year 2026 (or NULL).
2. **Stop ingest** of the same window (daily API + historical flat-file).
3. **Mass Tort (Lane B) untouched** — no DML/DDL on `mass_tort_matters` / `mdl_events`.
4. After purge, ALL_YEARS year-span labels recompute from remaining 2026 siblings.

## Date field / timezone

- Column: `complaints.date_complaint_filed` (Postgres `DATE`).
- Source: NHTSA `dateComplaintFiled` / flat-file field 16, parsed to a calendar `date`.
- **No CT/UTC conversion** — comparison is calendar-date against `2026-01-01`.
- Not model year. Not `date_of_incident`.

## How to run (ops)

```bash
# Preview
python scripts/purge_pre_2026_lane_a.py

# Irreversible delete + rescore survivors
python scripts/purge_pre_2026_lane_a.py --execute
```

SQL twin: `migrations/003_purge_pre_2026_lane_a.sql` (not in `PENDING` — will not auto-run on app boot).

## Delete order

1. `DELETE` pre-window `complaints` → `cluster_complaints` CASCADE.
2. `DELETE` orphan `clusters` → `alerts_sent` CASCADE; memos on cluster row go with it.
3. Script rescored remaining clusters.
