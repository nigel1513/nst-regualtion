"""검수 화면 개편 (서비스 UI 스펙 §6): 보류(HOLD) 상태와 사람 결정 보관.

- `review_task.status`에 `HOLD`를 더한다.
- `review_decision`: 사람이 내린 담당·결정을 `(kind, target)`으로 따로 둔다. FK가 없어 `reg process --rebuild`의
  `TRUNCATE … CASCADE`에 지워지지 않는다.
- `review_task` BEFORE INSERT 트리거가 같은 `(kind, target)`의 결정을 새 행에 되살린다. 작업을 만드는 곳(quality,
  ocr, alio, lawgo)은 고치지 않아도 된다. 단, 버전 단위 작업(PARSE·CONFLICT·EFFECTIVE_DATE)은 감지 내용(detail)이
  결정 때와 같을 때만 상태를 되살리고(내용이 바뀌면 새 문제), ABOLISHED는 alio_rule이 원장이라 담당만 되살린다.

통합 때 down_revision을 현재 core head로 다시 잇는다(트랙별 마이그레이션이 따로 생길 수 있음).
"""
from alembic import op

revision = "0013"
down_revision = "0010"

DDL = """
ALTER TABLE regulation.review_task DROP CONSTRAINT IF EXISTS review_task_status_check;
ALTER TABLE regulation.review_task ADD CONSTRAINT review_task_status_check
  CHECK (status IN ('OPEN', 'HOLD', 'RESOLVED', 'DISMISSED'));

CREATE TABLE regulation.review_decision (
  kind text NOT NULL,
  target text NOT NULL,
  status text NOT NULL CHECK (status IN ('OPEN', 'HOLD', 'RESOLVED', 'DISMISSED')),
  assignee text,
  decision jsonb,
  detail jsonb,
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, target)
);

CREATE FUNCTION regulation.review_task_apply_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d regulation.review_decision;
BEGIN
  SELECT * INTO d FROM regulation.review_decision WHERE kind = NEW.kind AND target = NEW.target;
  IF NOT FOUND THEN
    RETURN NEW;
  END IF;
  NEW.assignee := d.assignee;
  IF NEW.kind <> 'ABOLISHED'
     AND (NEW.kind NOT IN ('PARSE', 'CONFLICT', 'EFFECTIVE_DATE') OR d.detail IS NULL OR d.detail = NEW.detail) THEN
    NEW.status := d.status;
    NEW.decision := d.decision;
    NEW.resolved_at := d.resolved_at;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER review_task_apply_decision BEFORE INSERT ON regulation.review_task
  FOR EACH ROW EXECUTE FUNCTION regulation.review_task_apply_decision();

-- 이미 사람이 남긴 담당·결정이 있으면 옮긴다 (자동 결정 {"auto": …}은 옮기지 않는다)
INSERT INTO regulation.review_decision (kind, target, status, assignee, decision, detail, resolved_at)
SELECT kind, target, status, assignee, CASE WHEN decision ? 'by' THEN decision END, detail, resolved_at
FROM regulation.review_task WHERE assignee IS NOT NULL OR coalesce(decision ? 'by', false);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
DROP TRIGGER review_task_apply_decision ON regulation.review_task;
DROP FUNCTION regulation.review_task_apply_decision();
DROP TABLE regulation.review_decision;
UPDATE regulation.review_task SET status = 'OPEN' WHERE status = 'HOLD';
ALTER TABLE regulation.review_task DROP CONSTRAINT review_task_status_check;
ALTER TABLE regulation.review_task ADD CONSTRAINT review_task_status_check
  CHECK (status IN ('OPEN', 'RESOLVED', 'DISMISSED'));
""")
