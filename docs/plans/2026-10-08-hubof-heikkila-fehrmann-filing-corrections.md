# Fehrmann / Hubof / Heikkila filing corrections

**Date:** 2026-10-08
**Status:** code on PR; no migration; Lane A only (no human_label / invest_score)
**Pattern:** same as PR #14 (Cass) and PR #5 (`filing_corrections.py` CaptionRule)

## Filings (Signal Searcher, CL verified, complaint stage, all pending)

1. **Fehrmann v. General Motors LLC** (brake loss, priority). E.D. Pa. `2:26-cv-07669`,
   filed **2026-10-06**.
   CL: https://www.courtlistener.com/docket/74924532/fehrmann-v-general-motors-llc/
   Defect: 2025 Chevrolet Traverse / GMC Acadia / Buick Enclave / Chevrolet Colorado /
   GMC Canyon master brake cylinder. Loss of braking.
2. **Hubof v. General Motors, LLC**. E.D. Mich. `2:26-cv-13622`, filed **2026-09-24**.
   CL: https://www.courtlistener.com/docket/74843881/hubof-v-general-motors-llc/
   Defect: 2024-2026 Silverado / Sierra 2500HD/3500HD 6.6L Duramax cracked oil cooler.
3. **Heikkila v. BMW of North America, LLC**. D.N.J. `2:26-cv-12932`, filed **2026-10-02**.
   CL: https://www.courtlistener.com/docket/74910947/heikkila-v-bmw-of-north-america-llc/
   Defect: 2018-2025 BMW G-chassis A/C evaporator corrosion (~1M vehicles).

## Cluster key patterns

Cluster key = `{MAKE}::{MODEL}::{YEAR|ALL_YEARS}::{COMPONENT}`.

| Rule | Component bucket | Intended keys | same_defect |
|---|---|---|---|
| `fehrmann_gm_master_brake_cylinder` | `BRAKES` | `CHEVROLET::COLORADO::*::BRAKES`, `GMC::CANYON::*::BRAKES` (+ Traverse / Acadia / Enclave if ever tracked) | True |
| `hubof_gm_duramax_oil_cooler` | `ENGINE` (`ENGINE AND ENGINE COOLING` normalizes here) | `CHEVROLET::SILVERADO[ 2500/3500/HD]::*::ENGINE`, `GMC::SIERRA[ 2500/3500/HD]::*::ENGINE` | False |
| `heikkila_bmw_ac_evaporator` | `OTHER`, `ELECTRICAL` | `BMW::{G-chassis model}::*::OTHER` / `ELECTRICAL` | False |

Why the same_defect choices:

- **Fehrmann:** Scout-verified, caption will not name brakes. Forced True like Cass / Thieme.
  Gap: CaptionRule has no model-year gate. Older Colorado / Canyon BRAKES keys
  (2015-2024, prior generation) also accept the hit and would be hidden. A year gate is
  a separate change.
- **Hubof:** base `SILVERADO` / `SIERRA` keys mix 1500 and HD. The 1500 6.2L L87 engine
  track lives on the same ENGINE key. Forced False (Norberg precedent) so Hubof does not
  hide it. HD-specific model strings are also allowed in case flat-file import stored
  them raw.
- **Heikkila:** there is no A/C bucket. NHTSA files evaporator complaints as
  `UNKNOWN OR OTHER` / `VISIBILITY` (to `OTHER`) and sometimes `ELECTRICAL SYSTEM`.
  Both buckets are broad, so vehicle-only.

## TRACKED_VEHICLES coverage

Two different gaps. Do not mix them up.

- **(a) Not in TRACKED_VEHICLES:** no cluster will ever exist until the model is added.
- **(b) Tracked, no cluster yet:** prod data is stale (newest complaint 2026-05-04, NHTSA
  parser broken). Tag: **recheck after #16**.

| Named model | Status |
|---|---|
| Chevrolet Colorado (2025) | Tracked. (b) recheck after #16 |
| GMC Canyon (2025) | Tracked. (b) recheck after #16 |
| Chevrolet Traverse | (a) not tracked |
| GMC Acadia | (a) not tracked |
| Buick Enclave | (a) not tracked. BUICK is not a tracked make and has no MANUFACTURER_ALIASES entry |
| Silverado / Sierra 2500HD/3500HD (2024-2025) | Tracked via SILVERADO / SIERRA prefix. (b) recheck after #16 |
| Silverado / Sierra HD 2026 | Model year 2026 is outside MODEL_YEARS (2015-2025) for API ingest |
| BMW (all models) | (a) not tracked. BMW is not in TRACKED_VEHICLES |

Extra Heikkila gap: `check_filings` skips `OTHER` clusters (empty `COMPONENT_KEYWORDS`),
so the rule is inert until BMW is tracked and A/C has search terms.

Prod row check: the box could not reach the prod Postgres proxy (outbound TCP to the
Railway proxy port timed out). Live keys still need a read-only confirm from a machine
that can reach prod.

## Jimmy / ops still needed

1. Merge this PR only on Jimmy's exact yes. Deploy.
2. Land PR #16 (NHTSA parser) and let ingest refill 2025-2026 complaints.
3. Set `COURTLISTENER_API_TOKEN` on Railway (currently missing).
4. `python scripts/check_filings.py --recheck-days 0`. Flags fill only after this.
5. Confirm Fehrmann sits on Colorado / Canyon BRAKES only, Hubof on Silverado / Sierra
   ENGINE only, and nothing lands on Silverado BRAKES or 1500-only keys.
