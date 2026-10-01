-- Lane B mass-tort schema v1 + locked seed (PR1)
-- Spec: /workspace/goff-law/briefs/mass-tort-schema-v1-handoff-2026-10-01.md
-- Labels: /workspace/signal-searcher/mass-tort-jpml-2026-09-30/labels-locked.md
-- Locks: dash-only · no Filevine · no Jev on score/labels · invest_score NULL
-- Two-row rule: AI vs OpenAI; GLP-1 GI vs NAION — separate rows; parent_slug display-only

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  CREATE TYPE mass_tort_human_label AS ENUM ('WATCH', 'INVEST', 'CHASE', 'PASS');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS mass_tort_matters (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT UNIQUE NOT NULL,
  caption         TEXT NOT NULL,
  parent_slug     TEXT NULL,
  human_label     mass_tort_human_label NOT NULL,
  invest_score    INTEGER NULL CHECK (invest_score IS NULL OR (invest_score >= 0 AND invest_score <= 100)),
  mdl_or_jccp_id  TEXT NULL,
  court           TEXT NULL,
  pending_count   INTEGER NULL,
  last_event_at   TIMESTAMPTZ NULL,
  last_event_type TEXT NULL,
  source_urls     JSONB NOT NULL DEFAULT '[]'::jsonb,
  notes           TEXT NULL,
  priority_rank   INTEGER NULL,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mass_tort_matters_label
  ON mass_tort_matters (human_label);

CREATE INDEX IF NOT EXISTS idx_mass_tort_matters_priority
  ON mass_tort_matters (priority_rank ASC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_mass_tort_matters_parent
  ON mass_tort_matters (parent_slug) WHERE parent_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS mdl_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  matter_id   UUID NOT NULL REFERENCES mass_tort_matters(id) ON DELETE CASCADE,
  event_type  TEXT NOT NULL,
  event_date  DATE NULL,
  cite        TEXT NULL,
  source_url  TEXT NULL,
  summary     TEXT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mdl_events_matter
  ON mdl_events (matter_id, event_date DESC NULLS LAST);

-- 13 locked rows. invest_score left NULL (labels are source of truth).
-- Captions / MDL / court / pending from Searcher baselines; unknown → NULL.
-- Do not invent dockets.

INSERT INTO mass_tort_matters (
  slug, caption, parent_slug, human_label, invest_score,
  mdl_or_jccp_id, court, pending_count, source_urls, notes, priority_rank
) VALUES
  (
    'ai-litigation',
    'AI litigation (umbrella)',
    NULL,
    'INVEST',
    NULL,
    'MDL-3143',
    'S.D.N.Y.',
    19,
    '["https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf","https://www.courtlistener.com/docket/646469/in-re-openai-inc-copyright-infringement-litigation/"]'::jsonb,
    'Umbrella: copyright MDL-3143 granted (S.D.N.Y.); PI/suicide track is nested OpenAI row (JCCP 5431). Do not merge scores.',
    1
  ),
  (
    'openai-suicide-pl',
    'OpenAI suicide / product liability',
    'ai-litigation',
    'INVEST',
    NULL,
    'JCCP 5431',
    'SF Superior (CA)',
    NULL,
    '["https://openclassactions.com/blog/will-openai-pay-damages-consumers-states-before-2028.php","https://lawsuitinformer.com/jccp-5431-chatgpt-product-liability-cases"]'::jsonb,
    'Separate row under AI for display nesting only. CA JCCP 5431; no federal MDL verified. Pending count press-only (~12–24) — left NULL.',
    2
  ),
  (
    'galaxy-gas',
    'Galaxy Gas (N₂O)',
    NULL,
    'INVEST',
    NULL,
    NULL,
    NULL,
    NULL,
    '["https://www.aboutlawsuits.com/nitrous-oxide-lawsuit/judge-transfers-galaxy-gas-lawsuits-nitrous-oxide-canister-sales-same-court/"]'::jsonb,
    'Pre-MDL. Informal M.D. Fla. clustering; absent from JPML Sep 1 2026 pending list.',
    3
  ),
  (
    'roblox',
    'Roblox child exploitation',
    NULL,
    'INVEST',
    NULL,
    'MDL-3166',
    'N.D. Cal.',
    182,
    '["https://www.jpml.uscourts.gov/sites/jpml/files/MDL-3166-Transfer_Order-12-25.pdf","https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'In re Roblox Corp. Child Sexual Exploitation and Assault Litig. Distinct from social-media addiction MDL-3047.',
    4
  ),
  (
    'spinal-cord-stimulator',
    'Spinal cord stimulator (Boston Scientific)',
    NULL,
    'INVEST',
    NULL,
    'MDL-3181',
    'C.D. Cal.',
    29,
    '["https://www.jpml.uscourts.gov/sites/jpml/files/MDL-3181-Transfer_Order-5-26.pdf","https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'BSC-only MDL-3181. Abbott/Nevro petitions argued Sep 24 2026 — order not verified on free sources at harvest.',
    5
  ),
  (
    'glp1-gi',
    'GLP-1 GI / gastroparesis',
    NULL,
    'INVEST',
    NULL,
    'MDL-3094',
    'E.D. Pa.',
    4022,
    '["https://www.paed.uscourts.gov/mdl/mdl-3094-re-glucagon-peptide-1-receptor-agonists-glp-1-ras-products-liability-litigation-gi","https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'Separate from GLP-1 NAION (MDL-3163). Never merge scores.',
    6
  ),
  (
    'social-media-addiction',
    'Social media adolescent addiction',
    NULL,
    'WATCH',
    NULL,
    'MDL-3047',
    'N.D. Cal.',
    3208,
    '["https://cand.uscourts.gov/cases-e-filing/cases/422-md-03047-ygr/re-social-media-adolescent-addictionpersonal-injury-products","https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'Mature MDL; crowded for forming-MDL thesis.',
    NULL
  ),
  (
    'olympus-scope',
    'Olympus scope (duodenoscope infection)',
    NULL,
    'WATCH',
    NULL,
    NULL,
    NULL,
    NULL,
    '["https://www.classaction.org/olympus-scope-infection-lawsuit"]'::jsonb,
    'Pre-MDL. No JPML MDL on Sep 1 2026 list; no verified petition at harvest.',
    NULL
  ),
  (
    'chlorpyrifos',
    'Chlorpyrifos (Parkinson''s)',
    NULL,
    'WATCH',
    NULL,
    NULL,
    NULL,
    NULL,
    '["https://www.lawsuit-information-center.com/chlorpyrifos-lawsuit.html"]'::jsonb,
    'Pre-MDL. Early individual PI filings; no JPML petition verified.',
    NULL
  ),
  (
    'glp1-naion',
    'GLP-1 NAION (vision)',
    NULL,
    'WATCH',
    NULL,
    'MDL-3163',
    'E.D. Pa.',
    216,
    '["https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'Sibling of GLP-1 GI — separate row; parent_slug left NULL (display nesting reserved for OpenAI under AI).',
    NULL
  ),
  (
    'hair-relaxer',
    'Hair relaxer',
    NULL,
    'WATCH',
    NULL,
    'MDL-3060',
    'N.D. Ill.',
    12129,
    '["https://www.courtlistener.com/docket/65759955/in-re-hair-relaxer-marketing-sales-practices-and-products-liability/","https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'Large active MDL; pre-bellwether verdict.',
    NULL
  ),
  (
    'pfas-afff',
    'PFAS (AFFF)',
    NULL,
    'PASS',
    NULL,
    'MDL-2873',
    'D.S.C.',
    15264,
    '["https://www.jpml.uscourts.gov/sites/jpml/files/Pending_MDL_Dockets_By_Actions_Pending-September-1-2026.pdf"]'::jsonb,
    'Ultra-mature AFFF track; not early-warning formation signal.',
    NULL
  ),
  (
    'exactech',
    'Exactech polyethylene orthopedic',
    NULL,
    'PASS',
    NULL,
    'MDL-3044',
    'E.D.N.Y.',
    1838,
    '["https://www.courtlistener.com/docket/64875045/in-re-exactech-polyethylene-orthopedic-products-liability-litigation/","https://restructuring.ra.kroll.com/Exactech/Home-Index"]'::jsonb,
    'MDL live but bankruptcy-dominated (D. Del. 24-12441); inventory path is trust/BK.',
    NULL
  )
ON CONFLICT (slug) DO NOTHING;

COMMIT;
