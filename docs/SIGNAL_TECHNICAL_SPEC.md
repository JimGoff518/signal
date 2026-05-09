# SIGNAL — Technical Specification Document
### MVP: Pipeline + Scoring Algorithm + Basic Dashboard
### Client: Goff Law PLLC | Prepared for: Development Team
### Date: March 27, 2026
### Version: 1.0

---

## 1. PROJECT OVERVIEW

SIGNAL is a real-time complaint intelligence platform that:
1. **Ingests** vehicle complaint data daily from NHTSA's public API
2. **Clusters** complaints by make/model/year/component
3. **Scores** each cluster using a weighted algorithm to identify litigation potential
4. **Displays** ranked clusters on a web dashboard for attorney review

**Litigation lens (updated 2026-05-09):**
- **Primary:** consumer class action + product liability — the scoring algorithm prioritizes Rule 23 class-certification signals (numerosity, commonality, manufacturer knowledge, economic harm).
- **Secondary:** mass tort — severity escalators (death, injury, crash, fire) remain in scope but at reduced weight, since severe individual harm pushes cases away from class certification (per *Amchem*) and into MDL coordination.

The MVP covers Phase 1 only: NHTSA data pipeline + scoring + dashboard.
Reddit and CarComplaints.com are Phase 2 (not in this spec).

---

## 2. SYSTEM ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────┐
│                        SIGNAL MVP                           │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│  │  NHTSA   │───►│ Ingestion│───►│ Database │             │
│  │   API    │    │  Service │    │          │             │
│  └──────────┘    └──────────┘    └─────┬────┘             │
│                                        │                    │
│                                  ┌─────▼─────┐              │
│                                  │Clustering │              │
│                                  │ Engine    │              │
│                                  └─────┬─────┘              │
│                                        │                    │
│                                  ┌─────▼─────┐              │
│                                  │ Scoring   │              │
│                                  │ Engine    │              │
│                                  └─────┬─────┘              │
│                                        │                    │
│                  ┌─────────────────────▼────────────────┐   │
│                  │           Claude API                 │   │
│                  │     (Viability Memo Generation)      │   │
│                  └─────────────────────┬────────────────┘   │
│                                        │                    │
│                                  ┌─────▼─────┐              │
│                                  │Dashboard  │              │
│                                  │  (Web)    │              │
│                                  └───────────┘              │
└─────────────────────────────────────────────────────────────┘
```

**Stack:** Alex's team to decide. No constraints imposed by client.
**Hosting:** Alex's team to decide.
**Database:** Alex's team to decide (PostgreSQL recommended for relational complaint data).

---

## 3. DATA SOURCE — NHTSA API

### 3.1 Base URL
```
https://api.nhtsa.gov/complaints/complaintsByVehicle
```

### 3.2 Query Parameters
| Parameter | Type | Example |
|---|---|---|
| make | string | ford |
| model | string | f-150 |
| modelYear | integer | 2023 |

### 3.3 Example Request
```
GET https://api.nhtsa.gov/complaints/complaintsByVehicle?make=ford&model=f-150&modelYear=2023
```

### 3.4 Response Fields (Key Fields for SIGNAL)
Every complaint record returns these fields — all required for the scoring engine:

| Field | Type | Description |
|---|---|---|
| odiNumber | string | NHTSA unique complaint ID |
| manufacturer | string | Manufacturer name (e.g. "Ford Motor Company") |
| make | string | Vehicle make (e.g. "Ford") |
| model | string | Vehicle model (e.g. "F-150") |
| modelYear | integer | Model year (e.g. 2023) |
| components | string | Component description (e.g. "ENGINE AND ENGINE COOLING") |
| dateOfIncident | string | Date failure occurred (YYYYMMDD) |
| dateComplaintFiled | string | Date filed with NHTSA (YYYYMMDD) |
| vin | string | Partial VIN (first 11 chars) |
| crash | boolean | Was vehicle in a crash? |
| fire | boolean | Was vehicle in a fire? |
| numberOfInjuries | integer | Number of persons injured |
| numberOfDeaths | integer | Number of fatalities |
| description | string | Full complaint narrative (up to 2048 chars) |
| state | string | Consumer's state (2-letter code) |

### 3.5 Additional NHTSA Endpoints

**Get all available makes:**
```
GET https://api.nhtsa.gov/products/vehicle/makes?issueType=c
```

**Get models for a given make/year:**
```
GET https://api.nhtsa.gov/products/vehicle/models?make={MAKE}&modelYear={YEAR}&issueType=c
```

**Get complaint by ODI number:**
```
GET https://api.nhtsa.gov/complaints/odinumber?odinumber={ODI_NUMBER}
```

### 3.6 Flat File Alternative (For Bulk Historical Load)
For initial database population, use the full flat file download:
```
https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip
```
This contains ALL complaints since 1995. Use for one-time historical import.
Field layout documented at: `https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt`

---

## 4. DATA INGESTION SERVICE

### 4.1 Purpose
Pull new NHTSA complaints daily and store in the database.

### 4.2 Schedule
Run once daily — recommended time: 2:00 AM CT (off-peak).

### 4.3 Logic
```
1. Query NHTSA for complaints filed in last 7 days
   (use dateComplaintFiled as filter)

2. For each complaint returned:
   a. Check if odiNumber already exists in database
   b. If new — insert record
   c. If exists — skip (avoid duplicates)

3. Log run results:
   - Timestamp
   - Number of new complaints ingested
   - Any errors

4. Trigger clustering engine after successful ingestion
```

### 4.4 Vehicles to Monitor (Initial List)
Start with high-volume makes. Expand over time.

**Priority Makes (Phase 1):**
- Ford (F-150, F-250, Ranger, Explorer, Bronco, Mustang)
- Chevrolet (Silverado, Colorado, Tahoe, Suburban, Equinox)
- GMC (Sierra, Canyon, Yukon)
- Ram (1500, 2500, 3500)
- Toyota (Tacoma, Tundra, RAV4, Camry)
- Honda (CR-V, Accord, Civic, Pilot)
- Nissan (Rogue, Altima, Frontier)
- Jeep (Grand Cherokee, Wrangler, Gladiator)
- Tesla (Model 3, Model Y, Model S, Cybertruck)
- Hyundai (Tucson, Santa Fe, Elantra)
- Kia (Telluride, Sorento, Sportage)

**Model Years:** Last 10 years (2015–2025 for initial load)

**Note:** Client can add/remove makes and models from dashboard settings in a future version. For MVP, hardcode the list above.

---

## 5. DATABASE SCHEMA

### 5.1 complaints table
```sql
CREATE TABLE complaints (
  id                    SERIAL PRIMARY KEY,
  odi_number            VARCHAR(20) UNIQUE NOT NULL,
  manufacturer          VARCHAR(100),
  make                  VARCHAR(50) NOT NULL,
  model                 VARCHAR(100) NOT NULL,
  model_year            INTEGER NOT NULL,
  component             VARCHAR(200),
  date_of_incident      DATE,
  date_complaint_filed  DATE,
  vin                   VARCHAR(20),
  crash                 BOOLEAN DEFAULT FALSE,
  fire                  BOOLEAN DEFAULT FALSE,
  injuries              INTEGER DEFAULT 0,
  deaths                INTEGER DEFAULT 0,
  description           TEXT,
  state                 VARCHAR(2),
  created_at            TIMESTAMP DEFAULT NOW()
);
```

### 5.2 clusters table
```sql
CREATE TABLE clusters (
  id                    SERIAL PRIMARY KEY,
  cluster_key           VARCHAR(200) NOT NULL,
  make                  VARCHAR(50) NOT NULL,
  model                 VARCHAR(100) NOT NULL,
  model_year            INTEGER,
  component             VARCHAR(200),
  complaint_count       INTEGER DEFAULT 0,
  injury_count          INTEGER DEFAULT 0,
  death_count           INTEGER DEFAULT 0,
  crash_count           INTEGER DEFAULT 0,
  fire_count            INTEGER DEFAULT 0,
  score                 INTEGER DEFAULT 0,
  classification        VARCHAR(20),
  velocity_7d           INTEGER DEFAULT 0,
  velocity_30d          INTEGER DEFAULT 0,
  first_complaint_date  DATE,
  last_complaint_date   DATE,
  viability_memo        TEXT,
  memo_generated_at     TIMESTAMP,
  created_at            TIMESTAMP DEFAULT NOW(),
  updated_at            TIMESTAMP DEFAULT NOW()
);
```

### 5.3 cluster_complaints table (junction)
```sql
CREATE TABLE cluster_complaints (
  id           SERIAL PRIMARY KEY,
  cluster_id   INTEGER REFERENCES clusters(id),
  complaint_id INTEGER REFERENCES complaints(id),
  created_at   TIMESTAMP DEFAULT NOW()
);
```

### 5.4 ingestion_log table
```sql
CREATE TABLE ingestion_log (
  id                  SERIAL PRIMARY KEY,
  run_at              TIMESTAMP DEFAULT NOW(),
  complaints_ingested INTEGER DEFAULT 0,
  complaints_skipped  INTEGER DEFAULT 0,
  errors              TEXT,
  status              VARCHAR(20)
);
```

---

## 6. CLUSTERING ENGINE

### 6.1 Purpose
Group individual complaints into named clusters representing the same defect pattern.

### 6.2 Clustering Key
Each cluster is identified by a composite key:
```
{MAKE}::{MODEL}::{MODEL_YEAR}::{COMPONENT_NORMALIZED}
```

Example:
```
NISSAN::ROGUE::2023::ENGINE AND ENGINE COOLING
FORD::F-150::2022::POWER TRAIN
CHEVROLET::COBALT::2006::AIR BAGS
```

### 6.3 Component Normalization
NHTSA component descriptions vary in wording. Normalize to standard categories:

| Raw NHTSA Value (examples) | Normalized Category |
|---|---|
| ENGINE AND ENGINE COOLING, ENGINE, ENGINE COOLING | ENGINE |
| POWER TRAIN, TRANSMISSION, DRIVELINE | POWER TRAIN |
| AIR BAGS, AIR BAG, AIRBAG | AIR BAGS |
| SERVICE BRAKES, BRAKES | BRAKES |
| STEERING | STEERING |
| ELECTRICAL SYSTEM, ELECTRICAL | ELECTRICAL |
| FUEL SYSTEM, FUEL | FUEL SYSTEM |
| SUSPENSION | SUSPENSION |
| TIRES | TIRES |
| UNKNOWN OR OTHER | OTHER |

### 6.4 Clustering Logic
```
For each new complaint ingested:

1. Generate cluster_key from make + model + model_year + component_normalized

2. Check if cluster exists in clusters table
   - If YES: update complaint counts, injury/death counts, dates
   - If NO: create new cluster record

3. Insert record into cluster_complaints junction table

4. Recalculate velocity metrics:
   - velocity_7d = complaints in last 7 days for this cluster
   - velocity_30d = complaints in last 30 days for this cluster

5. Trigger scoring engine for updated cluster
```

### 6.5 Multi-Year Clustering (Important)
If the same defect appears across multiple model years of the same vehicle, create SEPARATE clusters per year AND a cross-year aggregate cluster:

```
FORD::F-150::2021::POWER TRAIN  (47 complaints)
FORD::F-150::2022::POWER TRAIN  (63 complaints)
FORD::F-150::2023::POWER TRAIN  (38 complaints)
FORD::F-150::ALL_YEARS::POWER TRAIN  (148 complaints — aggregate)
```

The aggregate cluster receives a bonus in scoring (systemic defect signal).

---

## 7. SCORING ENGINE

### 7.1 Purpose
Assign a 0–100 score to each cluster representing **class-action litigation potential** (primary) with mass-tort severity as secondary signal. Rule 23 prerequisites (numerosity, commonality, manufacturer knowledge) are weighted ahead of injury/death escalators, because severe individual harm defeats class certification under *Amchem* and routes cases to mass-tort instead.

### 7.2 Scoring Formula (rebalanced 2026-05-09)

```python
def calculate_score(cluster):
    score = 0

    # ── NUMEROSITY — Rule 23(a)(1) ──────────────────────────────
    # Volume is THE class-action signal. Cap raised from 30 → 50.
    score += min(cluster.complaint_count, 50)

    # ── VELOCITY BONUS ──────────────────────────────────────────
    # Check tripled (0.66) FIRST so the larger multiplier wins
    # when both branches apply. (Spec v1.0 had these reversed.)
    if cluster.velocity_30d > 0:
        if cluster.velocity_30d >= cluster.complaint_count * 0.66:
            score *= 3
        elif cluster.velocity_30d >= cluster.complaint_count * 0.5:
            score *= 2

    # ── COMMONALITY — Rule 23(a)(2) ─────────────────────────────
    # Multi-year systemic defect = strongest commonality signal.
    if cluster.is_multi_year:
        score += 20  # was +10

    # ── MANUFACTURER KNOWLEDGE ──────────────────────────────────
    # Foundation for failure-to-warn theories and *scienter*.
    if cluster.nhtsa_investigation_open:
        score += 25  # was +20
    if cluster.recall_issued:
        score += 30  # was +25

    # ── SEVERITY ESCALATORS — secondary (mass-tort lens) ────────
    # Reduced from v1.0 to de-emphasize mass-tort routing. These
    # cases stay in scope but don't crowd out class-action signals.
    if cluster.injury_count > 0:
        score += 10  # was +20
    if cluster.death_count > 0:
        score += 20  # was +50
    if cluster.crash_count > 0:
        score += 5   # was +10
    if cluster.fire_count > 0:
        score += 10  # was +15

    # ── EXISTING CLASS ACTION PENALTY ───────────────────────────
    # Already filed = we're late. Penalty preserves the early-mover edge.
    if cluster.class_action_filed:
        score -= 30

    # ── PLANNED (not yet implemented) ───────────────────────────
    # Economic-damage narrative keyword scoring (warranty refused,
    # buyback, resale loss, dealer denial) — class-action gold.
    # Each category → +5 points. See Phase 2 / Phase 3 in
    # SIGNAL_PLAN_AND_GOALS.md.

    return max(0, min(100, score))
```

### 7.3 Classification Thresholds
```
90–100  → CRITICAL  (red)
70–89   → HOT       (orange)
50–69   → WATCH     (yellow)
25–49   → MONITOR   (green)
0–24    → NOISE     (grey — do not display on dashboard)
```

### 7.4 NHTSA Investigation Check (Optional Enhancement)
NHTSA publishes open investigations at:
```
https://api.nhtsa.gov/investigations/
```
Poll this endpoint weekly. If a make/model/year matches an open cluster, set `nhtsa_investigation_open = true` and add 20 points to score.

### 7.5 Score Recalculation Schedule
- Recalculate scores for all clusters every time new complaints are ingested
- Recalculate all scores once daily regardless of new ingestion (catches velocity changes)

---

## 8. CLAUDE API INTEGRATION — VIABILITY MEMO

### 8.1 Purpose
For every cluster classified as WATCH or higher (score ≥ 50), generate a short AI legal viability memo using Claude.

### 8.2 When to Generate
- First time a cluster crosses the WATCH threshold
- Regenerate if complaint count doubles since last memo
- Do NOT regenerate on every score update (expensive)

### 8.3 API Call
```javascript
const response = await fetch("https://api.anthropic.com/v1/messages", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": process.env.ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01"
  },
  body: JSON.stringify({
    model: "claude-sonnet-4-6",
    max_tokens: 1000,
    messages: [
      {
        role: "user",
        content: buildViabilityPrompt(cluster)
      }
    ]
  })
});
```

### 8.4 Prompt Template
```javascript
function buildViabilityPrompt(cluster) {
  return `You are a Texas plaintiff's attorney at Goff Law PLLC evaluating
a potential **consumer class action / product liability** case (with mass
tort as a secondary lens). Analyze the following complaint cluster and
provide a brief legal viability assessment focused on Rule 23
class-certification criteria first, mass-tort indicators second.

COMPLAINT CLUSTER DATA:
- Vehicle: ${cluster.model_year} ${cluster.make} ${cluster.model}
- Component: ${cluster.component}
- Total Complaints: ${cluster.complaint_count}
- Injuries Reported: ${cluster.injury_count}
- Deaths Reported: ${cluster.death_count}
- Crashes Reported: ${cluster.crash_count}
- Complaints in Last 30 Days: ${cluster.velocity_30d}
- States Represented: ${cluster.states_list}
- Date Range: ${cluster.first_complaint_date} to ${cluster.last_complaint_date}

SAMPLE COMPLAINT DESCRIPTIONS:
${cluster.sample_descriptions}  // Pull 3-5 most recent complaint texts

Provide a viability assessment in this exact format:

NUMEROSITY: [1-2 sentences — is there a sufficient number of potential plaintiffs?]

COMMONALITY: [1-2 sentences — is the defect consistent across complaints?]

ECONOMIC DAMAGE: [1-2 sentences — is there measurable economic loss even without physical injury?]

MANUFACTURER KNOWLEDGE: [1-2 sentences — what does the complaint pattern suggest about when the manufacturer knew?]

INJURY/DEATH SEVERITY: [1-2 sentences — assessment of physical harm reported]

OVERALL ASSESSMENT: [2-3 sentences — is this worth investigating further? What is the most likely legal theory?]

RECOMMENDED ACTION: [One of: INVESTIGATE NOW / MONITOR CLOSELY / LOW PRIORITY]

Keep the entire response under 400 words. Be direct. Do not use disclaimers.
Texas law applies.`;
}
```

### 8.5 Store Memo
Save the generated memo text to `clusters.viability_memo` and update `clusters.memo_generated_at`.

---

## 9. DASHBOARD SPECIFICATION

### 9.1 Overview
Web-based dashboard. Accessible from any browser. No mobile-specific optimization required for MVP (desktop first).

### 9.2 Pages Required for MVP

| Page | Route | Description |
|---|---|---|
| Main Dashboard | / | Ranked cluster table |
| Cluster Detail | /cluster/:id | Full detail view for one cluster |
| (Optional) Settings | /settings | Filter preferences |

---

### 9.3 Main Dashboard Page — `/`

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  🔴 SIGNAL — Class Action / Product Liability  [Goff Law]   │
├─────────────────────────────────────────────────────────────┤
│  Filters: [Make ▼] [Model Year ▼] [Classification ▼] [Search]│
├─────────────────────────────────────────────────────────────┤
│  Last Updated: March 27, 2026 2:04 AM CT                    │
│  Active Clusters: 47 | Critical: 2 | Hot: 8 | Watch: 14    │
├─────────────────────────────────────────────────────────────┤
│  CLUSTER TABLE (sorted by score descending)                 │
│                                                             │
│  [Classification] [Vehicle] [Component] [Count] [Score] [→] │
└─────────────────────────────────────────────────────────────┘
```

**Cluster Table Columns:**

| Column | Description |
|---|---|
| Status Badge | 🔴 CRITICAL / 🟠 HOT / 🟡 WATCH / 🟢 MONITOR |
| Vehicle | Year Make Model (e.g. "2023 Nissan Rogue") |
| Component | Normalized component (e.g. "ENGINE") |
| Complaints | Total complaint count |
| Injuries | Total injuries (bold red if > 0) |
| Deaths | Total deaths (bold red if > 0) |
| 30-Day Trend | New complaints in last 30 days with up arrow if increasing |
| Score | Numeric score (0–100) |
| → | Link to cluster detail page |

**Filters:**
- Make (dropdown — all makes in database)
- Model Year (dropdown — 2015 to current)
- Classification (All / Critical / Hot / Watch / Monitor)
- Text search (searches make + model + component)

**Default sort:** Score descending (highest first)
**Hide:** NOISE clusters (score < 25) by default. Show toggle to reveal.

---

### 9.4 Cluster Detail Page — `/cluster/:id`

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  ← Back to Dashboard                                        │
├─────────────────────────────────────────────────────────────┤
│  🔴 CRITICAL — Score: 87/100                                │
│  2023 Nissan Rogue | ENGINE | 47 Complaints                │
├──────────────────────┬──────────────────────────────────────┤
│  STATS               │  COMPLAINT VOLUME CHART              │
│  Injuries: 3         │  (Bar chart — complaints per month)  │
│  Deaths: 0           │                                      │
│  Crashes: 12         │                                      │
│  Fires: 1            │                                      │
│  States: TX, CA, FL… │                                      │
├──────────────────────┴──────────────────────────────────────┤
│  AI VIABILITY MEMO                                          │
│  [Generated memo text from Claude]                          │
├─────────────────────────────────────────────────────────────┤
│  RAW COMPLAINTS (paginated, 20 per page)                    │
│                                                             │
│  [Date] [State] [Crash] [Injuries] [Description excerpt →]  │
└─────────────────────────────────────────────────────────────┘
```

**Stats Panel:**
- Total complaints
- Injuries (red if > 0)
- Deaths (red if > 0)
- Crashes
- Fires
- States represented (comma-separated list)
- Date of first complaint
- Date of most recent complaint
- Complaints in last 30 days

**Complaint Volume Chart:**
- Bar chart showing complaints per month for the last 24 months
- Highlight last 30 days bar in red if velocity is increasing

**AI Viability Memo:**
- Display full memo text
- Show "Generated: [date]" below
- Button: "Regenerate Memo" (calls Claude API again)

**Raw Complaints Table:**
- Sortable by date (newest first default)
- Columns: Date Filed, State, Crash (Y/N), Injuries, Deaths, Component, Description (first 200 chars)
- Click row to expand full description
- Paginate at 20 records per page

---

## 10. ALERT SYSTEM

### 10.1 Email Alerts (MVP — Simple)
Send to: jim@gofflawdfw.com (hardcoded for MVP)

**Daily Digest Email (7:00 AM CT):**
```
Subject: SIGNAL Daily Brief — [Date]

🔴 CRITICAL CLUSTERS (2)
- 2023 Nissan Rogue | Engine | 47 complaints | Score: 87
- 2022 Ford F-150 | Transmission | 31 complaints | Score: 82

🟠 NEW HOT CLUSTERS (1 new today)
- 2024 Chevy Silverado | Brakes | 18 complaints | Score: 71 — NEW

View Dashboard → [link]
```

**Instant Death Alert:**
Any time `deaths > 0` is recorded on a new complaint for the first time in a cluster:
```
Subject: ⚠️ SIGNAL DEATH ALERT — [Year Make Model]

A fatality has been reported in an emerging complaint cluster.

Vehicle: 2024 Ford F-150
Component: POWER TRAIN
Total Complaints: 14
Deaths Reported: 1

View Cluster → [link]
```

### 10.2 Email Service
Use any transactional email provider (Resend, SendGrid, Postmark — Alex's preference).

---

## 11. PERFORMANCE REQUIREMENTS

| Metric | Target |
|---|---|
| Dashboard load time | < 2 seconds |
| Ingestion run time | < 5 minutes |
| Scoring recalculation | < 1 minute for all clusters |
| Claude memo generation | < 30 seconds per cluster |
| Database query response | < 500ms |

---

## 12. SECURITY REQUIREMENTS

- Dashboard requires login (simple username/password for MVP — no OAuth needed)
- Single user account: jim@gofflawdfw.com
- HTTPS required
- API keys stored as environment variables (never hardcoded)
- NHTSA data is public — no special handling required
- Claude API key must be kept server-side only (never exposed to browser)

---

## 13. MVP EXCLUSIONS (PHASE 2)

The following are explicitly NOT in scope for MVP:

- Reddit monitoring
- CarComplaints.com scraping
- CPSC consumer product data
- Multi-user accounts / team access
- Mobile optimization
- Texas-specific geographic filtering (add in Phase 2)
- Advertising integration
- Export to PDF/CSV
- Case management system integration (Filevine)
- SaaS multi-tenant architecture

---

## 14. DELIVERABLES CHECKLIST

- [ ] Daily NHTSA data ingestion pipeline (cron job)
- [ ] Historical data import (flat file, 2015–present)
- [ ] Complaint storage database
- [ ] Clustering engine
- [ ] Scoring engine (0–100 formula)
- [ ] Claude API integration (viability memos)
- [ ] Main dashboard page with cluster table
- [ ] Cluster detail page
- [ ] Daily digest email
- [ ] Death alert email
- [ ] Login/authentication (single user)
- [ ] Deployed to production URL (HTTPS)
- [ ] Basic documentation for client on how to use

---

## 15. QUESTIONS FOR DEVELOPMENT TEAM

Before starting, please confirm:

1. What database will you use? (PostgreSQL recommended)
2. What hosting platform?
3. What frontend framework? (React recommended)
4. What will you use for the cron/scheduler?
5. What email provider for alerts?
6. Estimated timeline for each deliverable?
7. Will you use the NHTSA flat file for historical import or query the API retroactively?

---

## 16. REFERENCE LINKS

| Resource | URL |
|---|---|
| NHTSA API Documentation | https://www.nhtsa.gov/nhtsa-datasets-and-apis |
| NHTSA Complaint API | https://api.nhtsa.gov/complaints/complaintsByVehicle |
| NHTSA Flat File Download | https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip |
| NHTSA Field Dictionary | https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt |
| Claude API Documentation | https://docs.anthropic.com |
| Business Context Document | See SIGNAL_README.md |

---

*SIGNAL Technical Specification v1.0*
*Goff Law PLLC — Confidential*
*For development use only — not for distribution*
