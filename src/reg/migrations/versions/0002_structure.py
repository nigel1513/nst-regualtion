"""M2a 구조화·버전 테이블"""
from alembic import op

revision = "0002"
down_revision = "0001"

DDL = """
ALTER TABLE regulation.outbox ADD COLUMN last_error text;
CREATE TABLE regulation.work (
  id text PRIMARY KEY,
  kind text NOT NULL,
  institution_id int REFERENCES regulation.institution(id),
  title text NOT NULL,
  external_ids jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX work_alio_seq ON regulation.work ((external_ids->>'alio_seq')) WHERE external_ids ? 'alio_seq';
CREATE TABLE regulation.work_version (
  id text PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  source_document_id bigint NOT NULL REFERENCES regulation.source_document(id),
  title text NOT NULL,
  promulgated_on date,
  posted_on date,
  effective_from date,
  effective_to date,
  effective_basis text NOT NULL,
  effective_status text NOT NULL CHECK (effective_status IN ('CONFIRMED', 'UNCERTAIN', 'CONFLICT')),
  version_state text NOT NULL DEFAULT 'UNDATED'
    CHECK (version_state IN ('FUTURE', 'CURRENT', 'HISTORICAL', 'UNDATED')),
  amendment_kind text,
  amendment_no text,
  class_code text,
  parsed jsonb NOT NULL,
  parse_stats jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (work_id, source_document_id)
);
CREATE TABLE regulation.amendment_history (
  work_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  ord int NOT NULL,
  kind text NOT NULL,
  date date NOT NULL,
  number text,
  PRIMARY KEY (work_version_id, ord)
);
CREATE TABLE regulation.provision (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  lineage_key text NOT NULL,
  UNIQUE (work_id, lineage_key)
);
CREATE TABLE regulation.provision_version (
  id bigserial PRIMARY KEY,
  provision_id bigint NOT NULL REFERENCES regulation.provision(id) ON DELETE CASCADE,
  path text NOT NULL,
  unit text NOT NULL,
  number_label text NOT NULL,
  heading text,
  parent_path text,
  text text NOT NULL,
  text_norm_hash text NOT NULL,
  annotations jsonb NOT NULL DEFAULT '[]',
  deleted boolean NOT NULL DEFAULT false,
  effective_from_override date,
  source_anchor jsonb,
  meta jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE regulation.version_provision (
  work_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  provision_version_id bigint NOT NULL REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  ord int NOT NULL,
  PRIMARY KEY (work_version_id, provision_version_id)
);
CREATE TABLE regulation.provision_change (
  id bigserial PRIMARY KEY,
  work_id text NOT NULL REFERENCES regulation.work(id),
  from_version_id text REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  to_version_id text NOT NULL REFERENCES regulation.work_version(id) ON DELETE CASCADE,
  provision_id bigint NOT NULL REFERENCES regulation.provision(id) ON DELETE CASCADE,
  from_pv_id bigint REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  to_pv_id bigint REFERENCES regulation.provision_version(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('ADDED', 'MODIFIED', 'DELETED', 'RENUMBERED', 'ANNOTATION_ONLY'))
);
CREATE INDEX provision_change_to ON regulation.provision_change (to_version_id);
CREATE INDEX version_provision_pv ON regulation.version_provision (provision_version_id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    for t in ["provision_change", "version_provision", "provision_version", "provision", "amendment_history",
              "work_version", "work"]:
        op.execute(f"DROP TABLE regulation.{t}")
    op.execute("ALTER TABLE regulation.outbox DROP COLUMN last_error")
