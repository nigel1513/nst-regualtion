"""law 스키마: 현행 법령·행정규칙 미러, 별표, 카탈로그, 실행 이력, 변경 기록 + regulation 쪽 FK 열 (spec §3A.3, §3A.5).

FK 대상이 law에 있으므로 regulation.reference/work/work_version의 FK 열도 이 이력이 더한다 (판정 R1).
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "law_0001"
down_revision = None
NEW_KINDS = ["REF_LAW_AMBIGUOUS", "REF_LAW_GONE"]

DDL = """
CREATE TABLE law.law_master (
  law_id text PRIMARY KEY,
  family text NOT NULL CHECK (family IN ('law', 'admrul')),
  source_id text NOT NULL,
  name text NOT NULL,
  name_norm text NOT NULL,
  name_abbr text,
  abbr_norm text,
  kind text,
  ministry text,
  ministry_code text,
  current_mst text,
  status text NOT NULL DEFAULT '현행' CHECK (status IN ('현행', '폐지')),
  missing_since date,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_synced_at timestamptz,
  url text NOT NULL
);
CREATE INDEX law_master_name_norm ON law.law_master (name_norm);
CREATE INDEX law_master_abbr ON law.law_master (name_abbr) WHERE name_abbr IS NOT NULL;
CREATE INDEX law_master_abbr_norm ON law.law_master (abbr_norm) WHERE abbr_norm IS NOT NULL;

CREATE TABLE law.law_version (
  mst text PRIMARY KEY,
  law_id text NOT NULL REFERENCES law.law_master(law_id),
  promulgated_on date,
  promulgation_no text,
  effective_on date,
  revision_kind text,
  is_current boolean NOT NULL DEFAULT false,
  source_document_id bigint REFERENCES regulation.source_document(id),
  xml_url text NOT NULL,
  html_url text NOT NULL,
  articles_loaded boolean NOT NULL DEFAULT false,
  seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX law_version_one_current ON law.law_version (law_id) WHERE is_current;
CREATE INDEX law_version_source ON law.law_version (source_document_id);

CREATE TABLE law.article (
  id bigserial PRIMARY KEY,
  law_id text NOT NULL REFERENCES law.law_master(law_id),
  mst text NOT NULL REFERENCES law.law_version(mst),
  path text NOT NULL,
  unit text NOT NULL,
  parent_path text,
  jo_code text,
  label text NOT NULL,
  heading text,
  text text NOT NULL DEFAULT '',
  ord int NOT NULL,
  effective_on date,
  text_hash text NOT NULL,
  deleted boolean NOT NULL DEFAULT false,
  gone_in_mst text,
  url text,
  UNIQUE (law_id, path)
);
CREATE INDEX article_mst ON law.article (mst);

CREATE TABLE law.annex (
  seq text PRIMARY KEY,
  family text NOT NULL CHECK (family IN ('law', 'admrul')),
  law_id text NOT NULL REFERENCES law.law_master(law_id),
  mst text,
  number text,
  kind text,
  title text NOT NULL,
  promulgated_on date,
  file_path text,
  pdf_path text,
  view_url text NOT NULL,
  html_key text,
  pdf_key text,
  fetched_at timestamptz,
  is_current boolean NOT NULL DEFAULT true,
  first_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX annex_law ON law.annex (law_id);
CREATE INDEX annex_backlog ON law.annex (first_seen_at) WHERE html_key IS NULL AND is_current;

CREATE TABLE law.admrul_catalog (
  admrul_id text PRIMARY KEY,
  name text NOT NULL,
  name_norm text NOT NULL,
  kind text,
  ministry text,
  ministry_code text,
  current_seq text,
  issued_on date,
  issue_no text,
  effective_on date,
  revision_kind text,
  status text NOT NULL DEFAULT '현행',
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX admrul_catalog_name_norm ON law.admrul_catalog (name_norm);

CREATE TABLE law.sync_run (
  id bigserial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('daily', 'full', 'annex')),
  since date,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  stats jsonb NOT NULL DEFAULT '{}',
  error text
);

CREATE TABLE law.change_log (
  id bigserial PRIMARY KEY,
  run_id bigint REFERENCES law.sync_run(id),
  law_id text NOT NULL REFERENCES law.law_master(law_id),
  from_mst text,
  to_mst text,
  path text,
  change text NOT NULL CHECK (change IN ('added', 'modified', 'deleted', 'law_added', 'law_abolished')),
  label text,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX change_log_law ON law.change_log (law_id, at);

ALTER TABLE regulation.reference ADD COLUMN IF NOT EXISTS target_law_id text,
  ADD COLUMN IF NOT EXISTS target_law_article_id bigint;
ALTER TABLE regulation.reference
  ADD CONSTRAINT reference_target_law_fk FOREIGN KEY (target_law_id)
    REFERENCES law.law_master(law_id) ON DELETE SET NULL,
  ADD CONSTRAINT reference_target_law_article_fk FOREIGN KEY (target_law_article_id)
    REFERENCES law.article(id) ON DELETE SET NULL;
CREATE INDEX reference_target_law_article ON regulation.reference (target_law_article_id);
ALTER TABLE regulation.work ADD COLUMN IF NOT EXISTS law_id text;
ALTER TABLE regulation.work ADD CONSTRAINT work_law_fk FOREIGN KEY (law_id)
  REFERENCES law.law_master(law_id) ON DELETE SET NULL;
ALTER TABLE regulation.work_version ADD COLUMN IF NOT EXISTS law_mst text;
ALTER TABLE regulation.work_version ADD CONSTRAINT work_version_law_mst_fk FOREIGN KEY (law_mst)
  REFERENCES law.law_version(mst) ON DELETE SET NULL;

GRANT USAGE ON SCHEMA law TO reg_app;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA law TO reg_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA law TO reg_app;
"""


def _kind_check() -> tuple[str | None, list[str]]:
    row = op.get_bind().execute(sa.text(
        "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint"
        " WHERE conrelid = 'regulation.review_task'::regclass AND contype = 'c'"
        " AND position('kind' in pg_get_constraintdef(oid)) > 0")).mappings().first()
    return (row["conname"], re.findall(r"'([^']+)'", row["def"])) if row else (None, [])


def _set_kinds(kinds: list[str]) -> None:
    name, _ = _kind_check()
    if name:
        op.execute(f'ALTER TABLE regulation.review_task DROP CONSTRAINT "{name}"')
    allowed = ", ".join(f"'{k}'" for k in kinds)
    op.execute(f"ALTER TABLE regulation.review_task ADD CONSTRAINT review_task_kind_check CHECK (kind IN ({allowed}))")


def upgrade() -> None:
    op.execute(DDL)
    _, kinds = _kind_check()
    _set_kinds(list(dict.fromkeys(kinds + NEW_KINDS)))


def downgrade() -> None:
    _, kinds = _kind_check()
    op.execute("DELETE FROM regulation.review_task WHERE kind = ANY(ARRAY['REF_LAW_AMBIGUOUS', 'REF_LAW_GONE'])")
    _set_kinds([k for k in kinds if k not in NEW_KINDS])
    op.execute("""
ALTER TABLE regulation.work_version DROP CONSTRAINT work_version_law_mst_fk, DROP COLUMN law_mst;
ALTER TABLE regulation.work DROP CONSTRAINT work_law_fk, DROP COLUMN law_id;
DROP INDEX regulation.reference_target_law_article;
ALTER TABLE regulation.reference DROP CONSTRAINT reference_target_law_article_fk,
  DROP CONSTRAINT reference_target_law_fk, DROP COLUMN target_law_article_id, DROP COLUMN target_law_id;
DROP TABLE law.change_log, law.sync_run, law.admrul_catalog, law.annex, law.article, law.law_version,
  law.law_master;
""")
