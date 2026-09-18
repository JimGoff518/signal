# Statute-of-limitations and filed-case exclusion — design

**Date:** 2026-09-18
**Status:** approved by Jim, implementing

## Problem

SIGNAL scores clusters on raw complaint volume and shows clusters with a
pending class action (penalised 30 points). Two kinds of noise result:

1. Complaints whose underlying incident is years old inflate numerosity even
   though those class members no longer have a live claim.
2. Clusters where a class action is already on file are not an opportunity
   for the firm, pending or not, yet they still appear on the dashboard, get
   memos, and land in digests.

## Decision

### Statute of limitations — complaint level

- A complaint is **live** when `COALESCE(date_of_incident, date_complaint_filed)`
  is on or after `today - SOL_YEARS` years. If both dates are NULL the
  complaint counts as live (we cannot prove it is barred).
- `SOL_YEARS` is a pydantic setting, default **4**. Rationale: UCC 2-725 warranty
  limitations, which Magnuson-Moss borrows, and Texas contract claims. Two years
  (Texas PI / DTPA) would drop complaints that are live under warranty theories
  or in longer-SOL states; six years keeps too much stale volume.
- `recalculate_cluster` computes every aggregate (count, injuries, deaths,
  crash, fire, velocity, first/last dates, distinct years) over live complaints
  only. Time-barred complaints stay in `cluster_complaints` for the record.
- New column `clusters.time_barred_count` so the cluster page can say
  "14 live · 6 time-barred (older than 4 years)".
- A cluster with zero live complaints is written as count 0 / score 0 / NOISE
  instead of being skipped, so it ages out of the dashboard.
- Because complaints cross the line every day, `run_ingestion.py` rescores
  **all** clusters after ingesting (reusing `rescore_all_clusters`).

### Already-filed cases — cluster level

- Any cluster with `class_action_filed = TRUE` (pending **or** terminated) is
  excluded from: dashboard table, tier counts, charts, header stats, memo
  generation, daily digest, and death alerts.
- One shared predicate (`queries.EXCLUDE_FILED_SQL`) so every surface agrees.
- Dashboard "Class action" filter becomes: *Excluded* (default) and
  *Show filed only* (audit view). The signals-strip "class action pending" link
  opens the audit view.
- Memos page keeps listing historical memos, flagged, as today.
- The −30 penalty in `compute_score` stays; harmless, and the archetype tests
  stay untouched.

## Schema

```sql
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS time_barred_count INTEGER NOT NULL DEFAULT 0;
```

Added to `signalwarn.migrations.PENDING` (auto-applied at web boot) and
mirrored into `migrations/001_initial_schema.sql`.

## Testing

- Pure function `sol_floor(today, years)` and its use in the aggregate SQL.
- `_build_filters` defaults exclude filed; `filed="1"` shows filed only.
- Template tests for the new dropdown options.
- Existing scoring archetype tests unchanged.
