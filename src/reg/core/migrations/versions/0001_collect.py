"""M1 수집 테이블"""
from alembic import op

revision = "0001"
down_revision = None

DDL = """
CREATE TABLE regulation.institution (
  id serial PRIMARY KEY,
  code text NOT NULL UNIQUE,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('NST', 'GRI')),
  alio_apba_id text UNIQUE,
  alio_name text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.fetch_run (
  id bigserial PRIMARY KEY,
  source text NOT NULL,
  scope text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  stats jsonb NOT NULL DEFAULT '{}',
  error text
);
CREATE TABLE regulation.request_log (
  id bigserial PRIMARY KEY,
  run_id bigint REFERENCES regulation.fetch_run(id),
  source text NOT NULL,
  url text NOT NULL,
  status int,
  bytes int,
  elapsed_ms int,
  waited_ms int,
  error text,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.source_document (
  id bigserial PRIMARY KEY,
  source text NOT NULL CHECK (source IN ('alio', 'lawgo')),
  sha256 text NOT NULL,
  blob_key text NOT NULL,
  mime text NOT NULL,
  size_bytes bigint NOT NULL,
  url text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  source_meta jsonb NOT NULL DEFAULT '{}',
  UNIQUE (source, sha256)
);
CREATE TABLE regulation.alio_rule (
  seq text PRIMARY KEY,
  institution_id int NOT NULL REFERENCES regulation.institution(id),
  title text NOT NULL,
  divis text,
  revised_on date,
  posted_on date,
  list_fingerprint text,
  detail jsonb NOT NULL DEFAULT '{}',
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.alio_rule_file (
  file_no text PRIMARY KEY,
  seq text NOT NULL REFERENCES regulation.alio_rule(seq),
  file_name text NOT NULL,
  ord int NOT NULL,
  status text NOT NULL CHECK (status IN ('fetched', 'rejected')),
  reject_reason text,
  source_document_id bigint REFERENCES regulation.source_document(id),
  fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE regulation.law_watch (
  law_id text PRIMARY KEY,
  name text NOT NULL,
  kind text,
  last_mst text,
  promulgated_on date,
  effective_on date,
  source_document_id bigint REFERENCES regulation.source_document(id),
  last_checked_at timestamptz
);
CREATE TABLE regulation.outbox (
  id bigserial PRIMARY KEY,
  topic text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  claimed_at timestamptz,
  processed_at timestamptz,
  attempts int NOT NULL DEFAULT 0
);
CREATE INDEX outbox_unprocessed ON regulation.outbox (id) WHERE processed_at IS NULL;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    for t in ["outbox", "law_watch", "alio_rule_file", "alio_rule", "source_document",
              "request_log", "fetch_run", "institution"]:
        op.execute(f"DROP TABLE regulation.{t}")
