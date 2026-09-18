-- SIGNAL Phase 1 — initial schema
-- Per docs/SIGNAL_TECHNICAL_SPEC.md §5.

BEGIN;

CREATE TABLE IF NOT EXISTS complaints (
  id                    SERIAL PRIMARY KEY,
  odi_number            VARCHAR(20) UNIQUE NOT NULL,
  manufacturer          VARCHAR(100),
  make                  VARCHAR(50)  NOT NULL,
  model                 VARCHAR(100) NOT NULL,
  model_year            INTEGER      NOT NULL,
  component_raw         VARCHAR(500),
  component             VARCHAR(50)  NOT NULL,           -- normalized category
  date_of_incident      DATE,
  date_complaint_filed  DATE,
  vin                   VARCHAR(20),
  crash                 BOOLEAN      NOT NULL DEFAULT FALSE,
  fire                  BOOLEAN      NOT NULL DEFAULT FALSE,
  injuries              INTEGER      NOT NULL DEFAULT 0,
  deaths                INTEGER      NOT NULL DEFAULT 0,
  description           TEXT,
  state                 VARCHAR(2),
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaints_lookup
  ON complaints (make, model, model_year, component);

CREATE INDEX IF NOT EXISTS idx_complaints_filed
  ON complaints (date_complaint_filed DESC);


CREATE TABLE IF NOT EXISTS clusters (
  id                    SERIAL PRIMARY KEY,
  cluster_key           VARCHAR(200) UNIQUE NOT NULL,
  make                  VARCHAR(50)  NOT NULL,
  model                 VARCHAR(100) NOT NULL,
  model_year            INTEGER,                          -- NULL for cross-year aggregates
  component             VARCHAR(50)  NOT NULL,
  is_multi_year         BOOLEAN      NOT NULL DEFAULT FALSE,
  complaint_count       INTEGER      NOT NULL DEFAULT 0,
  injury_count          INTEGER      NOT NULL DEFAULT 0,
  death_count           INTEGER      NOT NULL DEFAULT 0,
  crash_count           INTEGER      NOT NULL DEFAULT 0,
  fire_count            INTEGER      NOT NULL DEFAULT 0,
  velocity_7d           INTEGER      NOT NULL DEFAULT 0,
  velocity_30d          INTEGER      NOT NULL DEFAULT 0,
  score                 INTEGER      NOT NULL DEFAULT 0,
  classification        VARCHAR(20)  NOT NULL DEFAULT 'NOISE',
  nhtsa_investigation_open BOOLEAN   NOT NULL DEFAULT FALSE,
  recall_issued         BOOLEAN      NOT NULL DEFAULT FALSE,
  class_action_filed    BOOLEAN      NOT NULL DEFAULT FALSE,
  first_complaint_date  DATE,
  last_complaint_date   DATE,
  viability_memo        TEXT,
  memo_generated_at     TIMESTAMPTZ,
  memo_complaint_count_at_gen INTEGER,                    -- to detect "doubled since memo"
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clusters_score
  ON clusters (score DESC);

CREATE INDEX IF NOT EXISTS idx_clusters_classification
  ON clusters (classification);


CREATE TABLE IF NOT EXISTS cluster_complaints (
  cluster_id    INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
  complaint_id  INTEGER NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (cluster_id, complaint_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_complaints_complaint
  ON cluster_complaints (complaint_id);


CREATE TABLE IF NOT EXISTS ingestion_log (
  id                  SERIAL PRIMARY KEY,
  run_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  complaints_ingested INTEGER      NOT NULL DEFAULT 0,
  complaints_skipped  INTEGER      NOT NULL DEFAULT 0,
  clusters_touched    INTEGER      NOT NULL DEFAULT 0,
  errors              TEXT,
  status              VARCHAR(20)  NOT NULL DEFAULT 'RUNNING'
);


-- Track which clusters have triggered a death alert so we don't repeat.
CREATE TABLE IF NOT EXISTS alerts_sent (
  id            SERIAL PRIMARY KEY,
  cluster_id    INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
  alert_type    VARCHAR(30) NOT NULL,                     -- 'DEATH', 'PROMOTED_HOT', etc.
  sent_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (cluster_id, alert_type)
);

-- Phase 3a — CourtListener class-action filing detection (added 2026-05-09).
-- These columns are filled by scripts/check_filings.py querying CourtListener's
-- search API for each cluster's manufacturer/component, and are also reset by
-- subsequent re-checks. The class_action_filed boolean above (in the clusters
-- table) is the score-affecting flag; these columns provide audit trail.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_url TEXT;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_checked_at TIMESTAMPTZ;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_case_name TEXT;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_court TEXT;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_filed_date DATE;
-- 'pending' (still in court → -30 penalty) or 'terminated' (settled / dismissed
-- / SJ for defendant → hide entirely; class counsel chosen or case closed
-- means no opportunity for a new firm).
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_status TEXT;
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS class_action_terminated_date DATE;

CREATE INDEX IF NOT EXISTS idx_clusters_class_action_filed
  ON clusters (class_action_filed) WHERE class_action_filed = TRUE;
CREATE INDEX IF NOT EXISTS idx_clusters_class_action_status
  ON clusters (class_action_status) WHERE class_action_status IS NOT NULL;

-- Statute of limitations (added 2026-09-18). Complaints whose accrual date is
-- older than SOL_YEARS stay attached to the cluster but no longer count toward
-- any aggregate; this column records how many were set aside.
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS time_barred_count INTEGER NOT NULL DEFAULT 0;

COMMIT;
