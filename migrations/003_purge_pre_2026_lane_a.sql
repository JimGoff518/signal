-- Lane A hard purge: NHTSA complaints filed before calendar year 2026.
-- Locked 2026-10-01 (Jimmy exact-yes via CoS / Signal room).
--
-- IMPORTANT
-- ---------
-- This file is a one-shot / docker-init twin of
--   scripts/purge_pre_2026_lane_a.py  +  signalwarn.purge_lane_a
-- It is intentionally NOT registered in signalwarn.migrations.PENDING so
-- FastAPI startup never auto-runs a destructive DELETE against production.
-- Prefer the Python script (preview → --execute) for live databases.
--
-- Date field: complaints.date_complaint_filed (Postgres DATE).
-- Semantics: calendar date as stored from NHTSA; no CT/UTC conversion.
-- NULL filed dates are purged (ineligible under the new ingest gate).
--
-- Mass Tort (Lane B) is completely untouched — no mass_tort_* / mdl_events DDL
-- or DML appears below.
--
-- Delete order (FK-safe):
--   1. complaints (pre-2026 / NULL) → cluster_complaints CASCADE
--   2. orphan clusters (no remaining memberships) → alerts_sent CASCADE;
--      viability_memo / research_memo live on clusters and go with the row.
-- Surviving mixed clusters need recalculate_cluster (script does this;
-- plain SQL below does not rescore).

BEGIN;

DELETE FROM complaints c
 WHERE c.date_complaint_filed IS NULL
    OR c.date_complaint_filed < DATE '2026-01-01';

DELETE FROM clusters cl
 WHERE NOT EXISTS (
   SELECT 1 FROM cluster_complaints cc
    WHERE cc.cluster_id = cl.id
 );

COMMIT;
