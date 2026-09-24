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

## Pilot list (10)
Interim URLs from live site; replace 9–10 with `python scripts/top_clusters.py` (exclude `OTHER`):

1. 2020 Chevrolet Trax — brakes / Stabilitrak
2. 2018 Mazda CX-5 — engine head
3. 2024 Mazda CX-90 Hybrid — rear brake squeal
4. 2002 Ford Explorer — worst vehicles
5. 2019 Toyota RAV4 — worst vehicles
6. 2003 Honda Accord — worst vehicles
7. 2016 Hyundai Tucson — `body_paint/structure-body.shtml`
8. 2015 Dodge Challenger — `body_paint/`
9. TBD HOT from `top_clusters.py`
10. TBD HOT from `top_clusters.py`

## Watch-outs
- Robots.txt / ToS / rate limits
- PII in owner narratives
- America-only filter on `state` when present
- Do not replace NHTSA ingestion

## Acceptance criteria
- [ ] Staging table has ≥10 pilot pages
- [ ] ≥7/10 join to a Signal cluster key or are explicitly unmatched
- [ ] Script or dashboard shows CarComplaints corroboration on a HOT cluster
- [ ] Phase 2 checklist in `SIGNAL_PLAN_AND_GOALS.md` links here

## Source
WebScrape R&D draft for Jimmy Goff, 2026-09-24.
