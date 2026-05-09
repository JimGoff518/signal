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
- **PACER / CourtListener integration** *(in progress 2026-05-09)* — pull early-stage federal product-liability filings by manufacturer/component to detect when other firms are starting to nibble (pre-MDL window). Use CourtListener's free RECAP-cached docs first; fall back to PACER for the rest. Specifically:
  - **Phase 3a — Filing detection** *(building now)*: for every WATCH+ cluster, query CourtListener for matching dockets containing the make/model/component. If a match exists, populate `clusters.class_action_filed = TRUE` and `class_action_url`, which triggers the -30 penalty in scoring. Goal: deduplicate the dashboard so already-lawyered cases drop tier and only virgin territory floats to the top.
  - **Phase 3b — Active monitoring**: poll CourtListener's RECAP feed daily for new product-liability complaints in target federal districts (E.D. Tex., S.D. Tex., N.D. Cal., D.N.J., E.D. Mo., E.D. Pa., S.D. Fla.). Cross-reference incoming defendant names against tracked manufacturers; auto-flag clusters when a new filing appears.
  - **Phase 3c — Litigation trends + opinions (Jim's ask 2026-05-09)**: pull recent **class-certification orders** from CourtListener's opinion corpus and run them through Claude to extract: which products/components are being certified, which courts are friendly to plaintiffs, what theories survive *Daubert* and *Comcast*, what damages models are working. Feed this back into the viability memo prompt as live precedent context. Use CourtListener's `/api/rest/v4/search/?type=o` for opinion text.
  - **Phase 3d — PACER paid fallback** *(later)*: for filings not in RECAP, fetch the docket sheet from PACER (~$0.10/page) only for HOT+ clusters where filing status materially affects strategy. Capped monthly spend.
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

## CALIBRATION — 10-YEAR BACKTEST (added 2026-05-09)

**Premise:** 10 years of NHTSA history is now in the DB. CourtListener integration (Phase 3a) will tag each historical cluster with whether a class action was eventually filed. That gives us a **labeled training set** — every cluster, with both its precursor signals (volume, velocity, multi-year, recall, deaths) AND its eventual outcome (filed / not filed / certified / settled / lost).

**Use that data to answer:**
- Which signal combinations historically led to **certified** class actions (not just filed)?
- Which led to **settlements** vs. summary judgment for the defendant?
- What was the **average lead time** between SIGNAL-detectable signal and first filing? (8 years for GM ignition switch — what's the median across the dataset?)
- Are there **defects SIGNAL would have flagged** that nobody filed against — because the firms didn't see the pattern, or because the case was actually weak?
- For the candidates SIGNAL surfaces today, what does the historical base rate of success look like for that signal pattern?

**How:**
1. After Phase 3a tags historical clusters, build `scripts/backtest_scoring.py` that joins cluster scores against filed/not-filed labels.
2. Compute precision/recall at each score threshold (e.g., "85% of clusters scoring >70 had a class action filed within 5 years").
3. Identify weight imbalances — if multi-year is over- or under-weighted relative to historical filing correlation, recalibrate.
4. Optional v2: train a simple gradient-boosted model on the labeled set as an alternate scoring lens; ensemble or A/B with the rule-based score.

**Why this matters:** the current scoring weights are educated guesses informed by Rule 23 doctrine. Backtesting against actual filings tells us which signals were predictive in practice and which were noise. **This converts SIGNAL from "Jim's intuition encoded as Python" into an empirically calibrated scoring engine** — and gives Jim defensible numbers for any future SaaS pitch ("our scoring achieved 80% precision on a 10-year historical backtest of 17K clusters against 200+ filed class actions").

---

## DEBUG QUEUE — KNOWN ISSUES (added 2026-05-09)

Bugs and rough edges captured during dogfooding. Triage by impact, fix in priority order.

**High impact (block real work):**
- [ ] **`class_action_filed` flag never populated** — schema column exists and the -30 penalty fires correctly *if set*, but no code populates it. Solved by Phase 3a CourtListener integration (in progress).
- [ ] **`tsb_known` flag never populated** — TSB zips are on disk in `data/raw/`, `scripts/tsb_smoking_guns.py` exists but has never been run against prod. Once it runs, we still need to wire the flag into the cluster row so scoring can use it.
- [ ] **Component "OTHER" bucket inflates false positives** — the Kia Sorento "OTHER" cluster surfaced today with score 100. "OTHER" means NHTSA's free-text didn't normalize cleanly, so commonality is weaker than the score implies. Either filter "OTHER" from dashboard surfacing, penalize "OTHER" in scoring, or improve `signalwarn.normalize` to bucket more aggressively.

**Medium impact:**
- [ ] **Email digest may not have been arriving** — the cron service was running with `gofflawpllc.com` env var values (typo), and Resend's verified-domain status for `gofflawdfw.com` is unknown. Issue #1 (Resend → Gmail SMTP swap, assigned to Jack) should fix this end to end. In the meantime, check the cron service logs for "RESEND_API_KEY not set" or 4xx Resend errors.
- [ ] **Dashboard "12-mo trend" sparkline can mislead** — sparklines are normalized per-cluster (each cluster's own max), so a cluster with 3 complaints/month looks just as "spiky" as one with 300. Consider a global normalization or a tooltip showing absolute counts.
- [ ] **`historical_import.py --skip-complaints` (recall + investigation flag application)** — never ran post-bulk-import, so recall_issued / nhtsa_investigation_open are likely incomplete on many clusters. Should be re-run.

**Low impact / polish:**
- [ ] **Some HOT/CRITICAL clusters from pre-rebalance are now MONITOR** — dashboard's score sort handles this, but the daily-digest email's "newly HOT" detection might fire off-cycle for a few weeks as scores settle.
- [ ] **Dashboard mobile layout below 1280px** drops the sparkline and Inj/Dth/Δ30d columns — readable but information-dense panels collapse oddly on phones.
- [ ] **No cluster-level audit log** — when a cluster's score changes (e.g., from a rebalance), we lose the prior value. A `score_history` table would let us show "this cluster jumped from 60 → 95 on 2026-05-09 (rebalance)".

---

## DALLAS DOCKET — INTERFACE FUN ITEMS (added 2026-05-09)

Branding hook: "Dallas Docket — Goff Law's complaint scanner" (the firm's home turf is North Texas; "docket" is the legal-system metaphor). These are *intentional* delight features — tasteful, on-brand, opt-in or hidden by default so client-facing screens stay professional. None of these are required; they're a backlog of fun.

**Stats / status flair:**
- [ ] **"Stat of the Day"** banner — rotating headline pulled from real data: "1,247 NHTSA complaints filed about your tracked vehicles this week." Updates daily.
- [ ] **Cluster-of-the-day spotlight card** — randomly highlights one HOT or CRITICAL cluster on dashboard load with a "did you know?" framing. Pulls Jim's attention to clusters he hasn't reviewed.
- [ ] **"Streak counter"** — tracks how many consecutive days Jim opened the dashboard. Subtle, in the footer. Encourages the Phase 1 milestone of "Jim reviews 3x/week."

**Audio / animation (sparingly, off by default):**
- [ ] **Critical-alert chime** — a soft, distinctive sound when a new CRITICAL cluster appears in the feed. Off by default; toggleable. Like a Bloomberg terminal but quieter.
- [ ] **Score-bump animation** — when a cluster's score increases week-over-week, briefly highlight the row with a green pulse. When it drops, a red pulse. Communicates motion at a glance.

**Easter eggs (back-of-the-bus, no client-facing risk):**
- [ ] **Konami code → "Dallas Docket: Rush Hour" retro mode** — the previously-removed easter egg. If Jim wants it back, the matcher is robust now (per the 2026-05-09 rebuild). 75 lines of CSS/JS, no client-facing risk because it's strictly opt-in via the cheat code. *Note: removed on 2026-05-09 per Jim's call; back in scope as an explicit fun-feature ask.*
- [ ] **Footer fortune-cookie tort aphorism** — rotating one-liner: "*Res ipsa loquitur* — the thing speaks for itself." or "8 years from signal to recall in the GM ignition switch case. Watch the multi-year aggregates." Visible only on the dashboard footer; ignorable.
- [ ] **"This day in tort history"** — micro-card showing notable mass-tort milestones (Roundup verdicts, opioid settlements, etc) on the date. Pulled from a static seed list initially; could later integrate with PACER for live milestones.

**Gamification (handle with care — could feel cringe):**
- [ ] **Achievement badges** — "First signed plaintiff from a SIGNAL cluster," "First $1M settlement traced to a SIGNAL flag," "First Get Goff video derived from a cluster." Internal milestones, not visible to clients.
- [ ] **"Ad campaign tracker"** — when Jim launches a Texas ad campaign tied to a flagged cluster, that cluster gets a small 📢 icon. Click → see cost-per-lead and signed-retainer count for that cluster. (Requires ad-platform integration; deferred.)

**Pure UI polish that lifts the vibe:**
- [ ] **Manufacturer logos** in cluster rows — the `car_logos.zip` asset is already on local disk per memory. Drop in, brighten the dashboard significantly.
- [ ] **Bloomberg-style headline ticker** at the top of the dashboard — the LIVE strip already exists; could be expanded with rotating recent CRITICAL events ("CHEVY EQUINOX ENGINE — 12 NEW COMPLAINTS THIS WEEK").
- [ ] **Dark / light / "courthouse" theme toggle** — the courthouse theme being a high-contrast print look (white background, navy accents, serif headings) for screenshots Jim wants to send to co-counsel.

**Note:** these are all explicitly Jim-requested. Saved feedback memory `feedback_no_unrequested_features` still applies for *unsolicited* additions — don't ship anything in this section without Jim's explicit go-ahead on that specific item.

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

## THE ALGORITHM — QUICK REFERENCE (rebalanced 2026-05-09 for class-action lens)

Every complaint cluster scores 0–100:

```
NUMEROSITY     +1 per complaint (capped at 50) — Rule 23(a)(1)
VELOCITY       2x–3x multiplier if 30-day count ≥ 0.5 / 0.66 of total
COMMONALITY    +20 if multi-year systemic defect — Rule 23(a)(2)
KNOWLEDGE      +25 if NHTSA investigation open
               +30 if recall issued
SEVERITY       +10 if any injury  (mass-tort secondary lens)
               +20 if any death   (mass-tort secondary lens)
               +5  if any crash
               +10 if any fire
ALREADY FILED  -30 (want to be EARLY)
```

Numerosity / commonality / manufacturer-knowledge dominate; severity escalators are kept but reduced because severe individual injury defeats Rule 23 predominance and pushes cases toward mass tort instead of class. See `docs/SIGNAL_TECHNICAL_SPEC.md §7.2` and `tests/test_scoring.py` archetype tests.

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
