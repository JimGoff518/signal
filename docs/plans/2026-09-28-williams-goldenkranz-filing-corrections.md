# Williams CVT + Goldenkranz ICCU filing corrections

**Date:** 2026-09-28
**Status:** code on stacked PR (depends on #4 `filing_corrections.py`); no migration
**Depends on:** https://github.com/JimGoff518/signal/pull/4 (Norberg/Thieme/O'Connor)

## New filings (Scout / Jev)

1. **Williams v. General Motors LLC** — FILED — D. Del. `1:26-cv-01162`, filed 2026-09-15.
   - Defect: VT40/TR690 CVT (clutch regulator / valve body) on 2019–2025 Malibu,
     2021–2025 Trailblazer, 2024+ Equinox / Terrain.
   - Links:
     - https://www.classaction.org/news/general-motors-lawsuit-alleges-certain-chevy-gmc-models-plagued-by-defective-transmission-components
     - https://www.courtlistener.com/docket/74797847/williams-v-general-motors-llc/
   - **Keep SEPARATE from Barba GM 8-speed.**

2. **Goldenkranz v. Hyundai Motor America** — FILED — W.D. Wash. `2:26-cv-03581`, filed 2026-09-23.
   - Defect: twice-recalled ICCU → 12V drain / loss of drive (Ioniq 5/6/9, EV6/EV9,
     Genesis GV60/GV70/GV80 Electrified).
   - Hagens Berman press 2026-09-24.
   - Links:
     - https://www.courtlistener.com/docket/74842006/goldenkranz-v-hyundai-motor-america/
     - https://www.financialcontent.com/article/bizwire-2026-9-24-hagens-berman-hyundai-kia-and-genesis-ev-owners-sue-over-twice-recalled-iccu-linked-to-drained-12-volt-batteries-and-loss-of-vehicle-power
   - Related older (not this rule): Young v. Hyundai Kefico, D.N.J. `3:26-cv-04198` (Apr 2026).

O'Connor `cert_denied` remains in open PR #4 — no change this sweep.

## Cluster key patterns

Cluster key = `{MAKE}::{MODEL}::{YEAR|ALL_YEARS}::{COMPONENT}`.

| Filing | Component bucket | Intended keys (examples) |
|---|---|---|
| Williams CVT | `POWER TRAIN` (`TRANSMISSION` normalizes here) | `CHEVROLET::EQUINOX::*::POWER TRAIN`, `CHEVROLET::MALIBU::*::POWER TRAIN`, `CHEVROLET::TRAILBLAZER::*::POWER TRAIN`, `GMC::TERRAIN::*::POWER TRAIN` |
| Barba 8-speed | `POWER TRAIN` | `CHEVROLET::SILVERADO::*::POWER TRAIN`, `…::SUBURBAN/TAHOE/COLORADO::…`, `GMC::SIERRA/YUKON/CANYON::*::POWER TRAIN` |
| Goldenkranz ICCU | `ELECTRICAL` | `HYUNDAI::IONIQ 5::*::ELECTRICAL` (and Ioniq 6/9), `KIA::EV6/EV9::*::ELECTRICAL`, `GENESIS::GV60/GV70/GV80::*::ELECTRICAL` |

## How Barba separation is enforced

- **Williams** `CaptionRule`: `allow_models={MALIBU,TRAILBLAZER,EQUINOX,TERRAIN}` only.
- **Barba** `CaptionRule`: `allow_models={SILVERADO,SIERRA,TAHOE,SUBURBAN,YUKON,COLORADO,CANYON}` only.
- Disjoint allow-lists → Williams cannot pin truck/SUV POWER TRAIN; Barba cannot pin Equinox/Terrain/Malibu/Trailblazer.
- Caption model tokens + `MODEL_SIBLINGS` also reject Suburban-style collapse when the Williams caption names Equinox/Malibu/etc.

## TRACKED_VEHICLES coverage (gaps)

From `signalwarn/ingestion.py` Phase 1 list:

| Named model | In TRACKED_VEHICLES? |
|---|---|
| Chevrolet Equinox | **YES** — only live Williams attach surface today |
| Chevrolet Malibu | **NO** |
| Chevrolet Trailblazer | **NO** |
| GMC Terrain | **NO** |
| Hyundai Ioniq 5/6/9 | **NO** (Hyundai tracks Tucson/Santa Fe/Elantra only) |
| Kia EV6 / EV9 | **NO** (Kia tracks Telluride/Sorento/Sportage only) |
| Genesis GV60/GV70/GV80 | **NO** (Genesis not a tracked make; no `MANUFACTURER_ALIASES` entry) |

Do **not** invent vehicle tracks in this PR. Rules still reject Goldenkranz on Tucson/Telluride/etc. so CourtListener cannot false-attach when those clusters are checked. Kia plausibility still requires "kia" in the caption (`MANUFACTURER_ALIASES` deliberately does not cross-list Hyundai↔Kia) — document for Jimmy if Kia EV clusters are added later.

## What this PR does (no schema migration)

Extends `signalwarn/filing_corrections.py` (same pattern as PR #4):

- CVT sibling union on Equinox/Terrain (keeps Thieme Envision).
- Caption tokens for Malibu/Trailblazer + Ioniq/EV/GV models.
- `CaptionRule.allow_make` may be a `frozenset` (Goldenkranz / Williams / Barba multi-make).
- New rules: `williams_gm_cvt`, `barba_gm_8speed`, `goldenkranz_iccu`.

## Jimmy still needed

1. Merge PR #4 first (or merge the stack), then this PR; deploy.
2. Re-run `python scripts/check_filings.py --matched-only` (or `--recheck-days 0`) so CourtListener re-attachments hit the new rules. Prefer this over hand SQL when GoffLaw/prod is reachable.
3. Confirm live prod captions for Williams / Barba / Goldenkranz match allow-lists (Barba model list is the tracked truck/SUV surface — adjust if live caption names a different set).
4. Optional TRACKED_VEHICLES expansion (Jimmy sign-off): Malibu, Trailblazer, Terrain, Ioniq*, EV6/EV9, Genesis — **not** done here.
5. Optional: Genesis `MANUFACTURER_ALIASES` + Hyundai↔Kia cross-list for Goldenkranz on Kia clusters — deliberate non-change today.

### Suggested prod SQL (only if re-check cannot run; Jimmy runs — not from box)

```sql
-- Clear any Williams mis-pin on truck/SUV POWER TRAIN (Barba surface)
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
   AND model IN ('SILVERADO', 'SIERRA', 'TAHOE', 'SUBURBAN', 'YUKON', 'COLORADO', 'CANYON')
   AND component = 'POWER TRAIN'
   AND class_action_case_name ILIKE '%Williams%';

-- Clear any Barba mis-pin on Williams CVT models
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
   AND model IN ('EQUINOX', 'MALIBU', 'TRAILBLAZER', 'TERRAIN')
   AND component = 'POWER TRAIN'
   AND class_action_case_name ILIKE '%Barba%';

-- Clear Goldenkranz false-attach on tracked ICE Hyundai/Kia ELECTRICAL
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
 WHERE make IN ('HYUNDAI', 'KIA')
   AND model IN ('TUCSON', 'SANTA FE', 'ELANTRA', 'TELLURIDE', 'SORENTO', 'SPORTAGE')
   AND component = 'ELECTRICAL'
   AND class_action_case_name ILIKE '%Goldenkranz%';

-- Then: python scripts/check_filings.py --recheck-days 0
-- (or at least re-check Equinox POWER TRAIN) and rescore if needed.
```
