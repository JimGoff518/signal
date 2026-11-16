# Fehrmann filing correction + model-year guard

**Date:** 2026-10-08
**Status:** code on PR #17; no migration; Lane A only (no human_label / invest_score)
**Pattern:** same as PR #14 (Cass) and PR #5 (`filing_corrections.py` CaptionRule)

## Filing (Signal Searcher, CL verified, complaint stage, pending)

**Fehrmann v. General Motors LLC** (brake loss, priority). E.D. Pa. `2:26-cv-07669`,
filed **2026-10-06**.

- CL: https://www.courtlistener.com/docket/74924532/fehrmann-v-general-motors-llc/
- Defect: 2025 Chevrolet Traverse / GMC Acadia / Buick Enclave / Chevrolet Colorado /
  GMC Canyon master brake cylinder. Loss of braking.

## Rule

`fehrmann_gm_master_brake_cylinder`:

- Makes: CHEVROLET, GMC, BUICK.
- Models: TRAVERSE, ACADIA, ENCLAVE, COLORADO, COLORADO ZR2 BISON, CANYON, CANYON AT4X AEV.
- Component: `BRAKES` only.
- `allow_years={2025}`.
- `same_defect=True` on 2025 keys. Vehicle-only on ALL_YEARS keys.

Intended keys: `CHEVROLET::COLORADO::2025::BRAKES`, `GMC::CANYON::2025::BRAKES`
(same defect), and `CHEVROLET::COLORADO::ALL_YEARS::BRAKES`,
`GMC::CANYON::ALL_YEARS::BRAKES` (vehicle-only).

## Model-year guard (new)

`CaptionRule.allow_years: frozenset[int] | None = None`.

- Per-year cluster outside `allow_years`: the hit is rejected inside
  `find_class_action`, the same way a wrong model or component is. The loop moves on to
  the next plausible hit. If none is left, the cluster is "no match", exactly as a
  model/component rejection is today.
- ALL_YEARS cluster (`model_year IS NULL` / `is_multi_year`): the hit may attach, but
  `same_defect_override(..., all_years=True)` returns False. The aggregate mixes in-range
  and out-of-range years, so it must not be hidden.
- The CourtListener search has no year. The guard runs per hit. `run_check_filings` now
  SELECTs `model_year` and `is_multi_year` and passes them through.
- Rules without `allow_years` behave as before.

Years set:

| Rule | allow_years |
|---|---|
| Fehrmann | {2025} |
| Cass | {2016, 2017, 2018} |

This also tightens Cass. Before, Cass attached to every Altima AIR BAGS year. Now
2015 and 2019+ Altima AIR BAGS keys reject it, and the Altima ALL_YEARS key goes
vehicle-only.

## Dropped from this PR

- **Hubof v. GM (Duramax oil cooler).** Signal cannot tell 2500HD/3500HD from 1500 on
  the SILVERADO / SIERRA ENGINE clusters. The 1500 engine track shares those keys.
- **Heikkila v. BMW (A/C evaporator).** BMW is not in TRACKED_VEHICLES. There is no A/C
  bucket (evaporator complaints normalize to OTHER, which check_filings skips).

Both stay as notes in the Searcher's file, not in code.

## TRACKED_VEHICLES coverage

- **(a) Not in TRACKED_VEHICLES:** Traverse, Acadia, Enclave. BUICK is not a tracked make
  and has no MANUFACTURER_ALIASES entry.
- **(b) Tracked, no cluster yet:** Colorado and Canyon 2025. Prod data is stale (newest
  complaint 2026-05-04). Recheck after #16.

Prod row check: the box could not reach the prod Postgres proxy (outbound TCP timed out).
Live keys still need a read-only confirm from a machine that can reach prod.

## Jimmy / ops still needed

1. Merge only on Jimmy's exact yes. Deploy.
2. Land PR #16 (NHTSA parser) and let ingest refill 2025-2026 complaints.
3. Set `COURTLISTENER_API_TOKEN` on Railway (currently missing).
4. `python scripts/check_filings.py --recheck-days 0`. Flags fill only after this.
5. Confirm Fehrmann sits on Colorado / Canyon 2025 BRAKES (same defect) and ALL_YEARS
   (vehicle-only) only. Confirm Cass left 2015 and 2019+ Altima keys.
