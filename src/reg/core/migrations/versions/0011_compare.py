"""기관 비교 (서비스 UI 개편 spec §4): 규정 ↔ 주제(work_topic), 주제·항목 × 기관 비교값(compare_cell).

둘 다 다시 만들 수 있는 파생 데이터다(reg topics classify, reg compare build). 재파싱 때 provision_version id가 바뀌고
work를 다시 적재할 수 있으므로 외래키를 두지 않는다: 읽을 때 work와 조인하고, 조문은 (work_id, path)로 현행 판본에서
다시 찾는다. pv_id·version_id는 추출 당시의 기록이다."""
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
CREATE TABLE regulation.work_topic (
    work_id       text NOT NULL,
    topic         text NOT NULL,
    score         real NOT NULL,
    method        text NOT NULL CHECK (method IN ('title', 'purpose', 'embedding', 'none', 'manual')),
    rank          smallint NOT NULL DEFAULT 1 CHECK (rank IN (1, 2)),
    classified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (work_id, topic)
);
CREATE INDEX work_topic_topic ON regulation.work_topic (topic, work_id);

CREATE TABLE regulation.compare_cell (
    topic            text NOT NULL,
    item             text NOT NULL,
    institution_code text NOT NULL,
    work_id          text,
    version_id       text,
    pv_id            bigint,
    path             text,
    value            text,
    value_norm       text,
    quote            text,
    method           text NOT NULL CHECK (method IN ('llm', 'absent', 'manual')),
    confidence       real,
    extracted_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic, item, institution_code),
    CHECK (method = 'absent' OR (work_id IS NOT NULL AND path IS NOT NULL AND quote IS NOT NULL))
);
CREATE INDEX compare_cell_institution ON regulation.compare_cell (institution_code, topic, item);
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regulation.compare_cell, regulation.work_topic")
