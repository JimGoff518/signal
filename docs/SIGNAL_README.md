# SIGNAL — Class Action / Product Liability Early Warning System
### Goff Law PLLC | Confidential Internal Planning Document
### Created: March 27, 2026 | Lens reframed: May 9, 2026

---

## EXECUTIVE SUMMARY

**SIGNAL** is a real-time consumer sentiment intelligence platform that monitors public complaint databases and online communities to identify emerging vehicle defect and consumer product patterns — before they become known litigation.

The core insight: the data to identify the next GM ignition switch, the next Nissan Rogue engine failure, or the next Takata airbag disaster exists in public databases **years before** the first class action is filed. No PI firm has built an automated system to read that data early, target affected consumers with advertising, and sign plaintiffs before national firms even know the case exists.

**SIGNAL** closes that gap.

---

## LITIGATION LENS — UPDATED 2026-05-09

The original framing of this document positioned SIGNAL as a **mass tort early warning system**. After reviewing Goff Law's actual practice mix, the framing is updated:

**Primary lens:** consumer class action + product liability.
**Secondary lens:** mass tort.

**Why this matters:** Personal-injury cases with severe individual harm (deaths, serious injuries) almost never survive Rule 23(b)(3) class certification — *Amchem* and *Ortiz* killed that path because individualized causation/damages defeat predominance. Those cases proceed as mass torts (MDLs, state coordination), where each plaintiff retains an individual claim. **Class actions thrive on the opposite profile**: widespread *uniform* harm, economic damage, systemic defects across many units/years.

For SIGNAL, this changes which clusters bubble to the top. The original scoring leaned heavily on death and injury escalators (mass-tort signals). The class-action lens prioritizes:

1. **Numerosity** — total complaint volume (Rule 23(a)(1) — class so numerous joinder is impracticable)
2. **Commonality** — multi-year systemic defects, normalized component clustering (Rule 23(a)(2))
3. **Manufacturer knowledge** — NHTSA investigations, recalls, TSB patterns (foundation for failure-to-warn theories and *scienter*)
4. **Economic damage** — narrative keywords like "warranty refused", "buyback", "resale", "dealer denied"
5. **"Already filed" penalty** — minus 30 because we want to be *early*

Severity (death, injury, crash, fire) remains in scope but at reduced weight — those cases route to the mass-tort lens.

The case studies in this document (GM ignition switch, Nissan Rogue) are still useful illustrations of "early-detectable signal" but they are **mass-tort** archetypes. Equivalent class-action archetypes — defective transmissions, paint peeling, infotainment failures, multi-year warranty denial patterns — should be treated as the primary surface area going forward.

**Reference:** see `civil_litigation_frameworks_reference.md` (shared with Claude on 2026-05-09) for the full doctrinal background on Rule 23, MDL, and product liability theory.

---

## THE PROBLEM WE'RE SOLVING

Traditional PI mass tort marketing is entirely reactive:

| Traditional Model | SIGNAL Model |
|---|---|
| Wait for case to be publicly filed | Detect the case before it's filed |
| Buy leads from lead gen companies | Generate leads from raw complaint data |
| Compete with 50 firms on same plaintiffs | Be the only firm advertising to those plaintiffs |
| Pay $500–2,000 per signed retainer | Own the pipeline permanently |
| Reactive | **Predictive** |

### Proof of Concept — GM Ignition Switch
- **2005–2006:** NHTSA complaints begin filing. Deaths reported.
- **2006:** Our algorithm would score this **75/100 — HOT**
- **2007:** NHTSA recommends investigation. ODI closes it. Our algorithm scores **85/100 — CRITICAL**
- **2014:** GM finally recalls 2.6M vehicles
- **2014:** First class action filed

**Gap between detectable signal and litigation: 8 years.**
SIGNAL would have flagged this in 2006 — giving an attorney an 8-year head start on every firm that eventually filed.

### Live Example — Nissan Rogue (Active Case)
- **Sept 2023:** First NHTSA complaints filed re: engine bearing failures
- **Dec 2023:** NHTSA opens formal investigation
- **July 2025:** Class action filed in Delaware federal court
- **Feb 2026:** 642,698 vehicles recalled across two campaigns
- **Mar 27, 2026:** Owner notification letters mailing TODAY

SIGNAL would have flagged this in **September 2023** — 22 months before the class action was filed.

---

## THE COMPETITIVE LANDSCAPE

### Darrow AI (Closest Competitor)
- Raised $60M in venture funding
- Generates $26M annual revenue (2024)
- Serves 80 law firms at enterprise pricing ($10K–$1M+/year)
- Broad focus: data breaches, ERISA, environmental, pharma
- **Does NOT specifically focus on NHTSA/CPSC complaint monitoring**
- **Priced out of solo and small PI firm market entirely**

### Lead Generation Companies (Best Case Leads, Tort Experts, Blue Sky Legal)
- Reactive only — run ads AFTER cases are publicly filed
- Sell the same leads to multiple competing firms
- $500–2,000 per signed retainer with no exclusivity

### Large Mass Tort Firms
- Monitor court dockets manually with associate armies
- No algorithmic early detection

### The Gap Nobody Has Filled
An automated, algorithmic NHTSA + CPSC complaint scanner built specifically for small PI firms to find cases **before** they become public — priced accessibly for solo attorneys.

---

## DATA SOURCES

### Phase 1 — Automotive (NHTSA)
- **Source:** api.nhtsa.gov — free, public, updated daily
- **Coverage:** All vehicle complaints since 1995
- **Volume:** ~100–150 new complaints per week nationally
- **Key fields available in every complaint:**
  - Manufacturer, Make, Model, Year
  - Crash (Y/N)
  - Fire (Y/N)
  - Number Injured (exact count)
  - Number of Deaths (exact count)
  - Medical Attention Required (Y/N)
  - Police Report Filed (Y/N)
  - Vehicle Speed at Incident
  - Consumer State (Texas filter available)
  - Full narrative description (2,048 characters)
  - Component description

### Phase 2 — Consumer Products (CPSC)
- **Source:** SaferProducts.gov — free public API
- **Coverage:** All consumer product complaints
- **Structure:** Similar to NHTSA — injury/death flags built in
- **Categories:** Electronics, appliances, furniture, children's products, tools

### Phase 3 — Community Corroboration
- **Reddit:** Free API — target r/MechanicAdvice, r/cars, brand-specific subs
- **CarComplaints.com:** Aggregated owner complaints — scrape as proxy for forums
- **Twitter/X:** $100+/month API — deprioritize for now
- **Facebook:** Not viable — no public post search API

---

## THE ALGORITHM — 7 STEPS

### Step 1 — Data Ingestion (Runs Daily)
```
Pull all new NHTSA complaints from last 7 days
Pull Reddit posts matching tracked vehicles
Pull CarComplaints.com new entries
→ Store in database tagged by:
   make, model, year, component, date, injuries, deaths, crash Y/N
```

### Step 2 — Clustering
```
Group complaints by:
  - Same make + model + year
  - Same component (engine, transmission, brakes, etc.)
  - Similar complaint description (AI semantic similarity)

→ Output: Named Complaint Clusters
   Example: "2022 Ford F-150 / Transmission / Shudder at highway speed"
   → 47 complaints across NHTSA + Reddit + CarComplaints
```

### Step 3 — Scoring (0–100, class-action-lens primary)

**BASE SCORE — NUMEROSITY (Rule 23(a)(1))**
- +1 point per complaint, capped at +50 (was +30 — uplifted to reflect numerosity's primacy)

**VELOCITY BONUS**
- 2x multiplier if complaints in last 30 days ≥ 50% of total
- 3x multiplier if complaints in last 30 days ≥ 66% of total

**COMMONALITY (Rule 23(a)(2))**
- +20 points if same defect spans multiple model years (multi-year = systemic = strongest commonality signal; was +10)

**MANUFACTURER KNOWLEDGE (failure-to-warn / *scienter*)**
- +25 points if NHTSA has opened a formal investigation (was +20)
- +30 points if a recall has already been issued (was +25)
- TSB-issued without recall (planned — see Phase 3 in PLAN_AND_GOALS.md)

**ECONOMIC DAMAGE SIGNALS** *(planned — narrative keyword scoring not yet implemented)*
- +5 points each if complaints mention warranty refusal, value/resale loss, dealer denial
- These are class-action gold (uniform economic harm = textbook predominance)

**SEVERITY ESCALATORS — secondary (mass-tort lens)**
- +10 points if any complaint mentions injury (was +20)
- +20 points if any complaint mentions death (was +50)
- +5 points if crash = Y on any complaint (was +10)
- +10 points if fire = Y on any complaint (was +15)

These remain in scope but at reduced weight — severe individual injury pushes a case toward mass-tort classification (MDL), not class certification.

**LEGAL VIABILITY SIGNALS** *(Phase 2 — community corroboration not yet implemented)*
- +15 points if same issue appears on Reddit
- +15 points if same issue appears on CarComplaints.com

**PENALTY**
- -30 points if issue is already a filed class action (want to be EARLY)

### Step 4 — Classification
```
90–100  → 🔴 CRITICAL  (death reports or massive injury spike)
70–89   → 🟠 HOT       (injuries, fast growth, multi-source confirmation)
50–69   → 🟡 WATCH     (volume spike, economic damage signals)
25–49   → 🟢 MONITOR   (early, low volume, worth tracking)
0–24    → ⚪ NOISE     (filtered out, not shown)
```

### Step 5 — AI Viability Check (Claude)
For every WATCH or higher cluster, Claude automatically answers:
1. **Numerosity** — enough complaints to certify a class?
2. **Commonality** — is the defect the same across all complainants?
3. **Economic damage** — measurable loss even without physical injury?
4. **Manufacturer knowledge** — did they know? (prior complaints, TSBs, recalls)
5. **Similar cases filed?** — has this been litigated before elsewhere?

Output: Mini legal memo per cluster before attorney spends any time on it.

### Step 6 — Dashboard Output
```
Ranked table of clusters by score
→ Click any cluster to see:
   - All raw complaints
   - Reddit threads
   - CarComplaints entries
   - AI viability memo
   - Timeline chart of complaint volume over time
   - Map of complainant locations
```

### Step 7 — Alerts
```
Daily email digest: anything that moved to HOT or CRITICAL
Instant alert: any cluster receives a death report
Weekly summary: all MONITOR clusters trending upward
```

---

## ALGORITHM VALIDATION — GM IGNITION SWITCH TEST

**Historical NHTSA complaint data for Chevrolet Cobalt:**

| Year | Complaints | Deaths | Algorithm Score | Classification |
|---|---|---|---|---|
| 2005 | 26 | 1 | 31 | 🟢 MONITOR |
| 2006 | 69 | 6 | 75 | 🟠 HOT — **First actionable year** |
| 2007 | 87 | 4 | 85 | 🟠 HOT |
| 2008 | 106 | 3 | 88 | 🔴 CRITICAL |
| 2009 | 133 | 5 | 91 | 🔴 CRITICAL |
| 2010 | 400 | 15 | OFF CHARTS | 🔴 CRITICAL |

**Real timeline:**
- 2007: NHTSA recommends probe → ODI closes it (missed)
- 2010: NHTSA recommends probe again → ODI closes it again (missed)
- 2014: GM recalls 2.6M vehicles
- 2014: Class actions filed

**SIGNAL would have flagged this in 2006 — 8 years before recall.**

**Outcome:** $900M+ in settlements | 300+ deaths | 2.6M vehicles recalled | 40 class actions in 12 states

---

## BUSINESS MODEL — 5 REVENUE LAYERS

### Layer 1 — Direct Client Acquisition
Dashboard flags emerging cluster → run targeted Facebook/Google ads to owners of affected vehicle make/model/year in Texas → capture plaintiffs before any other firm is advertising.

Cost: Ad spend only. No lead gen fees. No referral splits.

### Layer 2 — Referral Fee Machine
- SIGNAL identifies emerging case
- Sign Texas plaintiffs early
- Refer to national mass tort firm
- Collect **25–40% referral fee** on attorney fees
- Texas Rule 1.04 compliant with client consent + written agreement
- Zero case management overhead

### Layer 3 — Co-Counsel Positioning
Come to national firms with 15+ signed Texas plaintiffs + documented NHTSA cluster + AI viability memo. Negotiate co-counsel split instead of straight referral. Higher upside, more involvement.

### Layer 4 — Get Goff Content Engine
Every complaint cluster = a YouTube video topic:
- *"Nissan Rogue owners — here's what Nissan isn't telling you"*
- *"If you own a 2023 F-150 watch this before your warranty expires"*
- *"This GM defect killed 300 people and it took 10 years for a recall"*

Dashboard gives Bryan unlimited evergreen high-urgency content topics that no other Texas PI firm is producing. Videos target exactly the people who own affected vehicles and are already searching for answers.

### Layer 5 — SaaS Product (Long Term)
After 90-day internal validation:
- License to other solo/small PI firms nationally
- $300–500/month subscription
- 500 subscribers = $200K/month recurring revenue
- Darrow proved the demand. You serve the underserved market.

---

## THE FLYWHEEL

```
DETECT                     ADVERTISE                  FILE
────────────────────────────────────────────────────────
Algorithm flags        →   Target ads to owners   →   Sign plaintiffs
emerging complaint         of affected vehicles       before national
cluster on NHTSA           on Facebook/Google         firms even know
                           before anyone else         the case exists
     |                                                      |
     |____________________CONTENT__________________________|
                      Get Goff YouTube videos
                      drive organic inbound from
                      affected vehicle owners
```

---

## IMPLEMENTATION ROADMAP

### Phase 1 — Automotive (Now → Month 3)
- Build NHTSA API data pipeline
- Build clustering algorithm
- Build scoring engine
- Build dashboard (web browser, accessible anywhere)
- First live complaint cluster identified and scored

### Phase 2 — Expand Sources (Month 3 → Month 6)
- Add Reddit monitoring
- Add CarComplaints.com
- Add AI viability memo generation (Claude)
- First targeted ad campaign to affected vehicle owners in Texas

### Phase 3 — Consumer Products (Month 6 → Month 9)
- Add CPSC SaferProducts.gov data source
- Same architecture — second pipeline bolted on
- Expand beyond automotive into consumer product defects

### Phase 4 — Productize (Month 9+)
- Evaluate SaaS opportunity based on internal validation
- Multi-tenant architecture if pursuing
- Separate brand ("Signal" or similar)

---

## TECH STACK (To Be Finalized)

**Data Layer:**
- NHTSA API (free, public)
- CPSC SaferProducts.gov API (free, public)
- Reddit API (free tier)
- CarComplaints.com (scrape)

**AI Layer:**
- Claude API — complaint clustering, semantic similarity, viability memos
- OpenAI embeddings — optional for semantic search

**Infrastructure:**
- Railway or similar for hosting
- Pinecone for vector storage (already in use for Bill AI Machine)
- n8n for workflow automation (already in stack)

**Dashboard:**
- Web-based (browser accessible anywhere)
- React frontend
- Daily automated data refresh

**Existing Stack Compatibility:**
- VS Code for development
- Docker for containerization
- n8n already deployed for automation

---

## CATEGORY SELECTION RATIONALE

Four options evaluated:

| Category | Data Quality | Legal Fit | Competition | Build Speed | Decision |
|---|---|---|---|---|---|
| **Automotive (NHTSA)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **Phase 1 — START HERE** |
| Consumer Products (CPSC) | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Phase 2 expansion |
| Data Breaches | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | Skip — Darrow dominates |
| AI-Related Actions | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | Too early — 2–3 years |

**Key reasoning:** PI background in trucking and crashes means immediate ability to read an NHTSA complaint and assess legal viability. That judgment is the unfair advantage — and it only applies natively to automotive. Start where expertise already exists.

---

## KEY STATISTICS

- Class action settlements exceeded **$70 billion** in 2025 — highest in history of American jurisprudence
- Courts certified **68%** of all class certification motions in 2025
- NHTSA complaint database updated **daily**, goes back to 1995
- Approximately **100–150 new complaints per week** nationally
- Average recall completion rate across all manufacturers: **48%** — meaning half of recalled vehicles remain unrepaired
- Darrow AI serves 80 law firms, has facilitated **$15B+ in active litigation value**
- Darrow charges **$10K–$1M+/year** — solo PI firms priced out entirely

---

## NOTES & NEXT STEPS

- [ ] Finalize tech build approach (vibe code vs. hire developer vs. no-code)
- [ ] Confirm dashboard hosting preference
- [ ] Set timeline for Phase 1 working prototype
- [ ] Plan advertising strategy (how flagged case becomes signed clients)
- [ ] Plan intake process (how leads flow into firm once ads run)
- [ ] Identify first national mass tort firms for referral relationships
- [ ] Discuss with Bryan how SIGNAL feeds Get Goff content calendar

---

*SIGNAL — Goff Law PLLC Internal Planning Document*
*Confidential — Not for Distribution*
*Last Updated: March 27, 2026*
