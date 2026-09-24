# Phase 2 design — CarComplaints.com harvest

**Date:** 2026-09-24  
**Owner ask:** Jimmy — spike CarComplaints before `class_action_filed` / `tsb_known`  
**Repo:** https://github.com/JimGoff518/signal  
**Tracking issue:** https://github.com/JimGoff518/signal/issues/2

## Goal
Add CarComplaints.com as a U.S.-only secondary discovery / corroboration source for automobile design and product defects. NHTSA remains the core early-warning pipeline. Detection is nationwide; Texas stays primary for ads and plaintiff intake.

## Why this source
URL shape aligns with Signal clusters:

`https://www.carcomplaints.com/{Make}/{Model}/{Year}/{category}/`  
`https://www.carcomplaints.com/{Make}/{Model}/{Year}/{category}/{problem}.shtml`

Problem pages expose complaint volume, crashes/fires, injuries/deaths, average mileage, owner narratives (city/state), and sidebar counts for recalls, investigations, and TSBs.

## Tooling recommendation
| Step | Tool |
|------|------|
| Discovery crawl | Homepage trends / worst vehicles → category → problem pages |
| Structured extract | llm-scraper or Lightfeed Extractor + Zod → Postgres staging |
| Recurring agent pull | PyScrappy or DeepScrape MCP |
| High volume (later) | Trawl after selectors stabilize |

## Zod schema (draft)

```ts
import { z } from "zod";

const RecentComplaint = z.object({
  problem_number: z.number().int().optional(),
  date: z.string().optional(),
  text: z.string(),
  city: z.string().optional(),
  state: z.string().length(2).optional(),
});

export const CarComplaintsProblemPage = z.object({
  make: z.string(),
  model: z.string(),
  year: z.number().int().min(1980).max(2030),
  category_slug: z.string(),
  problem_slug: z.string().optional(),
  page_url: z.string().url(),
  complaint_count: z.number().int().nonnegative().optional(),
  nhtsa_category_label: z.string().optional(),
  crashes: z.number().int().nonnegative().optional(),
  fires: z.number().int().nonnegative().optional(),
  injuries: z.number().int().nonnegative().optional(),
  deaths: z.number().int().nonnegative().optional(),
  avg_mileage: z.number().nonnegative().optional(),
  site_severity_score: z.number().optional(),
  recalls_count: z.number().int().nonnegative().optional(),
  investigations_count: z.number().int().nonnegative().optional(),
  tsbs_count: z.number().int().nonnegative().optional(),
  site_notes: z.string().optional(),
  recent_complaints: z.array(RecentComplaint).default([]),
  scraped_at: z.string().datetime(),
});
```

## Join rule
Normalize `make` / `model` / `year` and map `category_slug` → Signal `component` (also helps reduce noisy `OTHER`).

- Match HOT/CRITICAL NHTSA cluster → corroboration for viability memo / ads
- Rising CarComplaints page without a strong NHTSA cluster → discovery candidate
- Treat CarComplaints counts as corroboration (often NHTSA-mirrored), not a second ground truth

## MVP build order
1. One-shot extract of homepage trends + worst vehicles → staging table
2. Walk category/problem pages; fill Zod rows
3. Match to clusters; flag `carcomplaints_only` vs `nhtsa_and_carcomplaints`
4. MCP / script for “open CarComplaints for this cluster” + nightly delta on WATCH+

## Pilot list (10) — live CRITICAL @ score 100 (2026-09-24)
Source: prod DB via Jev Scout — Signal. All CRITICAL at 100 (no HOT in this top slice).

| # | Make | Model | Year | Component | Multi-year | Complaints | Span |
|---|------|-------|------|-----------|------------|------------|------|
| 1 | HYUNDAI | ELANTRA | 2012 | ELECTRICAL | no | 87 | 2015-01-05 → 2026-01-28 |
| 2 | TESLA | MODEL Y | 2022 | OTHER | no | 325 | ⚠️ skip/remap OTHER |
| 3 | RAM | 1500 | multi | ENGINE | yes | 1172 | 2022-09-29 → 2026-05-02 |
| 4 | CHEVROLET | SUBURBAN 1500 | multi | BRAKES | yes | 70 | 2015-01-02 → 2025-06-10 |
| 5 | CHEVROLET | SILVERADO | multi | ELECTRICAL | yes | 86 | 2015-01-02 → 2023-10-11 |
| 6 | CHEVROLET | SILVERADO | multi | AIR BAGS | yes | 132 | 2015-01-02 → 2024-12-26 |
| 7 | CHEVROLET | SUBURBAN | multi | OTHER | yes | 118 | ⚠️ skip OTHER |
| 8 | GMC | YUKON | multi | BRAKES | yes | 84 | 2022-10-04 → 2026-05-04 |
| 9 | FORD | F-150 | multi | POWER TRAIN | yes | 3956 | 2022-09-19 → 2026-05-04 |
| 10 | TOYOTA | TACOMA | multi | ENGINE | yes | 75 | 2022-11-22 → 2026-04-20 |

**MVP extract order (non-OTHER):** #1, #3, #4, #5, #6, #8, #9, #10.

**CarComplaints year handling:** single-year locked for Elantra 2012; multi-year clusters need peak-year pick or year-range crawl then roll-up (CarComplaints is year-keyed).

**First URL probes:** `Hyundai/Elantra/2012/` electrical; `Ram/1500/{year}/engine`; `Chevrolet/Silverado/{year}/` electrical + airbags; `Ford/F-150/{year}/` powertrain; `Toyota/Tacoma/{year}/engine`; Suburban/Yukon brakes categories.

## Watch-outs
- Robots.txt / ToS / rate limits
- PII in owner narratives
- America-only filter on `state` when present
- Do not replace NHTSA ingestion
- Skip or remapped `OTHER` component clusters until normalize improves

## Acceptance criteria
- [ ] Staging table has ≥8 non-OTHER pilot pages from the CRITICAL list
- [ ] ≥7/8 join to a Signal cluster key or are explicitly unmatched
- [ ] Script or dashboard shows CarComplaints corroboration on a CRITICAL cluster
- [ ] Phase 2 checklist in `SIGNAL_PLAN_AND_GOALS.md` links here

## Source
WebScrape R&D draft for Jimmy Goff, 2026-09-24; pilot keys from Jev Scout — Signal live DB.
