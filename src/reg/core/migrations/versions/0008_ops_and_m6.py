"""운영 테이블을 ops 스키마로, M6 트랙이 쓸 컬럼·테이블 (overview §2.5)."""
from alembic import op

revision = "0008"
down_revision = "0007"
OPS = ["outbox", "fetch_run", "request_log", "release", "release_item", "qa_log", "change_impact",
       "owner_assignment", "notification", "email_delivery"]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")
    for t in OPS:
        op.execute(f"ALTER TABLE regulation.{t} SET SCHEMA ops")
    op.execute("""
ALTER TABLE regulation.work ADD COLUMN status text NOT NULL DEFAULT 'ACTIVE'
  CHECK (status IN ('ACTIVE', 'ABOLISHED_CANDIDATE', 'ABOLISHED')),
  ADD COLUMN abolished_on date;
ALTER TABLE regulation.work_version ADD COLUMN parser_version text;
ALTER TABLE regulation.source_document ADD COLUMN ocr_status text
  CHECK (ocr_status IN ('pending', 'ready', 'failed', 'not_needed')),
  ADD COLUMN ocr_blob_key text, ADD COLUMN ocr_engine text;
CREATE TABLE ops.pipeline_run (
  id bigserial PRIMARY KEY, dag_id text, run_id text, task_id text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
  stats jsonb NOT NULL DEFAULT '{}', error text);
CREATE INDEX ON ops.pipeline_run (started_at);
ALTER TABLE regulation.institution ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';
-- 목록 마스터: 규범문서 1행 = 기관 코드·이름·약칭 + 현행 버전 요약 (사용자 요구: 기관별 조회)
CREATE VIEW regulation.v_regulation_master AS
SELECT w.id AS work_id, w.title, w.kind, w.status, w.abolished_on,
       i.code AS institution_code, i.name AS institution_name, i.aliases AS institution_aliases,
       cv.id AS current_version_id, cv.effective_from, cv.effective_status,
       (SELECT count(*) FROM regulation.work_version v WHERE v.work_id = w.id)::int AS version_count,
       (SELECT count(*) FROM regulation.version_provision vp WHERE vp.work_version_id = cv.id)::int AS provisions,
       (SELECT max(sd.fetched_at) FROM regulation.work_version v
          JOIN regulation.source_document sd ON sd.id = v.source_document_id WHERE v.work_id = w.id) AS last_collected_at
FROM regulation.work w
LEFT JOIN regulation.institution i ON i.id = w.institution_id
LEFT JOIN regulation.work_version cv ON cv.work_id = w.id AND cv.version_state = 'CURRENT';
GRANT SELECT ON regulation.v_regulation_master TO reg_app;
CREATE TABLE ops.embedding_cache (
  text_hash text NOT NULL, model text NOT NULL, vector real[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (text_hash, model));""")


def downgrade() -> None:
    op.execute("DROP TABLE ops.embedding_cache; DROP TABLE ops.pipeline_run;"
               " DROP VIEW regulation.v_regulation_master; ALTER TABLE regulation.institution DROP COLUMN aliases;"
               " ALTER TABLE regulation.source_document DROP COLUMN ocr_engine, DROP COLUMN ocr_blob_key,"
               " DROP COLUMN ocr_status; ALTER TABLE regulation.work_version DROP COLUMN parser_version;"
               " ALTER TABLE regulation.work DROP COLUMN abolished_on, DROP COLUMN status;")
    for t in OPS:
        op.execute(f"ALTER TABLE ops.{t} SET SCHEMA regulation")
