# P0 cluster-filing corrections (Norberg / Thieme / O'Connor)

**Date:** 2026-09-25
**Status:** code landed in PR; prod DB still needs Jimmy re-check / SQL

## Mapping mechanism today

There is **no seed case→cluster table**. Attachment is:

1. Cluster key = `{MAKE}::{MODEL}::{YEAR|ALL_YEARS}::{COMPONENT}` (`clustering.make_cluster_key`).
2. `scripts/check_filings.py` → `filings_check.run_check_filings` → CourtListener
   `find_class_action(make, model, component)`.
3. Result written onto the cluster row: `class_action_filed`, `class_action_same_defect`,
   `class_action_case_name`, `class_action_court`, `class_action_status`
   (`pending`|`terminated` from `dateTerminated`), URL, dates.
4. Dashboard hide rule: `EXCLUDE_FILED_SQL` = filed AND same_defect (and, after this
   change, status ≠ `cert_denied`).

Norberg, Petro, Thieme, O'Connor do **not** appear as hard-coded strings anywhere
in the repo before this change.

## The three P0 failures

1. **Norberg Hurricane ECM vs Petro HEMI** — both live on `RAM::1500::*::ENGINE`.
   First plausible CourtListener hit wins; one slot per cluster collapses the tracks.
2. **Thieme vacuum-pump** — `COMPONENT_KEYWORDS["BRAKES"]` includes `vacuum pump`,
   and plausibility only checks manufacturer → Equinox/Terrain/Envision suit attaches
   to Suburban / Yukon BRAKES.
3. **O'Connor 10R80** — cert denied N.D. Ill. 2026-09-14, but `dateTerminated` is
   null so status stays `pending` → Signal treats it as an open cert path.

## What this PR does (no schema migration)

New module `signalwarn/filing_corrections.py`:

- **MODEL_SIBLINGS** + caption model detection → reject cross-family hits (Thieme).
- **CAPTION_RULES** for Norberg / Petro / Thieme / O'Connor:
  - Norberg allowed on RAM 1500 ENGINE/ELECTRICAL but `same_defect=False` so it
    does not hide/collapse the Petro HEMI opportunity on the shared ENGINE key.
  - Petro stays `same_defect=True` on RAM 1500 ENGINE.
  - Thieme only on CHEVROLET EQUINOX BRAKES.
  - O'Connor → `status_override=cert_denied` on FORD F-150 POWER TRAIN.
- `find_class_action` consults `allowed_by_corrections`.
- `filings_check` applies status / same_defect overrides when persisting.
- `EXCLUDE_FILED_SQL` keeps `cert_denied` clusters **visible** with a status flag.
- Research candidates skip `cert_denied` (not an open cert research target).
- Cluster page shows an orange "Class certification DENIED" pill.

## What Jimmy still needs to do

1. Merge + deploy.
2. Re-run filings check on touched clusters (or apply SQL below against prod).
3. Confirm live cluster keys / case captions in prod match the allow-lists.
4. Longer-term (needs Jimmy sign-off): sub-defect cluster keys or multi-filing
   support so Norberg and Petro can each own a same_defect flag on ENGINE.

### Suggested prod SQL (run by Jimmy; do not run from the box)

```sql
-- 1) Clear Thieme mis-attachments on full-size SUV BRAKES
UPDATE clusters
   SET class_action_filed = FALSE,
       class_action_same_defect = FALSE,
       class_action_url = NULL,
       class_action_case_name = NULL,
       class_action_court = NULL,
       class_action_filed_date = NULL,
       class_action_status = NULL,
       class_action_terminated_date = NULL,
       class_action_checked_at = NULL
 WHERE make IN ('CHEVROLET', 'GMC')
   AND model IN ('SUBURBAN', 'YUKON', 'TAHOE')
   AND component = 'BRAKES'
   AND class_action_case_name ILIKE '%Thieme%';

-- 2) If Norberg is currently pinned as same-defect on RAM 1500 ENGINE, demote
UPDATE clusters
   SET class_action_same_defect = FALSE
 WHERE make = 'RAM' AND model = '1500' AND component = 'ENGINE'
   AND class_action_case_name ILIKE '%Norberg%';

-- 3) Flag O'Connor cert denial on F-150 POWER TRAIN
UPDATE clusters
   SET class_action_status = 'cert_denied',
       class_action_filed = TRUE,
       class_action_same_defect = TRUE
 WHERE make = 'FORD' AND model = 'F-150' AND component = 'POWER TRAIN'
   AND (
        class_action_case_name ILIKE '%O''Connor%'
     OR class_action_case_name ILIKE '%OConnor%'
   );

-- Then rescore affected rows (admin rescore or scripts/rescore_all.py).
```

After deploy, prefer `python scripts/check_filings.py --matched-only` (or
`--recheck-days 0`) so CourtListener re-attachments go through the new rules.
