"""폐지 원장(alio_rule)과 검수 유형 ABOLISHED (spec 3.3).

review_task는 core 테이블이다. 0008에 이 변경이 없어서 overview §2.4에 따라 alio 이력에 넣는다.
kind CHECK는 기존 허용값을 읽어 'ABOLISHED'만 더한다. IN (...) 형태로 다시 만들어 pg가 같은 ARRAY['X'::text] 형식으로 보여 주므로 다시 읽을 수 있다. 다른 모듈이 같은 방식으로 값을 더해도 서로 지우지 않는다.
SQLAlchemy·psycopg 자리표시자와 섞이지 않도록 '%'를 쓰지 않는다.
"""
from alembic import op

revision = "a002"
down_revision = "a001"

ADD_KIND = """
DO $$
DECLARE def text; kinds text[];
BEGIN
  SELECT pg_get_constraintdef(oid) INTO def FROM pg_constraint
   WHERE conrelid = 'regulation.review_task'::regclass AND conname = 'review_task_kind_check';
  IF def IS NULL OR position('''ABOLISHED''' IN def) > 0 THEN RETURN; END IF;
  SELECT array_agg(m[1] ORDER BY m[1]) INTO kinds FROM regexp_matches(def, '''([A-Z_]+)''', 'g') AS m;
  IF kinds IS NULL THEN RAISE EXCEPTION USING MESSAGE = 'review_task_kind_check 형식을 읽지 못함: ' || def; END IF;
  ALTER TABLE regulation.review_task DROP CONSTRAINT review_task_kind_check;
  EXECUTE 'ALTER TABLE regulation.review_task ADD CONSTRAINT review_task_kind_check CHECK (kind IN ('
          || (SELECT string_agg(quote_literal(k), ', ') FROM unnest(array_append(kinds, 'ABOLISHED')) AS k) || '))';
END $$;
"""

DROP_KIND = """
DO $$
DECLARE def text; kinds text[];
BEGIN
  SELECT pg_get_constraintdef(oid) INTO def FROM pg_constraint
   WHERE conrelid = 'regulation.review_task'::regclass AND conname = 'review_task_kind_check';
  IF def IS NULL OR position('''ABOLISHED''' IN def) = 0 THEN RETURN; END IF;
  DELETE FROM regulation.review_task WHERE kind = 'ABOLISHED';
  SELECT array_agg(m[1] ORDER BY m[1]) INTO kinds FROM regexp_matches(def, '''([A-Z_]+)''', 'g') AS m;
  ALTER TABLE regulation.review_task DROP CONSTRAINT review_task_kind_check;
  EXECUTE 'ALTER TABLE regulation.review_task ADD CONSTRAINT review_task_kind_check CHECK (kind IN ('
          || (SELECT string_agg(quote_literal(k), ', ') FROM unnest(array_remove(kinds, 'ABOLISHED')) AS k) || '))';
END $$;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE regulation.alio_rule"
               " ADD COLUMN abolish_state text CHECK (abolish_state IN ('CANDIDATE', 'ABOLISHED')),"
               " ADD COLUMN abolished_on date")
    op.execute(ADD_KIND)


def downgrade() -> None:
    op.execute(DROP_KIND)
    op.execute("ALTER TABLE regulation.alio_rule DROP COLUMN abolished_on, DROP COLUMN abolish_state")
