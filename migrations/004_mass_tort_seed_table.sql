-- Mass Tort seed table upgrade (Jimmy lock 2026-10-02 via CoS / GLTD).
-- Adds harvest fields + HOLD label. Stage strip reuses last_event_type
-- (no separate stage column). Mass Tort only — no Lane A / ads / Filevine.

BEGIN;

-- Harvest fields Searcher fills later (7d CL Δ left NULL at seed time).
ALTER TABLE mass_tort_matters
  ADD COLUMN IF NOT EXISTS cl_filings_delta_7d INTEGER NULL;

ALTER TABLE mass_tort_matters
  ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ NULL;

COMMIT;

-- ADD VALUE cannot reliably run inside an open transaction on older PG;
-- IF NOT EXISTS keeps re-runs safe (PG 9.3+).
ALTER TYPE mass_tort_human_label ADD VALUE IF NOT EXISTS 'HOLD';

BEGIN;

-- PASS → HOLD for Jimmy decision language (invest / chase / hold).
-- WATCH stays WATCH (early watch ≠ hold). PASS remains a valid enum
-- value for back-compat reads; UI displays PASS as HOLD.
UPDATE mass_tort_matters
   SET human_label = 'HOLD',
       updated_at = NOW()
 WHERE human_label = 'PASS';

-- Backfill last_event_type for stage strip (filings → MDL → bellwether →
-- settlement). Only when currently NULL so a later harvest is not overwritten.
-- Granted federal MDLs → transfer_order (MDL strip).
UPDATE mass_tort_matters
   SET last_event_type = 'transfer_order',
       updated_at = NOW()
 WHERE slug IN (
   'ai-litigation',
   'roblox',
   'spinal-cord-stimulator',
   'glp1-gi',
   'social-media-addiction',
   'glp1-naion',
   'hair-relaxer',
   'pfas-afff'
 )
   AND last_event_type IS NULL;

-- Pre-MDL / no federal MDL → jpml_motion (Filings strip).
UPDATE mass_tort_matters
   SET last_event_type = 'jpml_motion',
       updated_at = NOW()
 WHERE slug IN (
   'galaxy-gas',
   'chlorpyrifos',
   'olympus-scope',
   'openai-suicide-pl'
 )
   AND last_event_type IS NULL;

-- Exactech: bankruptcy-dominated; EVENT_TYPES has no bankruptcy — use other.
-- Settlement posture deferred to a later PR.
UPDATE mass_tort_matters
   SET last_event_type = 'other',
       updated_at = NOW()
 WHERE slug = 'exactech'
   AND last_event_type IS NULL;

-- Searcher baseline stamp (2026-09-30 CT).
UPDATE mass_tort_matters
   SET last_verified_at = TIMESTAMPTZ '2026-09-30 12:00:00-05:00',
       updated_at = NOW()
 WHERE slug IN (
   'ai-litigation',
   'openai-suicide-pl',
   'galaxy-gas',
   'roblox',
   'spinal-cord-stimulator',
   'glp1-gi',
   'social-media-addiction',
   'olympus-scope',
   'chlorpyrifos',
   'glp1-naion',
   'hair-relaxer',
   'pfas-afff',
   'exactech'
 )
   AND last_verified_at IS NULL;

-- cl_filings_delta_7d intentionally left NULL (Searcher harvest fills later).

COMMIT;
