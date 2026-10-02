"""M2b 보기용 PDF·참조·검수"""
from alembic import op

revision = "0003"
down_revision = "0002"

DDL = """
ALTER TABLE regulation.source_document
  ADD COLUMN view_blob_key text,
  ADD COLUMN view_status text NOT NULL DEFAULT 'pending'
    CHECK (view_status IN ('pending', 'ready', 'failed', 'not_needed'));
ALTER TABLE regulation.work_version
  ADD COLUMN validation_status text NOT NULL DEFAULT 'PASSED' CHECK (validation_status IN ('PASSED', 'REVIEW'));
CREATE TABLE regulation.reference (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  source_pv_id bigint NOT NULL REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  evidence_text text NOT NULL,
  span_start int NOT NULL,
  span_end int NOT NULL,
  rel_type text NOT NULL CHECK (rel_type IN ('BASIS', 'DELEGATION', 'IMPLEMENTS', 'MUTATIS', 'EXCEPTION', 'CITATION')),
  target_kind text NOT NULL CHECK (target_kind IN ('PROVISION', 'WORK', 'ANNEX', 'NONE', 'EXTERNAL_UNRESOLVED')),
  target_work_id text REFERENCES regulation.work(id),
  target_path text,
  target_name text,
  resolution text NOT NULL CHECK (resolution IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
  confidence real NOT NULL DEFAULT 1.0,
  extractor text NOT NULL DEFAULT 'rule',
  review_status text NOT NULL DEFAULT 'AUTO' CHECK (review_status IN ('AUTO', 'PENDING', 'ACCEPTED', 'REJECTED'))
);
CREATE INDEX reference_source ON regulation.reference (source_pv_id);
CREATE INDEX reference_target ON regulation.reference (target_work_id, target_path);
CREATE TABLE regulation.review_task (
  id bigserial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('PARSE', 'EFFECTIVE_DATE', 'REFERENCE', 'CONFLICT', 'LOW_TEXT')),
  target text NOT NULL,
  work_id text REFERENCES regulation.work(id) ON DELETE CASCADE,
  detail jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED', 'DISMISSED')),
  assignee text,
  decision jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  UNIQUE (kind, target)
);
CREATE TABLE regulation.law_seed (
  name text PRIMARY KEY,
  origin text NOT NULL CHECK (origin IN ('config', 'reference')),
  first_seen_work_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE regulation.law_seed; DROP TABLE regulation.review_task; DROP TABLE regulation.reference;"
               " ALTER TABLE regulation.work_version DROP COLUMN validation_status;"
               " ALTER TABLE regulation.source_document DROP COLUMN view_status, DROP COLUMN view_blob_key;")
