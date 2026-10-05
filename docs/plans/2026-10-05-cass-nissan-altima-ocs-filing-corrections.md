# Cass Altima OCS/airbag filing corrections

**Date:** 2026-10-05
**Status:** code on PR; no migration; Lane A only (no human_label / invest_score)
**Pattern:** same as PR #4 / #5 (`filing_corrections.py` CaptionRule)

## Filing (Scout / Searcher — CL verified)

**Cass v. Nissan North America, Inc.** — FILED / pending (complaint stage) —
C.D. Cal. `5:26-cv-05613`, filed **2026-09-23**.

- CL docket: https://www.courtlistener.com/docket/74842719/cass-v-nissan-north-america-inc/
- Defect: 2016–2018 Nissan Altima passenger occupant classification sensor (OCS)
  alleged to disable the passenger airbag.
- Firm (ClaimDepot): McCune Law Group.
- Harvest: `/workspace/signal-searcher/auto-defect-sweep-2026-10-05/harvest.md`
  (elevated from watch after CL HTML search verified caption/number/date; API was 429).

## Cluster key patterns

Cluster key = `{MAKE}::{MODEL}::{YEAR|ALL_YEARS}::{COMPONENT}`.

| Filing | Component bucket | Intended keys |
|---|---|---|
| Cass OCS/airbag | `AIR BAGS` | `NISSAN::ALTIMA::{2016\|2017\|2018\|ALL_YEARS}::AIR BAGS` |

## TRACKED_VEHICLES coverage

| Named model | In TRACKED_VEHICLES? |
|---|---|
| Nissan Altima | **YES** (`ingestion.TRACKED_VEHICLES`; MODEL_YEARS 2015–2025 covers 2016–2018) |
| Nissan Rogue / Frontier | YES — **reject** Cass attach (wrong model) |

Do **not** invent a new vehicle track or component bucket. OCS maps to existing
NHTSA `AIR BAGS` normalization (`AIR BAG` / `AIRBAG` → `AIR BAGS`).

Live prod row existence for `NISSAN::ALTIMA::*::AIR BAGS` is confirmed only after
deploy + `check_filings` / DB inspect — this PR only ships the mapping layer
(same as Goldenkranz, which shipped rules for then-untracked EV models).

## What this PR does (no schema migration)

Extends `signalwarn/filing_corrections.py`:

- `NISSAN` / `ALTIMA` sibling map + `altima` caption token.
- New rule `cass_nissan_altima_ocs`: allow `NISSAN` + `ALTIMA` + `AIR BAGS` only;
  `same_defect=True` (short CL caption does not name airbag).

## Jimmy / ops still needed

1. Merge this PR (Jimmy yes — do **not** auto-merge); deploy.
2. `python scripts/check_filings.py --recheck-days 0` (or at least Nissan Altima
   AIR BAGS) once CourtListener API is off 429 — prefer over hand SQL.
3. Confirm live prod keys `NISSAN::ALTIMA::{2016,2017,2018,ALL_YEARS}::AIR BAGS`
   take Cass; Rogue/Frontier AIR BAGS must not.
4. Optional: expand `COMPONENT_KEYWORDS["AIR BAGS"]` with `OCS` /
   `occupant classification` if CL search misses Cass on airbag-only terms —
   **not** done here (minimal change).

### Suggested prod SQL (only if re-check cannot run; Jimmy runs — not from box)

```sql
-- Clear any Cass mis-pin on Rogue/Frontier AIR BAGS
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
 WHERE make = 'NISSAN'
   AND model IN ('ROGUE', 'FRONTIER')
   AND component = 'AIR BAGS'
   AND class_action_case_name ILIKE '%Cass%';

-- Then: python scripts/check_filings.py --recheck-days 0
-- Prefer CL re-check to attach Cass to Altima AIR BAGS with:
--   url https://www.courtlistener.com/docket/74842719/cass-v-nissan-north-america-inc/
--   case 5:26-cv-05613, filed 2026-09-23, status pending
```
