# SIGNAL — Project Plan & Goals
### Goff Law PLLC | Owner: Jim Goff | Build Partner: Alex Goff
### Started: May 5, 2026

---

## WHAT SIGNAL IS

A real-time complaint intelligence dashboard that monitors public government databases and online communities to identify emerging vehicle defect patterns — before they become known litigation — so Goff Law can advertise to affected consumers and sign plaintiffs before any competing firm knows the case exists.

**Primary legal lens:** consumer class action + product liability (with mass tort as a secondary lens). The scoring algorithm reflects this — numerosity, commonality, manufacturer knowledge, and economic-harm signals are weighted ahead of mass-tort severity escalators (death/injury), because severe individual injury defeats Rule 23 predominance and pushes cases away from class treatment.

**One sentence:** SIGNAL finds the next GM ignition switch in 2006, not 2014 — *and* the next quietly-spreading transmission-shudder defect three years before any class action is filed.

---

## THE CORE PROBLEM IT SOLVES

Every PI mass tort marketing company in the country is reactive. They wait for a case to be publicly filed, then sell the same leads to 50 competing firms at $500–2,000 per retainer.

SIGNAL is predictive. It reads public complaint data early, surfaces emerging defect patterns algorithmically, and gives Goff Law a first-mover window to advertise and sign plaintiffs before national firms even know the case exists.

---

## SUCCESS METRICS — HOW WE KNOW IT'S WORKING

### 90-Day Goal (Phase 1 MVP)
- [x] **Dashboard live** at https://signal-mtw.up.railway.app — Railway cron service (`signal`) deployed 2026-05-09, runs `python scripts/run_ingestion.py` every 3 days at 02:00 CT (`0 7 */3 * *` UTC).
- [x] **At least 10 active complaint clusters scored and classified** — landed at **17,448 clusters** after the historical seed on 2026-05-06.
- [x] **At least 1 cluster rated HOT or CRITICAL** — there are **2,696** (1,451 CRITICAL + 1,245 HOT). Viable legal theory selection is the next step; use `python scripts/top_clusters.py` to rank by tort signal.
- [ ] Jim reviews dashboard at least 3x per week
- [ ] First targeted ad campaign launched to affected vehicle owners in Texas

### 6-Month Goal
- [ ] First Texas plaintiff signed from a SIGNAL-identified case
- [ ] First referral or co-counsel arrangement with a national mass tort firm
- [ ] Reddit and CarComplaints.com added as Phase 2 data sources
- [ ] Get Goff content calendar fed directly from SIGNAL clusters

### 12-Month Goal
- [ ] SIGNAL has identified at least 3 actionable cases
- [ ] At least 1 case in active litigation or referral fee agreement signed
- [ ] Decision made: internal tool only OR productize for other PI firms
- [ ] If productizing: first external law firm signed as beta customer

---

## ROLES & RESPONSIBILITIES

| Who | Role | Responsibility |
|---|---|---|
| **Jim Goff** | Product Owner | Reviews deliverables, approves classification logic, makes legal calls on viability, runs ads once cases are flagged |
| **Alex Goff** | Build Lead | Owns the technical build, stack decisions, timeline, and deployment |
| **Alex's Team** | Developers | Build pipeline, scoring engine, dashboard per the technical spec |
| **Claude** | Strategic Advisor | Spec writing, algorithm design, prompt engineering, ongoing strategic planning |

**Jim's time commitment:** 2 hours per week maximum during build phase. Review deliverables. Answer questions. Do not manage the build.

---

## PHASED ROADMAP

### Phase 1 — Core MVP (Now → Day 90)
**Goal:** Working pipeline + scoring + dashboard

- NHTSA API data pipeline (daily ingestion)
- Historical data import (2015–present)
- Clustering engine (make/model/year/component)
- Scoring algorithm (0–100 with severity escalators)
- Claude viability memo generation
- Web dashboard (cluster table + detail pages)
- Email alerts (daily digest + instant death alert)
- Single user login

**Hand off to Alex:** SIGNAL_README.md + SIGNAL_TECHNICAL_SPEC.md — Done

---

### Phase 2 — Expand Sources (Day 90 → Day 180)
**Goal:** Add community corroboration layer

- Reddit API integration (r/MechanicAdvice, brand-specific subs)
- CarComplaints.com data
- Texas geographic filter on NHTSA complaints
- First targeted ad campaign from flagged cluster

---

### Phase 3 — Legal Signals + Consumer Products (Day 180 → Day 270)
**Goal:** Add a litigation-signal layer to sharpen "did the manufacturer know?" — and expand beyond automotive.

**Legal data layer (sharpen what we already have):**
- **TSB cross-referencing** — every TSB zip is already on disk in `data/raw/`. When a manufacturer issues a TSB on a defect but no recall, AND complaints are rising, that's the smoking-gun pattern every mass tort hinges on. Add a `tsb_known` flag to each cluster and a TSB-without-recall scoring escalator.
- **PACER / CourtListener integration** — pull early-stage federal product-liability filings by manufacturer/component to detect when other firms are starting to nibble (pre-MDL window). Use CourtListener's free RECAP-cached docs first; fall back to PACER for the rest.
- **JPML watchlist** — RSS-poll pending motions to consolidate (Multidistrict Litigation panel). Once a motion is pending, the case is publicly known but most firms aren't watching the JPML docket.
- **State court docket monitoring** — re:SearchTX for Texas filings (priority — our forum); LexisNexis CourtLink for nationwide coverage.
- **CAFA notices** — settlements over $5M trigger AG notification; useful as lagging confirmation that a pattern materialized.

**Consumer products:**
- CPSC SaferProducts.gov data pipeline
- Same scoring architecture applied to consumer products
- Separate dashboard section for non-vehicle defects

**Lower priority for this phase:** IIHS crash data, EPA enforcement actions, SEC 10-K litigation disclosures.

**Evaluate (don't adopt as core):** [LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research) — open-source AI research agent (LangGraph + multi-engine search, MIT licensed, 5.5K stars, very active). **Not a fit for the core SIGNAL pipeline** because (a) most of its integrated sources are academic (arXiv, PubMed) which is the wrong domain, (b) it adds heavyweight framework dependencies (LangGraph, multiple LLM clients, SQLCipher) when our viability-memo flow is intentionally a tight Claude prompt, and (c) SIGNAL needs *targeted* legal feeds (PACER, JPML, TSBs), not general web research. **Where it could earn a place:** as an optional "deep dive" button on a HOT cluster — Jim clicks once on a high-priority cluster, the agent runs an adaptive research pass across web/news/court records and produces a richer briefing PDF. Bolt-on, not embedded.

---

### Phase 4 — Productize Decision (Day 270+)
**Goal:** Decide whether to commercialize

- Internal performance review: how many cases found? How many signed?
- If viable: build multi-tenant SaaS architecture
- If not: keep as internal proprietary tool
- Potential market: solo/small PI firms nationally at $300–500/month

---

## DATA SOURCES BY PHASE

| Source | Phase | Cost | Data Type |
|---|---|---|---|
| NHTSA API | 1 | Free | Structured vehicle complaints |
| Reddit API | 2 | Free | Unstructured community posts |
| CarComplaints.com | 2 | Free scrape | Aggregated owner complaints |
| CPSC SaferProducts.gov | 3 | Free | Structured consumer product complaints |
| Twitter/X | Deprioritized | $100+/mo | Not worth it yet |
| Facebook | Not viable | — | No public API |

---

## THE ALGORITHM — QUICK REFERENCE

Every complaint cluster scores 0–100:

```
BASE           +1 per complaint (capped at 30)
VELOCITY       2x–3x multiplier if complaints doubled/tripled in 30 days
INJURY         +20 points
DEATH          +50 points (instant CRITICAL review)
CRASH          +10 points
FIRE           +15 points
MULTI-YEAR     +10 points (systemic defect signal)
INVESTIGATION  +20 points (NHTSA opened formal probe)
RECALL ISSUED  +25 points
ALREADY FILED  -30 points (want to be EARLY)
```

**Classifications:**
- 🔴 90–100: CRITICAL
- 🟠 70–89: HOT
- 🟡 50–69: WATCH
- 🟢 25–49: MONITOR
- ⚪ 0–24: NOISE (hidden)

---

## MONETIZATION SEQUENCE

```
Month 1–3    Dashboard live. Start reading clusters.

Month 3–6    Run first Facebook/Google ads targeting owners
             of flagged vehicles in Texas.

Month 6–9    Sign first plaintiffs. Establish first referral
             or co-counsel deal with national mass tort firm.

Month 9–12   Evaluate: is this worth selling to other PI firms?

Month 12+    If yes: productize. If no: keep as proprietary edge.
```

**Revenue layers:**
1. **Direct clients** — ad campaigns to affected vehicle owners
2. **Referral fees** — 25–40% of attorney fees (Texas Rule 1.04 compliant)
3. **Co-counsel** — bring signed plaintiffs + viability memo to national firms
4. **Get Goff content** — every cluster is a YouTube video topic
5. **SaaS (long term)** — license to other solo PI firms nationally

---

## COMPETITIVE CONTEXT

| Company | What They Do | Why SIGNAL Is Different |
|---|---|---|
| Darrow AI | Broad class action scanner | Enterprise only ($10K–$1M+/yr). Not vehicle-focused. |
| Lead gen companies | Sell leads after cases are public | Reactive. Same leads to 50 firms. |
| Large mass tort firms | Manual docket monitoring | No algorithm. No early detection. |
| **SIGNAL** | Algorithmic early warning, vehicle-focused, built for solo PI | First mover. Proprietary. Yours. |

---

## PROOF OF CONCEPT — GM IGNITION SWITCH

The signal was in NHTSA data **in 2006.**
The first class action wasn't filed until **2014.**
The recall covered **2.6 million vehicles.**
Settlements exceeded **$900 million.**

SIGNAL would have classified this HOT in 2006 — **8 years before** the first firm filed.

---

## DOCUMENTS

| Document | Purpose | Status |
|---|---|---|
| SIGNAL_README.md | Business context, algorithm, monetization | ✅ Complete |
| SIGNAL_TECHNICAL_SPEC.md | Developer build guide, API docs, database schema | ✅ Complete |
| SIGNAL_PLAN_AND_GOALS.md | This document — project goals and roadmap | ✅ Complete |

**No more planning documents.** Next output is working code.

---

## THE UNCOMFORTABLE TRUTH (KEEP THIS IN THE DOCUMENT)

SIGNAL is only valuable if Jim actually uses it to sign cases — not just to read interesting complaint data.

The tool finds the opportunity. Jim still has to:
- Launch the ad campaign
- Answer the intake calls
- Make the referral calls to national firms
- Show up and do the human work

SIGNAL removes the information gap. It does not remove the execution requirement.

---

*Last Updated: May 5, 2026*
*Goff Law PLLC — Confidential*
