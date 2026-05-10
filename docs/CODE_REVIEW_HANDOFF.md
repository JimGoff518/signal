# SIGNAL — Code Review Handoff

**Audience:** an external reviewer (e.g., Gemini) being asked to critique the codebase.
**Author:** Jim Goff, Goff Law PLLC.
**Date:** May 9, 2026.

This document is the orientation doc — the briefest possible "what to read, in what order, what to scrutinize." After reading this, jump into the linked source.

---

## 1. What SIGNAL is in one paragraph

SIGNAL is a **consumer class-action + product-liability** early warning system for Goff Law PLLC. It pulls NHTSA vehicle complaint data daily, clusters defects by make/model/year/component, scores each cluster 0–100 against Rule 23 class-certification criteria (numerosity, commonality, manufacturer knowledge, economic harm) plus mass-tort severity signals, generates Anthropic Claude–powered viability memos for high-scoring clusters, integrates with CourtListener to detect already-filed class actions (so we don't waste effort on lawyered cases), and emails periodic digests + death alerts. Phase 1 MVP, currently in production. Tech stack: Python 3.12, FastAPI + Jinja + HTMX + Tailwind, PostgreSQL on Railway.

---

## 2. Documentation to read first (in order)

These four documents are the canonical context. Read in this order before opening any code:

1. **[docs/SIGNAL_README.md](SIGNAL_README.md)** — strategic context. What problem we're solving, why class action vs. mass tort matters legally, the algorithm's high-level shape, business model. Note the **"LITIGATION LENS — UPDATED 2026-05-09"** section near the top: as of yesterday, the system was reframed from "mass tort" to "consumer class action + product liability primary, mass tort secondary." That shift matters; it changes which clusters bubble to the top.

2. **[docs/SIGNAL_TECHNICAL_SPEC.md](SIGNAL_TECHNICAL_SPEC.md)** — implementation spec. **§7 (Scoring Engine)** has the rebalanced formula in code form. **§8** is the Claude viability memo prompt. **§5** is the database schema.

3. **[docs/SIGNAL_PLAN_AND_GOALS.md](SIGNAL_PLAN_AND_GOALS.md)** — roadmap (Phases 1–4), success metrics, debug queue (known issues), and the recently-added **"Calibration — 10-Year Backtest"**, **"Debug Queue"**, and **"Dallas Docket — Interface Fun Items"** sections.

4. **[CLAUDE.md](../CLAUDE.md)** — operating notes for AI agents working in this codebase. Architecture diagram, common commands, "things that bite," and prod-deployment notes (Railway).

5. **[civil_litigation_frameworks_reference.md](../civil_litigation_frameworks_reference.md)** *(if shared)* — a comprehensive reference on U.S. mass tort, class action, and product liability doctrine. Worth skimming if you're not familiar with Rule 23, *Amchem*, MDL, etc. — it explains why the scoring weights are shaped the way they are.

---

## 3. Code organization

```
Signal/
├── src/signalwarn/                   data + pipeline + scoring + legacy UI
│   ├── config.py                     pydantic-settings, single source of truth
│   ├── db.py                         psycopg + SQLAlchemy connection helpers
│   ├── nhtsa.py                      NHTSA API client
│   ├── normalize.py                  free-text → ~15 canonical component buckets
│   ├── clustering.py                 cluster builder (per-year + cross-year aggregates)
│   ├── scoring.py                    pure-function 0–100 scorer (§7.2 of spec)
│   ├── ingestion.py                  daily delta orchestrator
│   ├── historical.py                 bulk import + rescore-all
│   ├── viability.py                  Claude viability memo generator
│   ├── alerts.py                     Resend email alerts (digest + death alerts)
│   ├── courtlistener.py              CourtListener REST v4 client (added 2026-05-09)
│   ├── filings_check.py              CourtListener check core, called by both
│   │                                 the CLI script and the /admin endpoint
│   ├── migrations.py                 PENDING DDL list, applied on startup
│   └── app.py                        legacy Streamlit dashboard (being phased out)
├── web/                              current FastAPI dashboard
│   ├── app.py                        routes, auth, /admin operations page
│   ├── queries.py                    read queries for the dashboard
│   └── templates/                    Jinja2 + Tailwind via CDN
├── scripts/                          one-shot CLIs
│   ├── historical_import.py          bulk seed from NHTSA flat files
│   ├── run_ingestion.py              cron entry point (daily delta)
│   ├── check_filings.py              CourtListener filings checker
│   ├── rescore_all.py                full-DB rescore (post weight changes)
│   ├── apply_pending_migrations.py   DDL CLI (also auto-applied at app startup)
│   ├── top_clusters.py               rank by tort signal × log10(complaints+10)
│   └── tsb_smoking_guns.py           TSB-without-recall pattern surfacer
├── migrations/001_initial_schema.sql full schema (auto-applied on first boot)
└── tests/                            pytest unit tests (89 passing)
```

The data pipeline is the product. The dashboard is a read-only view over `clusters`.

---

## 4. Recent significant changes (last ~24 hours)

In commit order — see `git log` for details:

- **`64c110b` — Reframe SIGNAL: class action + product liability primary, mass tort secondary.** Doc-only commit that updates README, CLAUDE.md, SIGNAL_README, SIGNAL_TECHNICAL_SPEC, and the Claude viability prompt to lead with Rule 23 class-cert criteria.
- **`5a4f7ba` — Rebalance scoring weights for class-action lens.** Volume cap 30→50 (numerosity primacy). Multi-year 10→20 (commonality). Investigation 20→25, recall 25→30 (manufacturer knowledge). Severity escalators halved (death 50→20, injury 20→10, etc.). Three new archetype tests in `tests/test_scoring.py` lock in the intended behavior shift.
- **`2657e3b` — CourtListener integration (Phase 3a).** New `signalwarn.courtlistener` REST v4 client, `scripts/check_filings.py`, schema columns to track filings, 12 new unit tests. Ran against ~2,700 HOT+ clusters in prod; matched real cases (e.g., Buchholz v. GM for Equinox engine).
- **`ffc28f9` — Pending vs terminated differentiation.** A *terminated* class action (settled / dismissed / SJ for defendant / certification of competing class counsel) means the cluster is no longer an opportunity → hide it from the dashboard entirely. Only *pending* class actions get the -30 score penalty (we still want Jim to see them).
- **`cce2811` — Stop using SSH for ops: admin page + auto-migrations.** FastAPI lifespan hook auto-applies pending DDL on every container boot. New `/admin` page (login-required) exposes "check filings" and "rescore all" as background-thread jobs with status. Eliminates the SSH dance for routine ops.

---

## 5. What's running in prod RIGHT NOW vs. what's on `main`

This is important — there's a gap.

- `main` HEAD: `cce2811`.
- Active Railway deployment: `b5c2dbc3` (an older commit, predates several of the changes above).
- **Reason:** Railway's GitHub auto-deploy didn't pick up the last few pushes. The user is in the middle of resolving this (a single Redeploy click in the Railway dashboard).
- **Implication:** when reviewing the running system, recognize that `/admin`, the auto-startup migration hook, and the pending/terminated split are *not yet live*. The scoring rebalance, CourtListener v1, and rescored cluster fleet *are* live.

---

## 6. Files to focus a critique on

If you only have time to dig into a few:

- **[src/signalwarn/scoring.py](../src/signalwarn/scoring.py)** — the heart of the system. 80 lines, pure function, no I/O. Critique the formula, the weights, the ordering, edge cases.
- **[src/signalwarn/courtlistener.py](../src/signalwarn/courtlistener.py)** — newest code. REST client + per-component query construction + status detection. Critique error handling, API choices, query effectiveness.
- **[src/signalwarn/filings_check.py](../src/signalwarn/filings_check.py)** — the orchestration layer between CourtListener and the DB. Critique the SQL, the throttling, the rescore-after-match logic.
- **[web/app.py](../web/app.py)** — FastAPI routes including the new `/admin` page. Critique the background-task pattern (daemon threads + in-memory status dict), session auth, the lifespan migration hook.
- **[src/signalwarn/clustering.py](../src/signalwarn/clustering.py)** — the cluster identity logic. Two clusters per complaint (per-year + cross-year aggregate) — is that the right model?
- **[migrations/001_initial_schema.sql](../migrations/001_initial_schema.sql)** + **[src/signalwarn/migrations.py](../src/signalwarn/migrations.py)** — the home-grown migration system. Idempotent ALTER TABLE statements applied on every boot, no Alembic. Critique whether this scales.
- **[tests/test_scoring.py](../tests/test_scoring.py)** — note the three "archetype" tests at the bottom that lock in the class-action-vs-mass-tort behavior. Critique whether the tests actually capture the lens intent.

---

## 7. Specific questions worth asking

Frame the critique around these. They're the things the project owner is most uncertain about:

1. **Is the scoring formula well-calibrated?** Volume cap = 50, multi-year = +20, recall = +30, death = +20. The reasoning is in §7.2 of the spec and the [project_litigation_lens.md memory](.). The weights are educated guesses informed by Rule 23 doctrine; they have *not* been validated against historical filing outcomes yet. The plan calls for a 10-year backtest once CourtListener integration is fully populated. Are the relative magnitudes sensible? Are any signals missing? Is anything being double-counted?

2. **Is the CourtListener query strategy good enough?** [courtlistener.py:build_query](../src/signalwarn/courtlistener.py) constructs `"<Make>" "<Model>" (<component-keywords>) "class action"` queries. False positive rate is unknown. The "ENGINE" → "engine OR oil consumption OR rod bearing" expansion is hand-tuned; some buckets like "OTHER" are too generic to query. Is there a smarter approach? Should we use the `nature_of_suit` filter (NOS code 365 = Personal Injury - Product Liability) instead of relying on text matching?

3. **Is the pending vs. terminated heuristic right?** [filings_check.py](../src/signalwarn/filings_check.py) treats `dateTerminated` as the sole signal: present = terminated → hide; absent = pending → -30. We don't differentiate certified-but-not-yet-terminated cases (where class counsel is locked in but the case hasn't closed) from genuinely-active-and-up-for-grabs cases. Worth scanning docket entries for certification orders? Cost/benefit?

4. **Is the cluster model the right level of granularity?** [clustering.py](../src/signalwarn/clustering.py) creates two clusters per complaint: a per-year `MAKE::MODEL::YEAR::COMPONENT` cluster and a cross-year `MAKE::MODEL::ALL_YEARS::COMPONENT` aggregate. The aggregate gets a +20 multi-year bonus. This means every complaint is double-counted across two cluster rows. Is that the right model? Should we use a single cluster with a `model_years[]` array instead?

5. **Is the home-grown migration system a footgun?** No Alembic. We rely on `ALTER TABLE … ADD COLUMN IF NOT EXISTS` running on every boot via a FastAPI lifespan hook. Idempotent statements only. Critique: how does this fail? What about destructive changes (renames, drops)? When does this approach stop scaling?

6. **Is the background-task pattern in `/admin` safe?** [web/app.py](../web/app.py) launches daemon threads from a FastAPI route. Status is held in a module-level dict. Single uvicorn process means it works, but `--workers 2` is in the Dockerfile — does this break under multi-worker? Should this be Celery / RQ / something more robust?

7. **Auth.** Sessions via `starlette.middleware.sessions` + a cookie. `SECRET_KEY` is derived from `SIGNAL_PASSWORD + "::" + SIGNAL_USERNAME`, which means rotating Jim's password rotates the session key (good — invalidates old sessions on rotation). But: is single-user / multi-user-via-JSON the right shape long-term? Any obvious holes?

8. **Test coverage.** 89 passing tests. No integration tests against the real DB or real NHTSA / CourtListener APIs (the live API tests are run manually during development). Where's the biggest coverage gap that's likely to bite us?

---

## 8. Known issues (the "Debug Queue")

From [docs/SIGNAL_PLAN_AND_GOALS.md](SIGNAL_PLAN_AND_GOALS.md) — these are explicitly known and tracked, not unknown unknowns:

- Dashboard "12-mo trend" sparkline is per-cluster normalized, so a cluster with 3 complaints/month looks just as spiky as one with 300.
- The "OTHER" component bucket inflates false positives — clusters with `component='OTHER'` can hit score 100 despite weak commonality.
- TSB-without-recall pattern (`scripts/tsb_smoking_guns.py`) was built but has never been run against prod yet.
- Recall + investigation flag application (`historical_import.py --skip-complaints`) hasn't been re-run since the bulk import — flags are likely incomplete.
- Email digest reliability is unknown (Resend domain verification status for `gofflawdfw.com` not confirmed; pending Gmail SMTP swap in GitHub issue #1).

---

## 9. Constraints worth knowing

- **Solo principal practice.** Goff Law PLLC is Jim Goff (lead) + Jack Kelley (collaborator, just onboarded). Code that requires a team to maintain is over-engineered.
- **No SaaS users yet.** Phase 4 might productize for other small PI firms ($300–500/mo SaaS), but Phase 1 is internal-only. Multi-tenant complexity is premature.
- **Migrations need to land in prod manually.** No CI/CD pipeline beyond Railway's GitHub auto-deploy. No staging environment.
- **Windows dev environment + Railway prod.** PowerShell + Railway SSH friction has been a recurring pain. Anything that requires `railway ssh` for routine ops should be rejected — admin pages or cron services preferred.
- **Anthropic Claude is the LLM.** Don't suggest swapping to OpenAI / Gemini / open models without strong justification; the viability prompt is tuned and tracing is wired up via LangSmith.

---

## 10. What kind of critique is most useful

In priority order:

1. **Correctness bugs** — if you spot something that's actually wrong, flag it.
2. **Security holes** — auth, SQL injection vectors, secret handling, CSRF.
3. **Architectural advice** — places where the current shape will not scale or will become painful.
4. **Specific code quality issues** — bad naming, wrong abstractions, dead code, missing error handling.
5. **Testing gaps** — what's most likely to break silently.
6. **Doctrinal corrections** — if any legal framing in the docs (Rule 23, *Amchem*, MDL etc.) is wrong, flag it.

What's NOT useful: nitpicks about formatting, suggestions to add features that aren't in the plan, suggesting a rewrite in a different framework. The system is a working MVP; we want sharper, not bigger.

---

*End of handoff doc. Repo at https://github.com/JimGoff518/signal (private). All file paths above are relative to repo root.*
